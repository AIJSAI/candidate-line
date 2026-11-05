"""The candidates, the applicants and the slots as the line sees them: the data files plus an overlay of what
calls have changed.

Why an overlay: data/ is a committed synthetic fixture and is never rewritten, while a booking, a move request, a
callback, an application that came through intake, a recorded answer, a dial or an opt-out must outlive the call
that made it (var/state.json, spec.md sections 3 and 9). Every change is written through at once under one lock per
file, so two calls never book the same slot and two diallers never place the same dial. The same file keeps the
count of voice calls started each Central-time day, so the daily call cap (DR-021) holds across a restart.

Why no raw phone number and no PIN digit here: the raw number lives only in the contacts store, read only by the
dialler (DR-025 section 9), and an intake PIN is kept as a keyed HMAC, because a four-digit PIN has 10,000 values
and an unkeyed hash of one is no protection. The file is written through tempfile.mkstemp, so it is mode 600, since
it holds first names and answers.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from candidate_line.settings import Settings
from candidate_line.tools.codes import code_digits, code_label

DATA = Path(__file__).resolve().parents[2] / "data"
CANDIDATES_PATH = DATA / "candidates.yaml"
SLOTS_PATH = DATA / "slots.yaml"
APPLICATIONS_PATH = DATA / "applications.yaml"
ROLES_PATH = DATA / "roles.yaml"
# Six slots is about as many as a caller can hold in their head from one spoken list.
MAX_LISTED = 6
# The day the daily call cap counts in: the line's slots and its coordinator keep Central time (data/slots.yaml).
CENTRAL = ZoneInfo("America/Chicago")

# The purposes derive_key is given, so the PIN hashes and the number hashes each have their own key and neither
# shares one with the intake signature (DR-025 section 7). Intake hashes a number with NUMBER_PURPOSE.
PIN_PURPOSE = "pin"
NUMBER_PURPOSE = "number"

# DR-025 section 8.
DIAL_STATUSES = frozenset({"due", "claimed", "placed", "in-progress", "done", "cancelled", "failed"})
LIVE_DIAL_STATUSES = frozenset({"claimed", "placed", "in-progress"})
DIAL_OUTCOMES = frozenset(
    {
        "screened",
        "screen_unfinished",
        "voicemail",
        "machine",
        "no_answer",
        "busy",
        "failed",
        "opted_out",
        "wrong_person",
        "pin_missed",
        "hung_up_before_pin",
        "kill",
        "not_allowed",
    }
)
# DR-025 section 7.
OPT_OUT_HOWS = ("said on the call", "said stop", "wrong person", "operator", "deletion")
NOT_DIALLED_REASONS = ("no_consent", "opted_out", "not_allowed")
SCREEN_RESULTS = ("met", "not_met")
# A value record_answer writes is one of these, an option id the role posted, or a whole number of three digits at
# most, so a PIN can never be stored as an answer whatever the model passes (DR-025 section 3).
PLAIN_VALUES = frozenset({"yes", "no", "declined", "unclear"})
_NUMBER_VALUE = re.compile(r"[0-9]{1,3}")
# The applicant's own words are scrubbed by the tool before they come here; this cap and the digit mask below are
# the ledger's own backstop, so a slip upstream never writes a PIN or a number to the file.
MAX_HEARD = 500
_DIGIT_RUN = re.compile(r"(?<![0-9])[0-9](?:[ ,.-]?[0-9]){3,}(?![0-9])")
_NONCE = re.compile(r"[A-Za-z0-9_-]{22,64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")

_DIAL_FIELDS = frozenset(
    {
        "due_at",
        "status",
        "claimed_at",
        "placed_at",
        "call_sid",
        "twilio_status",
        "answered_at",
        "answered_by",
        "voicemail_left",
        "ended_at",
        "outcome",
    }
)
_DIAL_STAMPS = frozenset({"due_at", "claimed_at", "placed_at", "answered_at", "ended_at"})
_OVERLAY_KEYS = ("bookings", "moves", "callbacks", "calls", "applications", "answers", "dials", "opt_outs")

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
class Applicant:
    """An application, from data/applications.yaml or from intake, without its PIN or its number: the PIN never
    leaves the ledger and the raw number never enters it (DR-025 section 7)."""

    code: str
    first_name: str
    role: str  # a role id in data/roles.yaml
    zone: str  # an IANA zone
    received_at: str  # ISO, with its offset
    consent: Mapping[str, Any]  # version, text_sha256, accepted, at, source
    number_hmac: str | None  # None for the fixtures, which hold no number

    @property
    def consented(self) -> bool:
        return self.consent.get("accepted") is True


@dataclass(frozen=True)
class Slot:
    id: str
    start: datetime  # aware, in the data file's time zone
    duration_min: int
    interviewer: str  # for a recruiter's interview slot, the recruiter's label
    status: str
    held_by: str | None

    @property
    def label(self) -> str:
        return spoken_label(self.start)


@dataclass(frozen=True)
class _RolePlan:
    """What the ledger needs of a role: its recruiter, whose interview slots alone it may book, and its posted
    questions with the option ids each takes, so a value outside them is never written. The loader with every
    refusal of DR-025 section 4 is tools/roles.py; this reads only these fields, so the ledger never depends on it."""

    recruiter: str
    questions: tuple[str, ...]  # in posted order
    options: Mapping[str, frozenset[str]]  # question id to its option ids; empty for yes_no and range


def derive_key(root: str, purpose: str) -> bytes:
    """A key for one purpose, derived from INTAKE_SIGNING_KEY: HMAC-SHA256(root, "candidate-line " + purpose)."""
    return hmac.new(root.encode(), f"candidate-line {purpose}".encode(), hashlib.sha256).digest()


def pin_hmac(key: bytes, code: str, pin: str) -> str:
    """The code is inside the MAC, so two applicants who chose the same PIN never share a stored value."""
    return hmac.new(key, f"{code}:{pin}".encode(), hashlib.sha256).hexdigest()


def number_hmac(key: bytes, e164: str) -> str:
    """A number's HMAC, so an opt-out outlives the raw number and a later application from it is never dialled."""
    return hmac.new(key, e164.encode(), hashlib.sha256).hexdigest()


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


def _stamp(when: datetime) -> str:
    """Times as the ledger writes them: ISO UTC to the second."""
    if when.tzinfo is None:
        raise LedgerError("bad_time", "A time the ledger writes must carry its zone.")
    return when.astimezone(UTC).isoformat(timespec="seconds")


def _instant(value: object) -> datetime | None:
    """A stamp from the file as an aware instant, or None when it is missing or does not parse."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def central_day(when: datetime) -> str:
    """The Central-time date of an instant, as an ISO date: the day the daily caps count."""
    return when.astimezone(CENTRAL).date().isoformat()


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


def _slot(row: Mapping[str, Any], zone: ZoneInfo | None, interviewer: str) -> Slot:
    raw = row["start"]
    start = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    return Slot(
        id=str(row["id"]),
        start=start.astimezone(zone) if zone is not None else start,
        duration_min=int(row.get("duration_min") or 30),
        interviewer=interviewer,
        status=str(row.get("status") or "open"),
        held_by=str(row["held_by"]) if row.get("held_by") else None,
    )


def _load_slots(path: Path) -> dict[str, Slot]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    zone = _zone(doc.get("timezone"))
    rows = [_slot(row, zone, str(row.get("interviewer") or "")) for row in doc.get("slots", [])]
    return {s.id: s for s in sorted(rows, key=lambda s: s.start)}


def _read_yaml(path: Path) -> dict[str, Any]:
    """A data file that is not there reads as empty, so a ledger over another folder's candidates still opens."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return doc if isinstance(doc, dict) else {}


def consent_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _consent_record(raw: Mapping[str, Any], texts: Mapping[str, str]) -> dict[str, Any]:
    """The consent as the ledger keeps it: the version, the SHA-256 of the text that version showed, accepted or
    not, when and from where (DR-025, Security)."""
    version = str(raw.get("version") or "")
    text = texts.get(version)
    at = raw.get("at")
    return {
        "version": version,
        "text_sha256": consent_sha256(text) if text is not None else None,
        "accepted": raw.get("accepted") is True,
        "at": at.isoformat() if isinstance(at, datetime) else (str(at) if at is not None else None),
        "source": str(raw.get("source") or "") or None,
    }


def load_applications(
    path: Path = APPLICATIONS_PATH,
) -> tuple[dict[str, Applicant], dict[str, str], dict[str, str]]:
    """The fixtures of data/applications.yaml as applicants, their PINs apart, and the consent texts by version.
    The PINs are returned beside the applicants, never inside one, so no repr can show them."""
    doc = _read_yaml(path)
    texts = {str(k): str(v) for k, v in (doc.get("consent_texts") or {}).items()}
    applicants: dict[str, Applicant] = {}
    pins: dict[str, str] = {}
    for row in doc.get("applications") or []:
        code = str(row["code"])
        pins[code] = str(row["pin"]).zfill(4)
        applied = row.get("applied_at")
        applicants[code] = Applicant(
            code=code,
            first_name=str(row.get("first_name") or ""),
            role=str(row.get("role") or ""),
            zone=str(row.get("zone") or "America/Chicago"),
            received_at=applied.isoformat() if isinstance(applied, datetime) else str(applied or ""),
            consent=MappingProxyType(_consent_record(row.get("consent") or {}, texts)),
            number_hmac=None,
        )
    return applicants, pins, texts


def load_role_plans(path: Path = ROLES_PATH) -> tuple[dict[str, _RolePlan], dict[str, Slot]]:
    """Each role's recruiter and posted question ids, and the recruiters' interview slots, nearest first in
    Central time (data/roles.yaml)."""
    doc = _read_yaml(path)
    plans: dict[str, _RolePlan] = {}
    for role in doc.get("roles") or []:
        questions = tuple(str(q["id"]) for q in role.get("questions") or [])
        options = {
            str(q["id"]): frozenset(str(o["id"]) for o in q.get("options") or [])
            for q in role.get("questions") or []
        }
        plans[str(role["id"])] = _RolePlan(
            recruiter=str(role.get("recruiter") or ""),
            questions=questions,
            options=MappingProxyType(options),
        )
    rows = [_slot(row, CENTRAL, str(row.get("recruiter") or "")) for row in doc.get("interview_slots") or []]
    return plans, {s.id: s for s in sorted(rows, key=lambda s: s.start)}


def _empty_overlay() -> dict[str, Any]:
    return {
        "bookings": {},
        "moves": [],
        "callbacks": [],
        "calls": {},
        "applications": {},
        "answers": {},
        "dials": [],
        "opt_outs": [],
    }


def _blank_answers() -> dict[str, Any]:
    return {"by_question": {}, "screen": None}


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


def _pin_key(settings: Settings) -> bytes | None:
    """The PIN key from INTAKE_SIGNING_KEY (DR-025 section 11); without it no intake application can be stored or
    matched."""
    root = settings.intake_signing_key
    return derive_key(root, PIN_PURPOSE) if root else None


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
        applications_path: Path | str = APPLICATIONS_PATH,
        roles_path: Path | str = ROLES_PATH,
        pin_key: bytes | None = None,
    ) -> None:
        self._state_path = None if state_path in (None, ":memory:") else Path(str(state_path))
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = _lock_for(self._state_path)
        self._pin_key = pin_key
        self._candidates, self._pins = _load_candidates(Path(candidates_path))
        self._by_digits = {code_digits(code): code for code in self._candidates}
        self._slots = _load_slots(Path(slots_path))
        self._fixtures, self._applicant_pins, self._consent_texts = load_applications(Path(applications_path))
        self._roles, self._interview_slots = load_role_plans(Path(roles_path))
        self._overlay = _empty_overlay()
        self._seen: tuple[int, int] | None = None
        with self._lock:
            self._refresh(force=True)

    @classmethod
    def default(cls) -> Ledger:
        """The ledger over data/ and Settings.state_path. A file-backed one is shared by every call in the process,
        so its lock covers them all; an in-memory one is new each time, and the tools keep it on the call."""
        settings = Settings.from_env()
        state = settings.state_path
        if state is None:
            return cls(pin_key=_pin_key(settings))
        with _DEFAULTS_GUARD:
            ledger = _DEFAULTS.get(state)
            if ledger is None:
                ledger = _DEFAULTS[state] = cls(state_path=state, pin_key=_pin_key(settings))
            return ledger

    @property
    def state_path(self) -> Path | None:
        return self._state_path

    # Reads.

    def candidate(self, code: object) -> Candidate | None:
        digits = code_digits(code)
        found = self._by_digits.get(digits) if digits else None
        return self._candidates.get(found) if found else None

    def applicant(self, code: object) -> Applicant | None:
        """An application by its code, from the fixtures or from intake; None for a code that is neither."""
        with self._lock:
            self._refresh()
            return self._applicant(code)

    def match(self, code: str, pin: str) -> Candidate | Applicant | None:
        """The candidate or the applicant these digits belong to (from code_digits and pin_digits), or None.
        Whether the code exists is never told apart from a wrong PIN, so a caller cannot learn which codes are
        real."""
        found = self.candidate(code)
        if found is not None:
            return found if hmac.compare_digest(self._pins[found.code].encode(), pin.encode()) else None
        return self.match_applicant_pin(code, pin)

    def match_applicant_pin(self, code: str, pin: str) -> Applicant | None:
        """The applicant whose PIN these four digits are: the fixture's PIN compared as digits, an intake PIN as
        its HMAC, each in constant time. None without a PIN key for an intake application."""
        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
            return None
        with self._lock:
            self._refresh()
            app = self._applicant(code)
            if app is None:
                return None
            fixture_pin = self._applicant_pins.get(app.code)
            if fixture_pin is not None:
                return app if hmac.compare_digest(fixture_pin.encode(), pin.encode()) else None
            stored = self._overlay["applications"].get(app.code, {}).get("pin_hmac")
            if self._pin_key is None or not isinstance(stored, str):
                return None
            return app if hmac.compare_digest(stored, pin_hmac(self._pin_key, app.code, pin)) else None

    def mask_pin(self, code: str, text: str) -> str:
        """The text with this candidate's or fixture applicant's PIN taken out wherever its four digits stand alone,
        spaced or not, so free text a caller gave can be posted or saved. The PIN itself never leaves the ledger.
        An intake PIN is held only as its HMAC, so it cannot be found in text here; the tools mask digit runs."""
        pin = self._pins.get(code) or self._applicant_pins.get(code)
        if not pin:
            return text
        return re.sub(r"(?<!\d)" + r"[ ,.-]?".join(pin) + r"(?!\d)", "****", text)

    def slot(self, slot_id: object) -> Slot | None:
        """A first-round slot of data/slots.yaml; a recruiter's interview slot is found with `interview_slot`."""
        sid = normalise_slot_id(slot_id)
        return self._slots.get(sid) if sid else None

    def interview_slot(self, slot_id: object) -> Slot | None:
        sid = normalise_slot_id(slot_id)
        return self._interview_slots.get(sid) if sid else None

    def find_slot(self, text: object, recruiter: str | None = None) -> Slot | None:
        """A slot by its id or by its spoken label, since a model sometimes passes the words it read out. With a
        recruiter, only that recruiter's interview slots are searched, so an applicant never books a first-round
        slot and a candidate never books an interview slot."""
        pool = (
            {k: s for k, s in self._interview_slots.items() if s.interviewer == recruiter}
            if recruiter is not None
            else self._slots
        )
        sid = normalise_slot_id(text)
        if sid and sid in pool:
            return pool[sid]
        wanted = re.sub(r"\s+", " ", str(text)).strip().lower().removesuffix(" central")
        return next((s for s in pool.values() if s.label.lower().removesuffix(" central") == wanted), None)

    def booked_slot(self, code: str) -> Slot | None:
        with self._lock:
            self._refresh()
            sid = self._booked_id(code)
            return self._any_slot(sid) if sid else None

    def state(self, code: str) -> dict[str, Any]:
        """A candidate's fields as data/candidates.yaml names them, after every change the line has made; for an
        applicant, the screen's state as DR-025 section 7 names it. A candidate's state is as it always was."""
        with self._lock:
            self._refresh()
            if code not in self._candidates:
                app = self._applicant(code)
                if app is not None:
                    return self._applicant_state(app)
            cand = self._candidates[code]
            return {
                "booked_slot": self._booked_id(code),
                "moves_used": cand.moves_used,
                "callback_requested": cand.callback_requested or self._callback_for(code),
            }

    def is_open(self, slot_id: object) -> bool:
        with self._lock:
            self._refresh()
            found = self.slot(slot_id) or self.interview_slot(slot_id)
            return found is not None and self._is_open(found, self._holders())

    def open_slots(
        self, day: DayFilter | None = None, limit: int = MAX_LISTED, recruiter: str | None = None
    ) -> list[Slot]:
        """Nearest first, from now on, less every slot a candidate or an applicant holds in the data or the overlay.
        With a recruiter, that recruiter's interview slots only (data/roles.yaml); without, the first-round slots."""
        with self._lock:
            self._refresh()
            holders = self._holders()
            pool = (
                [s for s in self._interview_slots.values() if s.interviewer == recruiter]
                if recruiter is not None
                else list(self._slots.values())
            )
            found = [s for s in pool if self._is_open(s, holders) and (day is None or day.matches(s.start))]
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
        return central_day(self._now())

    def calls_today(self) -> int:
        """The voice calls counted so far on today's Central-time date."""
        with self._lock:
            self._refresh()
            return int(self._overlay["calls"].get(self.today(), 0))

    def nonce_seen(self, nonce: str, since: datetime) -> bool:
        """Whether an application received since then carries this intake nonce, so a replay inside the ten
        minutes is refused after a restart too (DR-025 section 10)."""
        with self._lock:
            self._refresh()
            for record in self._overlay["applications"].values():
                received = _instant(record.get("received_at"))
                if record.get("nonce") == nonce and received is not None and received >= since:
                    return True
            return False

    def answers(self, code: str) -> dict[str, dict[str, Any]]:
        """The recorded answers by question id: value, heard, at and call_id."""
        with self._lock:
            self._refresh()
            entry = self._overlay["answers"].get(self._canonical(code))
            return copy.deepcopy(entry["by_question"]) if entry else {}

    def screen(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh()
            entry = self._overlay["answers"].get(self._canonical(code))
            return copy.deepcopy(entry["screen"]) if entry and entry.get("screen") else None

    def opted_out(self, code: str | None = None, number_hmac: str | None = None) -> bool:
        """Whether an opt-out holds for this code or this number's HMAC. A code's own number counts too, so an
        application from a number that opted out under another code reads as opted out."""
        with self._lock:
            self._refresh()
            app = self._applicant(code) if code else None
            if app is not None and self._is_opted_out(app.code, app.number_hmac):
                return True
            return self._is_opted_out(self._canonical(code) if code else None, number_hmac)

    def dial(self, key: str) -> dict[str, Any] | None:
        """One dial record by its dial id or its CallSid."""
        with self._lock:
            self._refresh()
            found = self._find_dial(key)
            return copy.deepcopy(found) if found else None

    def dials(self, code: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh()
            wanted = self._canonical(code) if code else None
            return [
                copy.deepcopy(d) for d in self._overlay["dials"] if wanted is None or d.get("code") == wanted
            ]

    def dials_placed_today(self) -> int:
        """The dials placed so far on today's Central-time date, as calls_today counts calls."""
        with self._lock:
            self._refresh()
            return self._placed_on(self.today())

    # Changes, each written through before it returns.

    def book(self, code: str, slot_id: object, call_id: str | None = None) -> Slot:
        with self._exclusive():
            cand = self._candidates.get(code)
            app = None if cand is not None else self._applicant(code)
            if cand is None and app is None:
                raise LedgerError("unknown_candidate", "There is no candidate with that code.")
            if app is not None:
                found = self._applicant_slot(app, slot_id)
                code = app.code
            else:
                assert cand is not None
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
            booked = code

            def change(overlay: dict[str, Any]) -> None:
                overlay["bookings"][booked] = record

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

    def add_application(
        self,
        *,
        first_name: str,
        role: str,
        zone: str,
        pin: str,
        consent: Mapping[str, Any],
        number_hmac: str | None,
        number_masked: str | None,
        nonce: str,
        not_dialled: str | None = None,
        received_at: datetime | None = None,
    ) -> Applicant:
        """Stores an application that came through intake under a new code, its PIN as an HMAC and its number as
        an HMAC and the masked form. Intake has checked the schema; the refusals here are the ledger's own lock, so
        a bad caller of this method can never write a raw number, a PIN or an unknown role."""
        if self._pin_key is None:
            raise LedgerError("no_pin_key", "The PIN key is not set, so no application can be stored.")
        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
            raise LedgerError("bad_pin", "The PIN must be four digits.")
        if role not in self._roles:
            raise LedgerError("unknown_role", "There is no role with that id.")
        if not isinstance(zone, str) or _zone(zone) is None:
            raise LedgerError("bad_zone", "The time zone must be an IANA zone.")
        if not first_name.strip() or re.search(r"[0-9]", first_name) or len(first_name) > 40:
            raise LedgerError("bad_name", "The first name must be letters, at most 40 of them.")
        if not_dialled is not None and not_dialled not in NOT_DIALLED_REASONS:
            raise LedgerError(
                "bad_reason", f"A reason not to dial is one of {', '.join(NOT_DIALLED_REASONS)}."
            )
        if str(consent.get("version") or "") not in self._consent_texts:
            raise LedgerError("unknown_consent", "There is no consent text with that version.")
        if number_hmac is not None and not _HEX64.fullmatch(number_hmac):
            raise LedgerError("bad_number_hmac", "The number's HMAC must be 64 hex characters.")
        # A masked number keeps four digits at most; anything more is a raw number on its way into this file.
        if number_masked is not None and len(re.sub(r"[^0-9]", "", number_masked)) > 4:
            raise LedgerError("unmasked_number", "The number must be masked before it reaches the ledger.")
        if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
            raise LedgerError(
                "bad_nonce", "The nonce must be 22 to 64 letters, digits, hyphens or underscores."
            )
        received = _stamp(received_at) if received_at is not None else self._stamp_now()
        with self._exclusive():
            code = self._new_code()
            record = {
                "code": code,
                "first_name": first_name.strip(),
                "role": role,
                "zone": zone,
                "pin_hmac": pin_hmac(self._pin_key, code, pin),
                "number_hmac": number_hmac,
                "number_masked": number_masked,
                "consent": _consent_record(consent, self._consent_texts),
                "received_at": received,
                "nonce": nonce,
                "not_dialled": not_dialled,
            }
            self._commit(lambda overlay: overlay["applications"].__setitem__(code, record))
            return self._from_record(record)

    def record_answer(
        self, code: str, question_id: str, value: str, heard: str | None, call_id: str | None
    ) -> dict[str, Any] | None:
        """Writes one answer and returns the record it replaced (None when there was none), for the tool's undo.
        Refused once the screen is set, because from the last answer on the call's answers are fixed (spec 3.7)."""
        with self._exclusive():
            app = self._need_applicant(code)
            plan = self._role_plan(app)
            if question_id not in plan.questions:
                raise LedgerError(
                    "unknown_question", "There is no posted question with that id for this role."
                )
            if not self._allowed_value(plan, question_id, value):
                raise LedgerError("bad_value", "That value is not one this question takes.")
            entry = self._overlay["answers"].get(app.code)
            if entry and entry.get("screen"):
                raise LedgerError("screen_complete", "Every question is answered; the answers are fixed.")
            previous = copy.deepcopy(entry["by_question"].get(question_id)) if entry else None
            record = {
                "value": value,
                "heard": self._clean_heard(app.code, heard),
                "at": self._stamp_now(),
                "call_id": call_id,
            }
            key = app.code

            def change(overlay: dict[str, Any]) -> None:
                overlay["answers"].setdefault(key, _blank_answers())["by_question"][question_id] = record

            self._commit(change)
            return previous

    def restore_answer(self, code: str, question_id: str, previous: dict[str, Any] | None) -> None:
        """The undo of record_answer: puts back the record it replaced, or takes the answer out when there was none."""
        with self._exclusive():
            key = self._canonical(code)

            def change(overlay: dict[str, Any]) -> None:
                entry = overlay["answers"].get(key)
                if previous is None:
                    if entry is None:
                        return
                    entry["by_question"].pop(question_id, None)
                    if not entry["by_question"] and not entry.get("screen"):
                        overlay["answers"].pop(key, None)
                    return
                overlay["answers"].setdefault(key, _blank_answers())["by_question"][question_id] = dict(
                    previous
                )

            self._commit(change)

    def set_screen(
        self, code: str, result: str, call_id: str | None, promised_by: datetime | str | None
    ) -> None:
        """Records how the screen ended. "met" is refused while a posted question has no answer or holds declined
        or unclear, which meet no rule (DR-025 section 5): a second lock behind the gate, so the ledger never
        holds a met screen the gate could not have given."""
        if result not in SCREEN_RESULTS:
            raise LedgerError("bad_result", "A screen's result is met or not_met.")
        promised = _stamp(promised_by) if isinstance(promised_by, datetime) else promised_by
        if promised is not None and _instant(promised) is None:
            raise LedgerError("bad_time", "The promised time must be an ISO time with its zone.")
        with self._exclusive():
            app = self._need_applicant(code)
            plan = self._role_plan(app)
            entry = self._overlay["answers"].get(app.code) or _blank_answers()
            values = {q: str(entry["by_question"].get(q, {}).get("value") or "") for q in plan.questions}
            if result == "met" and any(v in ("", "declined", "unclear") for v in values.values()):
                raise LedgerError(
                    "screen_incomplete",
                    "A met screen needs every posted question answered with a posted value.",
                )
            record = {"result": result, "at": self._stamp_now(), "call_id": call_id, "promised_by": promised}
            key = app.code

            def change(overlay: dict[str, Any]) -> None:
                overlay["answers"].setdefault(key, _blank_answers())["screen"] = record

            self._commit(change)

    def clear_screen(self, code: str) -> None:
        with self._exclusive():
            key = self._canonical(code)
            if key not in self._overlay["answers"]:
                return

            def change(overlay: dict[str, Any]) -> None:
                overlay["answers"][key]["screen"] = None

            self._commit(change)

    def set_not_dialled(self, code: str, reason: str) -> None:
        """Records why an intake application is never dialled when the reason is found after intake: the dialler's
        allow-list check at dial time and /voice's (DR-025 section 12, fix 13), so the cockpit shows it and no
        later attempt is scheduled. A fixture keeps its row in data/, which is never rewritten, so nothing changes
        for one."""
        if reason not in NOT_DIALLED_REASONS:
            raise LedgerError(
                "bad_reason", f"A reason not to dial is one of {', '.join(NOT_DIALLED_REASONS)}."
            )
        with self._exclusive():
            key = self._canonical(code)
            record = self._overlay["applications"].get(key)
            if not isinstance(record, dict) or record.get("removed") or record.get("not_dialled") == reason:
                return
            self._commit(lambda overlay: overlay["applications"][key].__setitem__("not_dialled", reason))

    def opt_out(self, code: str, how: str, call_id: str | None = None, number_hmac: str | None = None) -> int:
        """Records that no more calls go to this applicant or this number, and cancels every dial still due to
        either, at once (spec 9.12). Returns the dials cancelled. An opt-out for a code the ledger does not know
        is still written, because refusing one would be the worse failure."""
        if how not in OPT_OUT_HOWS:
            raise LedgerError("bad_how", f"An opt-out is one of: {', '.join(OPT_OUT_HOWS)}.")
        with self._exclusive():
            app = self._applicant(code)
            digits = code_digits(code)
            key = app.code if app else (code_label(digits) if digits else str(code))
            hashed = number_hmac or (app.number_hmac if app else None)
            record = {
                "code": key,
                "number_hmac": hashed,
                "at": self._stamp_now(),
                "call_id": call_id,
                "how": how,
            }
            codes = {key} | (self._codes_for_number(hashed) if hashed else set())
            outcome = "wrong_person" if how == "wrong person" else "opted_out"
            due = [
                d["dial_id"]
                for d in self._overlay["dials"]
                if d.get("code") in codes and d.get("status") == "due"
            ]

            def change(overlay: dict[str, Any]) -> None:
                overlay["opt_outs"].append(record)
                for dial in overlay["dials"]:
                    if dial.get("dial_id") in due:
                        dial["status"], dial["outcome"] = "cancelled", outcome

            self._commit(change)
            return len(due)

    def schedule_dial(self, code: str, attempt: int, due_at: datetime) -> dict[str, Any]:
        """A dial record, status due. One record for one attempt of one application: a status callback that
        Twilio delivers twice schedules the next attempt once. Refused for an application the line may not dial."""
        if attempt < 1:
            raise LedgerError("bad_attempt", "A dial's attempt counts from 1.")
        due = _stamp(due_at)
        with self._exclusive():
            app = self._need_applicant(code)
            reason = self._not_dialable(app)
            if reason is not None:
                raise LedgerError("not_dialable", f"This application is not dialled ({reason}).")
            existing = next(
                (
                    d
                    for d in self._overlay["dials"]
                    if d.get("code") == app.code and d.get("attempt") == attempt
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing)
            record: dict[str, Any] = {
                "dial_id": f"D-{secrets.token_hex(6)}",
                "code": app.code,
                "attempt": attempt,
                "due_at": due,
                "status": "due",
                "claimed_at": None,
                "placed_at": None,
                "call_sid": None,
                "twilio_status": None,
                "answered_at": None,
                "answered_by": None,
                "voicemail_left": False,
                "ended_at": None,
                "outcome": None,
            }
            self._commit(lambda overlay: overlay["dials"].append(record))
            return copy.deepcopy(record)

    def claim_due_dial(
        self, now: datetime, max_per_day: int, ready: Callable[[dict[str, Any], Applicant], bool]
    ) -> dict[str, Any] | None:
        """The next dial to place, marked claimed under the file lock so it is placed once, by one dialler. None
        while a dial is claimed, placed or in progress (one call at a time), once the day's cap is reached, or when
        no due dial is due by now whose applicant consented, has not opted out, has no reason not to be dialled and
        passes `ready` (the dialler's window and allow-list checks)."""
        if now.tzinfo is None:
            raise LedgerError("bad_time", "The claim's time must carry its zone.")
        with self._exclusive():
            dials = self._overlay["dials"]
            if any(d.get("status") in LIVE_DIAL_STATUSES for d in dials):
                return None
            if self._placed_on(central_day(now)) >= max_per_day:
                return None
            due = []
            for d in dials:
                when = _instant(d.get("due_at"))
                if d.get("status") == "due" and when is not None and when <= now:
                    due.append((when, d))
            for _, d in sorted(due, key=lambda pair: pair[0]):
                app = self._applicant(d.get("code"))
                if app is None or self._not_dialable(app) is not None:
                    continue
                if not ready(copy.deepcopy(d), app):
                    continue
                return self._set_dial(d["dial_id"], {"status": "claimed", "claimed_at": _stamp(now)})
            return None

    def bind_call(self, dial_id: str, call_sid: str) -> dict[str, Any] | None:
        """Binds Twilio's CallSid to a live dial when /voice arrives before the dialler wrote it from the REST reply.
        None for a dial that is not live, one bound to another call, or a CallSid already on another dial, so a
        replayed /voice request can never take over a dial."""
        with self._exclusive():
            found = self._find_dial(dial_id) if dial_id.startswith("D-") else None
            if found is None or found.get("status") not in LIVE_DIAL_STATUSES:
                return None
            if found.get("call_sid") == call_sid:
                return copy.deepcopy(found)
            if found.get("call_sid") is not None or self._sid_taken(call_sid, dial_id):
                return None
            return self._set_dial(dial_id, {"call_sid": call_sid})

    def update_dial(self, key: str, **fields: Any) -> dict[str, Any] | None:
        """Changes named fields of one dial, found by its dial id or its CallSid; None when there is no such dial.
        Only the record's own fields are taken, so nothing (a number least of all) can be added to it."""
        unknown = sorted(set(fields) - _DIAL_FIELDS)
        if unknown:
            raise LedgerError("bad_field", f"A dial record has no field {unknown[0]}.")
        if "status" in fields and fields["status"] not in DIAL_STATUSES:
            raise LedgerError("bad_status", "That is not a dial status.")
        if fields.get("outcome") is not None and fields["outcome"] not in DIAL_OUTCOMES:
            raise LedgerError("bad_outcome", "That is not a dial outcome.")
        values = {
            k: (_stamp(v) if k in _DIAL_STAMPS and isinstance(v, datetime) else v) for k, v in fields.items()
        }
        with self._exclusive():
            found = self._find_dial(key)
            if found is None:
                return None
            dial_id = found["dial_id"]
            sid = values.get("call_sid")
            if sid is not None and found.get("call_sid") not in (None, sid):
                raise LedgerError("call_sid_bound", "This dial is bound to another call.")
            if sid is not None and self._sid_taken(sid, dial_id):
                raise LedgerError("call_sid_bound", "That call is bound to another dial.")
            return self._set_dial(dial_id, values)

    def forget(self, code: str) -> None:
        """A deletion request (spec 9.13): the application, its answers, its dials, its booking and its callbacks
        go, and only the consent's version and time and the number's HMAC stay on the removed record, with an
        opt-out, so the number is never called again. The raw number is deleted from the contacts store beside this (`make forget`). A
        fixture's own row stays in data/, which is never rewritten; its records here go the same way."""
        with self._exclusive():
            app = self._applicant(code)
            if app is None:
                raise LedgerError("unknown_applicant", "There is no application with that code.")
            key, stamp = app.code, self._stamp_now()
            opt_out = {
                "code": key,
                "number_hmac": app.number_hmac,
                "at": stamp,
                "call_id": None,
                "how": "deletion",
            }

            def change(overlay: dict[str, Any]) -> None:
                self._remove(overlay, key, "deletion", stamp)
                overlay["opt_outs"].append(opt_out)

            self._commit(change)

    def purge_answers(self, before: datetime) -> int:
        """ANSWERS_RETENTION_DAYS: every application received before `before` goes as forget() removes it, with
        its consent's version and time and its number's HMAC kept, and no opt-out added, because a retention
        period ending is not a request to stop calling. Returns the applications purged."""
        with self._exclusive():
            stamp = self._stamp_now()
            gone: list[str] = []
            for app in self._all_applicants():
                received = _instant(app.received_at)
                if received is not None and received < before and self._has_records(app.code):
                    gone.append(app.code)
            if not gone:
                return 0

            def change(overlay: dict[str, Any]) -> None:
                for key in gone:
                    self._remove(overlay, key, "retention", stamp)

            self._commit(change)
            return len(gone)

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

    def _canonical(self, code: object) -> str:
        digits = code_digits(code)
        return code_label(digits) if digits else str(code)

    def _applicant(self, code: object) -> Applicant | None:
        digits = code_digits(code)
        if digits is None:
            return None
        key = code_label(digits)
        record = self._overlay["applications"].get(key)
        if isinstance(record, dict) and not record.get("removed"):
            return self._from_record(record)
        fixture = self._fixtures.get(key)
        # A copy with its own consent dict, so a caller can copy or change it without touching the fixture.
        return replace(fixture, consent=dict(fixture.consent)) if fixture is not None else None

    def _need_applicant(self, code: object) -> Applicant:
        app = self._applicant(code)
        if app is None:
            raise LedgerError("unknown_applicant", "There is no application with that code.")
        return app

    def _all_applicants(self) -> list[Applicant]:
        found = {code: replace(app, consent=dict(app.consent)) for code, app in self._fixtures.items()}
        for key, record in self._overlay["applications"].items():
            if isinstance(record, dict) and not record.get("removed"):
                found[key] = self._from_record(record)
        return list(found.values())

    def _from_record(self, record: Mapping[str, Any]) -> Applicant:
        return Applicant(
            code=str(record.get("code") or ""),
            first_name=str(record.get("first_name") or ""),
            role=str(record.get("role") or ""),
            zone=str(record.get("zone") or "America/Chicago"),
            received_at=str(record.get("received_at") or ""),
            consent=dict(record.get("consent") or {}),
            number_hmac=record.get("number_hmac") if isinstance(record.get("number_hmac"), str) else None,
        )

    def _role_plan(self, app: Applicant) -> _RolePlan:
        plan = self._roles.get(app.role)
        if plan is None:
            raise LedgerError("unknown_role", "There is no role with that id.")
        return plan

    def _allowed_value(self, plan: _RolePlan, question_id: str, value: object) -> bool:
        if not isinstance(value, str):
            return False
        return (
            value in PLAIN_VALUES
            or value in plan.options.get(question_id, ())
            or bool(_NUMBER_VALUE.fullmatch(value))
        )

    def _clean_heard(self, code: str, heard: str | None) -> str | None:
        if heard is None:
            return None
        text = re.sub(r"\s+", " ", str(heard)).strip()[:MAX_HEARD]
        return _DIGIT_RUN.sub("****", self.mask_pin(code, text)) or None

    def _applicant_state(self, app: Applicant) -> dict[str, Any]:
        plan = self._roles.get(app.role)
        posted = plan.questions if plan else ()
        entry = self._overlay["answers"].get(app.code) or _blank_answers()
        recorded = [q for q in posted if q in entry["by_question"]]
        screen = entry.get("screen")
        return {
            "booked_slot": self._booked_id(app.code),
            "answers_recorded": len(recorded),
            "questions_left": len(posted) - len(recorded),
            "screen": screen.get("result") if isinstance(screen, dict) else None,
            "opted_out": self._is_opted_out(app.code, app.number_hmac),
            "dials_due": sum(
                1 for d in self._overlay["dials"] if d.get("code") == app.code and d.get("status") == "due"
            ),
            "callback_requested": self._callback_for(app.code),
        }

    def _applicant_slot(self, app: Applicant, slot_id: object) -> Slot:
        """The applicant's booking checks, the second lock behind book_slot's own (DR-025 section 1)."""
        entry = self._overlay["answers"].get(app.code)
        screen = entry.get("screen") if entry else None
        if not isinstance(screen, dict):
            raise LedgerError(
                "screen_not_met",
                "The screening questions come first; a booking is offered after the last one.",
            )
        if screen.get("result") != "met":
            raise LedgerError(
                "screen_not_met",
                "A recruiter calls this applicant within one business day; the line books nothing on this call.",
            )
        if self._booked_id(app.code):
            raise LedgerError("already_booked", "This applicant already holds an interview slot.")
        found = self.find_slot(slot_id, recruiter=self._role_plan(app).recruiter)
        if found is None:
            raise LedgerError(
                "unknown_slot", "There is no interview slot with that id for this role's recruiter."
            )
        return found

    def _callback_for(self, code: str) -> bool:
        return any(c.get("code") == code for c in self._overlay["callbacks"])

    def _is_opted_out(self, code: str | None, hashed: str | None) -> bool:
        for record in self._overlay["opt_outs"]:
            if code is not None and record.get("code") == code:
                return True
            if hashed is not None and record.get("number_hmac") == hashed:
                return True
        return False

    def _not_dialable(self, app: Applicant) -> str | None:
        """Why the line may never dial this application, or None."""
        record = self._overlay["applications"].get(app.code)
        reason = record.get("not_dialled") if isinstance(record, dict) else None
        if reason:
            return str(reason)
        if not app.consented:
            return "no_consent"
        if self._is_opted_out(app.code, app.number_hmac):
            return "opted_out"
        return None

    def _codes_for_number(self, hashed: str) -> set[str]:
        return {a.code for a in self._all_applicants() if a.number_hmac == hashed}

    def _find_dial(self, key: str) -> dict[str, Any] | None:
        field_name = "dial_id" if str(key).startswith("D-") else "call_sid"
        return next((d for d in self._overlay["dials"] if d.get(field_name) == key), None)

    def _set_dial(self, dial_id: str, values: Mapping[str, Any]) -> dict[str, Any] | None:
        """Writes fields of one dial through, inside the caller's _exclusive, and returns the record as it now is."""

        def change(overlay: dict[str, Any]) -> None:
            for dial in overlay["dials"]:
                if dial.get("dial_id") == dial_id:
                    dial.update(values)

        self._commit(change)
        found = self._find_dial(dial_id)
        return copy.deepcopy(found) if found else None

    def _sid_taken(self, call_sid: str, dial_id: str) -> bool:
        return any(
            d.get("call_sid") == call_sid and d.get("dial_id") != dial_id for d in self._overlay["dials"]
        )

    def _placed_on(self, day: str) -> int:
        count = 0
        for d in self._overlay["dials"]:
            placed = _instant(d.get("placed_at"))
            if placed is not None and central_day(placed) == day:
                count += 1
        return count

    def _has_records(self, code: str) -> bool:
        overlay = self._overlay
        record = overlay["applications"].get(code)
        return bool(
            (isinstance(record, dict) and not record.get("removed"))
            or code in overlay["answers"]
            or code in overlay["bookings"]
            or any(d.get("code") == code for d in overlay["dials"])
            or any(c.get("code") == code for c in overlay["callbacks"] + overlay["moves"])
        )

    def _remove(self, overlay: dict[str, Any], code: str, why: str, stamp: str) -> None:
        """Takes out everything the line holds for one application but the consent's version and time and the
        number's HMAC, which stay on a removed record as the evidence of consent (DR-025, Security)."""
        record = overlay["applications"].get(code)
        if isinstance(record, dict):
            consent = record.get("consent") or {}
            overlay["applications"][code] = {
                "code": code,
                "consent": {"version": consent.get("version"), "at": consent.get("at")},
                "number_hmac": record.get("number_hmac"),
                "removed": {"at": stamp, "why": why},
            }
        overlay["answers"].pop(code, None)
        overlay["bookings"].pop(code, None)
        overlay["dials"] = [d for d in overlay["dials"] if d.get("code") != code]
        overlay["callbacks"] = [c for c in overlay["callbacks"] if c.get("code") != code]
        overlay["moves"] = [m for m in overlay["moves"] if m.get("code") != code]

    def _new_code(self) -> str:
        """A fresh ACME code: never a candidate's, a fixture's or an earlier application's, removed ones included,
        so a code once given is never given again. Random, so the next code says nothing about the last."""
        taken = {code_digits(c) for c in (*self._candidates, *self._fixtures, *self._overlay["applications"])}
        for _ in range(200):
            digits = f"{secrets.randbelow(10_000):04d}"
            if digits not in taken:
                return code_label(digits)
        free = [f"{n:04d}" for n in range(10_000) if f"{n:04d}" not in taken]
        if not free:
            raise LedgerError("codes_exhausted", "Every application code is in use.")
        return code_label(secrets.choice(free))

    def _booked_id(self, code: str) -> str | None:
        held = self._overlay["bookings"].get(code)
        if held:
            return str(held["slot_id"])
        cand = self._candidates.get(code)
        return cand.booked_slot if cand else None

    def _any_slot(self, slot_id: str) -> Slot | None:
        return self._slots.get(slot_id) or self._interview_slots.get(slot_id)

    def _holders(self) -> dict[str, str]:
        held = {s.id: s.held_by for s in self._slots.values() if s.held_by}
        held |= {s.id: s.held_by for s in self._interview_slots.values() if s.held_by}
        held |= {c.booked_slot: c.code for c in self._candidates.values() if c.booked_slot}
        held |= {str(b["slot_id"]): code for code, b in self._overlay["bookings"].items()}
        return held

    def _is_open(self, slot: Slot, holders: dict[str, str]) -> bool:
        return slot.status == "open" and slot.id not in holders and slot.start > self._now()

    def _stamp_now(self) -> str:
        return _stamp(self._now())

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
        """The file's records, each key checked for its shape. A top-level key this image does not know is kept
        as it was and written back, so an older or a newer image never erases another's records (DR-025 fix 6)."""
        assert self._state_path is not None
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_overlay()
        except (OSError, ValueError) as error:
            return self._set_aside(f"{type(error).__name__}")
        if not isinstance(raw, dict):
            return self._set_aside("not an object")
        overlay = {k: v for k, v in raw.items() if k not in _OVERLAY_KEYS and k != "version"}
        overlay |= _empty_overlay()
        bookings = raw.get("bookings")
        if isinstance(bookings, dict):
            overlay["bookings"] = {
                str(code): dict(b)
                for code, b in bookings.items()
                if isinstance(b, dict) and isinstance(b.get("slot_id"), str)
            }
        for key in ("moves", "callbacks", "opt_outs"):
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
        applications = raw.get("applications")
        if isinstance(applications, dict):
            overlay["applications"] = {
                str(code): dict(a)
                for code, a in applications.items()
                if isinstance(a, dict) and a.get("code") == code
            }
        answers = raw.get("answers")
        if isinstance(answers, dict):
            overlay["answers"] = {
                str(code): {
                    "by_question": {
                        str(q): dict(r)
                        for q, r in (a.get("by_question") or {}).items()
                        if isinstance(r, dict)
                    },
                    "screen": dict(a["screen"]) if isinstance(a.get("screen"), dict) else None,
                }
                for code, a in answers.items()
                if isinstance(a, dict) and isinstance(a.get("by_question") or {}, dict)
            }
        dials = raw.get("dials")
        if isinstance(dials, list):
            overlay["dials"] = [
                dict(d) for d in dials if isinstance(d, dict) and str(d.get("dial_id") or "").startswith("D-")
            ]
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


def forget_everywhere(ledger: Ledger, code: str, delete_contact: Callable[[str], bool]) -> bool:
    """A deletion request in full: the raw number first, from the contacts store, then the ledger's records. The
    number goes first, so a failure part way never leaves a number with no application to find it by."""
    app = ledger.applicant(code)
    if app is None:
        raise LedgerError("unknown_applicant", "There is no application with that code.")
    removed = delete_contact(app.code)
    ledger.forget(app.code)
    return removed


def _contacts_deleter(settings: Settings) -> Callable[[str], bool]:
    """Contacts.delete over CONTACTS_PATH (DR-025 section 9)."""
    # Imported here: the outbound package imports the tools, which import this module.
    from candidate_line.outbound.contacts import Contacts

    path = settings.contacts_path
    if not path:
        raise LedgerError("no_contacts_path", "CONTACTS_PATH is not set, so the number cannot be deleted.")
    store = Contacts(Path(str(path)))
    return lambda code: bool(store.delete(code))


def main(argv: Sequence[str] | None = None) -> int:
    """`make forget CODE=ACME-dddd`: a deletion request against the live state file and the contacts store."""
    parser = argparse.ArgumentParser(description="the line's ledger: a deletion request")
    parser.add_argument("action", choices=["forget"])
    parser.add_argument("code", help="the application code, ACME and four digits")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    ledger = Ledger.default()
    if ledger.state_path is None:
        print("STATE_PATH is :memory:, so there is no state file to delete from")
        return 2
    try:
        removed = forget_everywhere(ledger, args.code, _contacts_deleter(settings))
    except LedgerError as refusal:
        print(f"not forgotten: {refusal}")
        return 1
    contact = "its number deleted from the contacts store" if removed else "no number was held for it"
    print(f"forgot {ledger._canonical(args.code)}: application, answers and dials removed; {contact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
