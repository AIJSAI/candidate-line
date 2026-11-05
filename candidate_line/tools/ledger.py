"""The candidates and slots as the line sees them: the data files plus an overlay of what calls have changed.

Why an overlay: data/ is a committed synthetic fixture and is never rewritten, while a booking, a move request or a
callback must outlive the call that made it (var/state.json, spec.md section 3). Every change is written through at
once under one lock per file, so two calls on the phone never book the same slot. The same file keeps the count of
voice calls started each Central-time day, so the daily call cap (DR-021) holds across a restart.
"""

from __future__ import annotations

import copy
import fcntl
import hmac
import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from candidate_line.settings import Settings
from candidate_line.tools.codes import code_digits

DATA = Path(__file__).resolve().parents[2] / "data"
CANDIDATES_PATH = DATA / "candidates.yaml"
SLOTS_PATH = DATA / "slots.yaml"
# Six slots is about as many as a caller can hold in their head from one spoken list.
MAX_LISTED = 6
# The day the daily call cap counts in: the line's slots and its coordinator keep Central time (data/slots.yaml).
CENTRAL = ZoneInfo("America/Chicago")

log = logging.getLogger("candidate_line.ledger")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAY_ABBREVIATIONS = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "weds": 2, "thu": 3, "thur": 3, "thurs": 3}
_WEEKDAY_WORDS = {name.lower(): i for i, name in enumerate(_WEEKDAYS)} | _WEEKDAY_ABBREVIATIONS
_WEEKDAY_WORDS |= {"fri": 4, "sat": 5, "sun": 6}
_MONTH_ABBREVIATIONS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
}
_MONTH_WORDS = {name.lower(): i + 1 for i, name in enumerate(_MONTHS)} | _MONTH_ABBREVIATIONS
_MONTH_WORDS |= {"oct": 10, "nov": 11, "dec": 12}
# "am" and "pm" are left out on purpose: "I am free Friday" would otherwise mean Friday morning.
_PART_WORDS = {"morning": "morning", "afternoon": "afternoon", "evening": "afternoon"}
_DAY_TOKEN = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}|\d+(?:st|nd|rd|th)?|[a-z]+")
_SLOT_ID = re.compile(r"S?\s*(\d{4})\W*(\d{4})")


class LedgerError(Exception):
    """A refusal, with a kind the tool maps to what the model is told. The message is one plain sentence and
    never holds a PIN."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Candidate:
    """A row of data/candidates.yaml without its PIN, which stays inside the ledger so no repr or log can show it."""

    code: str
    name: str
    role: str
    stage: str
    invited_at: str
    booked_slot: str | None  # as the data file has it; Ledger.booked_slot adds the overlay
    moves_used: int
    callback_requested: bool

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name.strip() else ""


@dataclass(frozen=True)
class Slot:
    id: str
    start: datetime  # aware, in the data file's time zone
    duration_min: int
    interviewer: str
    status: str
    held_by: str | None

    @property
    def label(self) -> str:
        return spoken_label(self.start)


def spoken_label(start: datetime) -> str:
    """The words a caller hears for a slot, the same in every tool: "Thursday 5 November at 9:30 AM Central"."""
    hour = start.hour % 12 or 12
    half = "AM" if start.hour < 12 else "PM"
    day = f"{_WEEKDAYS[start.weekday()]} {start.day} {_MONTHS[start.month - 1]}"
    return f"{day} at {hour}:{start.minute:02d} {half} Central"


def normalise_slot_id(raw: object) -> str | None:
    """Reads "s1105-0930", "S1105 0930" and "S11050930" as S1105-0930."""
    m = _SLOT_ID.fullmatch(str(raw).strip().upper())
    return f"S{m.group(1)}-{m.group(2)}" if m else None


@dataclass(frozen=True)
class DayFilter:
    weekday: int | None = None
    day: int | None = None
    month: int | None = None
    part: str | None = None  # "morning" or "afternoon"

    def matches(self, start: datetime) -> bool:
        if self.weekday is not None and start.weekday() != self.weekday:
            return False
        if self.day is not None and start.day != self.day:
            return False
        if self.month is not None and start.month != self.month:
            return False
        if self.part == "morning" and start.hour >= 12:
            return False
        return not (self.part == "afternoon" and start.hour < 12)


def parse_day(text: object) -> DayFilter | None:
    """A day as a caller or the model names it: "Thursday", "Friday 6 November", "the 6th", "2026-11-06", "11/6",
    "Monday afternoon". None when nothing in it names a day, which is how "tomorrow" reads: the line does not do
    date arithmetic. A month counts only beside a day number, so "may" in "I may be free" is never May."""
    tokens = _DAY_TOKEN.findall(str(text or "").lower())
    weekday: int | None = None
    day: int | None = None
    month: int | None = None
    part: str | None = None
    ordinal: int | None = None
    for i, token in enumerate(tokens):
        if "-" in token:
            _, m, d = (int(x) for x in token.split("-"))
            month, day = m, d
        elif "/" in token:
            m, d = (int(x) for x in token.split("/"))
            month, day = m, d
        elif token[0].isdigit():
            if token[-1].isalpha() and 1 <= int(token.rstrip("stndrh")) <= 31:
                ordinal = int(token.rstrip("stndrh"))
        elif token in _WEEKDAY_WORDS:
            weekday = _WEEKDAY_WORDS[token]
        elif token in _PART_WORDS:
            part = _PART_WORDS[token]
        elif token in _MONTH_WORDS and day is None:
            near = _day_beside(tokens, i)
            if near is not None:
                month, day = _MONTH_WORDS[token], near
    if day is None and ordinal is not None:
        day = ordinal
    if weekday is None and day is None and part is None:
        return None
    return DayFilter(weekday=weekday, day=day, month=month, part=part)


def _day_beside(tokens: list[str], i: int) -> int | None:
    """The day number next to a month word, either side, skipping "the" and "of": "6 November", "November 6th",
    "the 6th of November"."""
    for step in (-1, 1):
        j = i + step
        while 0 <= j < len(tokens) and tokens[j] in ("the", "of"):
            j += step
        if 0 <= j < len(tokens) and tokens[j][0].isdigit() and "-" not in tokens[j] and "/" not in tokens[j]:
            number = int(tokens[j].rstrip("stndrh"))
            if 1 <= number <= 31:
                return number
    return None


def _zone(name: object) -> ZoneInfo | None:
    try:
        return ZoneInfo(str(name or "America/Chicago"))
    except (ZoneInfoNotFoundError, ValueError):
        return None  # the offsets written in the file still give the right instant


def _load_candidates(path: Path) -> tuple[dict[str, Candidate], dict[str, str]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    candidates: dict[str, Candidate] = {}
    pins: dict[str, str] = {}
    for row in doc.get("candidates", []):
        code = str(row["code"])
        # zfill, because a PIN written without quotes would load as a number and lose its leading zero.
        pins[code] = str(row["pin"]).zfill(4)
        candidates[code] = Candidate(
            code=code,
            name=str(row.get("name") or ""),
            role=str(row.get("role") or ""),
            stage=str(row.get("stage") or ""),
            invited_at=str(row.get("invited_at") or ""),
            booked_slot=str(row["booked_slot"]) if row.get("booked_slot") else None,
            moves_used=int(row.get("moves_used") or 0),
            callback_requested=bool(row.get("callback_requested")),
        )
    return candidates, pins


def _load_slots(path: Path) -> dict[str, Slot]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    zone = _zone(doc.get("timezone"))
    rows: list[Slot] = []
    for row in doc.get("slots", []):
        raw = row["start"]
        start = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        rows.append(
            Slot(
                id=str(row["id"]),
                start=start.astimezone(zone) if zone is not None else start,
                duration_min=int(row.get("duration_min") or 30),
                interviewer=str(row.get("interviewer") or ""),
                status=str(row.get("status") or "open"),
                held_by=str(row["held_by"]) if row.get("held_by") else None,
            )
        )
    return {s.id: s for s in sorted(rows, key=lambda s: s.start)}


def _empty_overlay() -> dict[str, Any]:
    return {"bookings": {}, "moves": [], "callbacks": [], "calls": {}}


_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_DEFAULTS: dict[str, Ledger] = {}
_DEFAULTS_GUARD = threading.Lock()


def _lock_for(state_path: Path | None) -> threading.RLock:
    """One lock per state file in this process, so two ledgers over one file still take turns."""
    if state_path is None:
        return threading.RLock()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(str(state_path.resolve()), threading.RLock())


class Ledger:
    """The line's state. `state_path=None` (or ":memory:") keeps every change in this object only, which is one
    call's worth in the tests, the evals and the walks; a path writes every change through to that file and reads
    it again whenever another process has changed it."""

    def __init__(
        self,
        candidates_path: Path | str = CANDIDATES_PATH,
        slots_path: Path | str = SLOTS_PATH,
        state_path: Path | str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_path = None if state_path in (None, ":memory:") else Path(state_path)
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = _lock_for(self._state_path)
        self._candidates, self._pins = _load_candidates(Path(candidates_path))
        self._by_digits = {code_digits(code): code for code in self._candidates}
        self._slots = _load_slots(Path(slots_path))
        self._overlay = _empty_overlay()
        self._seen: tuple[int, int] | None = None
        with self._lock:
            self._refresh(force=True)

    @classmethod
    def default(cls) -> Ledger:
        """The ledger over data/ and Settings.state_path. A file-backed one is shared by every call in the process,
        so its lock covers them all; an in-memory one is new each time, and the tools keep it on the call."""
        state = Settings.from_env().state_path
        if state is None:
            return cls()
        with _DEFAULTS_GUARD:
            ledger = _DEFAULTS.get(state)
            if ledger is None:
                ledger = _DEFAULTS[state] = cls(state_path=state)
            return ledger

    @property
    def state_path(self) -> Path | None:
        return self._state_path

    # Reads.

    def candidate(self, code: object) -> Candidate | None:
        digits = code_digits(code)
        found = self._by_digits.get(digits) if digits else None
        return self._candidates.get(found) if found else None

    def match(self, code: str, pin: str) -> Candidate | None:
        """The candidate these digits belong to (from code_digits and pin_digits), or None. Whether the code exists
        is never told apart from a wrong PIN, so a caller cannot learn which codes are real."""
        found = self.candidate(code)
        if found is None:
            return None
        return found if hmac.compare_digest(self._pins[found.code].encode(), pin.encode()) else None

    def mask_pin(self, code: str, text: str) -> str:
        """The text with this candidate's PIN taken out wherever its four digits stand alone, spaced or not, so
        free text a caller gave can be posted or saved. The PIN itself never leaves the ledger."""
        pin = self._pins.get(code)
        if not pin:
            return text
        return re.sub(r"(?<!\d)" + r"[ ,.-]?".join(pin) + r"(?!\d)", "****", text)

    def slot(self, slot_id: object) -> Slot | None:
        sid = normalise_slot_id(slot_id)
        return self._slots.get(sid) if sid else None

    def find_slot(self, text: object) -> Slot | None:
        """A slot by its id or by its spoken label, since a model sometimes passes the words it read out."""
        found = self.slot(text)
        if found is not None:
            return found
        wanted = re.sub(r"\s+", " ", str(text)).strip().lower().removesuffix(" central")
        return next(
            (s for s in self._slots.values() if s.label.lower().removesuffix(" central") == wanted), None
        )

    def booked_slot(self, code: str) -> Slot | None:
        with self._lock:
            self._refresh()
            sid = self._booked_id(code)
            return self._slots.get(sid) if sid else None

    def state(self, code: str) -> dict[str, Any]:
        """The candidate's fields as data/candidates.yaml names them, after every change the line has made."""
        with self._lock:
            self._refresh()
            cand = self._candidates[code]
            callback = cand.callback_requested or any(
                c.get("code") == code for c in self._overlay["callbacks"]
            )
            return {
                "booked_slot": self._booked_id(code),
                "moves_used": cand.moves_used,
                "callback_requested": callback,
            }

    def is_open(self, slot_id: object) -> bool:
        with self._lock:
            self._refresh()
            found = self.slot(slot_id)
            return found is not None and self._is_open(found, self._holders())

    def open_slots(self, day: DayFilter | None = None, limit: int = MAX_LISTED) -> list[Slot]:
        """Nearest first, from now on, less every slot a candidate holds in the data or the overlay."""
        with self._lock:
            self._refresh()
            holders = self._holders()
            found = [
                s
                for s in self._slots.values()
                if self._is_open(s, holders) and (day is None or day.matches(s.start))
            ]
            return found[:limit]

    def bookings(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._refresh()
            return copy.deepcopy(self._overlay["bookings"])

    def moves(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh()
            return copy.deepcopy(self._overlay["moves"])

    def callbacks(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh()
            return copy.deepcopy(self._overlay["callbacks"])

    def today(self) -> str:
        """The Central-time date now, as an ISO date: the day the daily call cap counts."""
        return self._now().astimezone(CENTRAL).date().isoformat()

    def calls_today(self) -> int:
        """The voice calls counted so far on today's Central-time date."""
        with self._lock:
            self._refresh()
            return int(self._overlay["calls"].get(self.today(), 0))

    # Changes, each written through before it returns.

    def book(self, code: str, slot_id: object, call_id: str | None = None) -> Slot:
        with self._exclusive():
            cand = self._candidates.get(code)
            if cand is None:
                raise LedgerError("unknown_candidate", "There is no candidate with that code.")
            if cand.stage == "first_round_done":
                raise LedgerError(
                    "first_round_done",
                    "This candidate's first round is done, so there is no slot to book. The coordinator "
                    "handles the next step.",
                )
            if self._booked_id(code):
                raise LedgerError("already_booked", "This candidate already holds a slot.")
            found = self.find_slot(slot_id)
            if found is None:
                raise LedgerError("unknown_slot", "There is no slot with that id.")
            if not self._is_open(found, self._holders()):
                raise LedgerError("not_open", "That slot is not open.")
            record = {"slot_id": found.id, "at": self._stamp_now(), "call_id": call_id}

            def change(overlay: dict[str, Any]) -> None:
                overlay["bookings"][code] = record

            self._commit(change)
            return found

    def unbook(self, code: str, slot_id: str) -> bool:
        """Takes back a booking this ledger made, and only that one: a superseded turn's undo must never release
        a slot the candidate held before the call."""
        with self._exclusive():
            held = self._overlay["bookings"].get(code)
            if not held or held.get("slot_id") != slot_id:
                return False
            self._commit(lambda overlay: overlay["bookings"].pop(code, None))
            return True

    def request_move(
        self, code: str, current: str | None, preferred: str | None, call_id: str | None = None
    ) -> dict[str, Any]:
        record = {
            "code": code,
            "current": current,
            "preferred": preferred,
            "call_id": call_id,
            "at": self._stamp_now(),
        }
        with self._exclusive():
            self._commit(lambda overlay: overlay["moves"].append(record))
        return dict(record)

    def count_call(self, day: str) -> int:
        """Counts one voice call started on `day` (an ISO date, Central time) and returns the day's count with it.
        Written through like a booking and under the same lock, so two calls at one moment get two numbers."""
        with self._exclusive():
            count = int(self._overlay["calls"].get(day, 0)) + 1
            self._commit(lambda overlay: overlay["calls"].__setitem__(day, count))
            return count

    def request_callback(
        self, code: str | None, best_time: str | None, reason: str | None, call_id: str | None = None
    ) -> dict[str, Any]:
        """An unverified caller is recorded with no code; the call id joins it to the trace and its masked number."""
        record = {
            "code": code,
            "best_time": best_time,
            "reason": reason,
            "call_id": call_id,
            "at": self._stamp_now(),
        }
        with self._exclusive():
            self._commit(lambda overlay: overlay["callbacks"].append(record))
        return dict(record)

    # Inside the lock.

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """The thread lock, and for a file-backed ledger an advisory lock on a file beside it, so a text-mode walk
        and the phone booking at the same moment in two processes still take turns. The file is read afresh inside
        the lock, because the other process may have written it a moment ago."""
        with self._lock:
            if self._state_path is None:
                yield
                return
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_path.with_name(f"{self._state_path.name}.lock"), "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    self._refresh(force=True)
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _booked_id(self, code: str) -> str | None:
        held = self._overlay["bookings"].get(code)
        if held:
            return str(held["slot_id"])
        cand = self._candidates.get(code)
        return cand.booked_slot if cand else None

    def _holders(self) -> dict[str, str]:
        held = {s.id: s.held_by for s in self._slots.values() if s.held_by}
        held |= {c.booked_slot: c.code for c in self._candidates.values() if c.booked_slot}
        held |= {str(b["slot_id"]): code for code, b in self._overlay["bookings"].items()}
        return held

    def _is_open(self, slot: Slot, holders: dict[str, str]) -> bool:
        return slot.status == "open" and slot.id not in holders and slot.start > self._now()

    def _stamp_now(self) -> str:
        return self._now().astimezone(UTC).isoformat(timespec="seconds")

    def _file_stamp(self) -> tuple[int, int] | None:
        if self._state_path is None:
            return None
        try:
            st = os.stat(self._state_path)
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _refresh(self, force: bool = False) -> None:
        if self._state_path is None:
            return
        stamp = self._file_stamp()
        if not force and stamp == self._seen:
            return
        self._overlay = self._read_overlay()
        self._seen = stamp

    def _read_overlay(self) -> dict[str, Any]:
        assert self._state_path is not None
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_overlay()
        except (OSError, ValueError) as error:
            return self._set_aside(f"{type(error).__name__}")
        if not isinstance(raw, dict):
            return self._set_aside("not an object")
        overlay = _empty_overlay()
        bookings = raw.get("bookings")
        if isinstance(bookings, dict):
            overlay["bookings"] = {
                str(code): dict(b)
                for code, b in bookings.items()
                if isinstance(b, dict) and isinstance(b.get("slot_id"), str)
            }
        for key in ("moves", "callbacks"):
            items = raw.get(key)
            if isinstance(items, list):
                overlay[key] = [dict(item) for item in items if isinstance(item, dict)]
        calls = raw.get("calls")
        if isinstance(calls, dict):
            # bool is an int in Python; a count is a whole number and nothing else.
            overlay["calls"] = {
                str(day): n
                for day, n in calls.items()
                if isinstance(n, int) and not isinstance(n, bool) and n >= 0
            }
        return overlay

    def _set_aside(self, why: str) -> dict[str, Any]:
        """A state file that cannot be read is kept beside the new one for a person to look at, not overwritten."""
        assert self._state_path is not None
        aside = self._state_path.with_name(
            f"{self._state_path.name}.bad-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        )
        try:
            os.replace(self._state_path, aside)
            log.warning("state file unreadable (%s); set aside as %s", why, aside.name)
        except OSError:
            log.warning("state file unreadable (%s) and could not be set aside", why)
        return _empty_overlay()

    def _commit(self, change: Callable[[dict[str, Any]], object]) -> None:
        """Applies a change and writes it through; if the write fails the change is taken back, so the caller is
        never told about a booking that a restart would lose."""
        before = copy.deepcopy(self._overlay)
        change(self._overlay)
        try:
            self._write()
        except OSError as error:
            self._overlay = before
            log.error("state file write failed: %s", type(error).__name__)
            raise LedgerError("unsaved", "The change could not be saved.") from error

    def _write(self) -> None:
        if self._state_path is None:
            return
        parent = self._state_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=f".{self._state_path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, **self._overlay}, f, indent=2, sort_keys=True)
                f.write("\n")
            # A rename is atomic, so a reader in another process sees the old file or the new one, never half.
            os.replace(tmp, self._state_path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._seen = self._file_stamp()
