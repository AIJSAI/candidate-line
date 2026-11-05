"""`make scorecard`: what the line did, in the numbers a recruiting lead asks for, each with its method and its n.

Why pure functions over the store and the files: card 07 allows no number from anywhere but the trace store, the
ledger's state file, the rate table and the synthetic baseline, so each number is one function a test can feed
synthetic calls and a reader can check against its source (AGENTS.md rule 13). Why the booking count comes from the
spans and invite-to-booked from the ledger: a span shows what happened on a call, while the ledger holds only the
bookings that still stand, with their time, which is the clock invite-to-booked is about.

The outbound rows (DR-025 section 17) read the applications, answers and dials from the same state file, never
through a Ledger, and the recruiter's reads and call-backs from the store's hook spans.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import textwrap
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candidate_line.brain import Reply
from candidate_line.evals.rates import cost_usd
from candidate_line.settings import Settings
from candidate_line.telephony.app import CLOSED_OUTCOME
from candidate_line.tools.ledger import (
    APPLICATIONS_PATH,
    CANDIDATES_PATH,
    DATA,
    ROLES_PATH,
    Ledger,
    load_role_plans,
)
from candidate_line.traces.cockpit import applications, read_state
from candidate_line.traces.store import DEFAULT_PATH, CallRow, SpanRow, TraceStore

BASELINE_PATH = DATA / "baseline_invites.csv"
SCREENS_BASELINE_PATH = DATA / "baseline_screens.csv"
ROOT = DATA.parent
# A day of traces is tens of calls; the cap only keeps a forgotten store from making the page slow.
MAX_CALLS = 10_000
HAND_OFF_TOOLS = ("request_callback", "move_slot")
# The screening hand-off's reason starts with its kind (DR-025 section 15), whichever tool posted it.
SCREENING_KIND = "screening hand-off"
# A person answered when detection said so (or could not tell) and the media session wrote one of these outcomes,
# which it writes only once the stream has started (DR-025 sections 8 and 12).
PERSON = frozenset({"human", "unknown"})
REACHED_OUTCOMES = frozenset(
    {"screened", "screen_unfinished", "opted_out", "wrong_person", "pin_missed", "hung_up_before_pin"}
)
LIVE_OR_DUE = frozenset({"due", "claimed", "placed", "in-progress"})
# The first dial of an arrival inside the window is due two minutes after intake (DR-025 section 10); a minute of
# slack on top, so a dial due within three minutes of the arrival is an in-window arrival.
IN_WINDOW_SECONDS = 180
BASELINE_CHANNELS = ("phone", "email")
# DR-001: the latency budget for the median turn, set 2026-11-02.
TURN_BUDGET_MS = 2_000
WIDTH = 108


@dataclass(frozen=True)
class CallTrace:
    call: CallRow
    spans: tuple[SpanRow, ...]


@dataclass(frozen=True)
class Row:
    number: str
    value: str
    n: str
    method: str


@dataclass(frozen=True)
class Baseline:
    hours: dict[str, list[float]]  # channel -> hours_to_book of the invites that booked
    never: dict[str, int]  # channel -> invites that never booked


@dataclass(frozen=True)
class Outbound:
    """The outbound records as read from the state file and the store. `readable` is False when the state file
    could not be read, so a row says so instead of printing zeros."""

    applications: tuple[Mapping[str, Any], ...] = ()  # arrival order; removed ones are gone
    answers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # code -> by_question and screen
    dials: tuple[Mapping[str, Any], ...] = ()
    question_counts: Mapping[str, int] = field(default_factory=dict)  # role id -> posted questions
    read_seconds: tuple[int, ...] = ()  # every read the cockpit logged (hook/read spans)
    call_backs: Mapping[str, tuple[datetime, ...]] = field(
        default_factory=dict
    )  # screening call -> call-backs
    screen_minutes: tuple[float, ...] = ()  # data/baseline_screens.csv
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    readable: bool = True


# Reading the sources. Nothing here writes: the line may be live on the same files.


def read_calls(store: TraceStore, limit: int = MAX_CALLS) -> list[CallTrace]:
    return [CallTrace(c, tuple(store.spans(c.call_id))) for c in store.calls(limit=limit)]


def ledger_bookings(state_path: Path | None) -> dict[str, str] | None:
    """Code to booked-at stamp for every booking in the state file; {} when there is no file, None when it cannot
    be read. Read here and not through `Ledger`, because a ledger that opens a broken file moves it aside, and a
    page that only reads must never move the live line's file. The shape is the one `Ledger._write` gives it."""
    if state_path is None or not state_path.exists():
        return {}
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    bookings = raw.get("bookings") if isinstance(raw, dict) else None
    if not isinstance(bookings, dict):
        return {} if isinstance(raw, dict) else None
    return {
        str(code): str(b["at"])
        for code, b in bookings.items()
        if isinstance(b, dict) and isinstance(b.get("at"), str)
    }


def invited_at(codes: Iterable[str], candidates_path: Path = CANDIDATES_PATH) -> dict[str, str]:
    """Each code's invited_at from data/candidates.yaml, through the ledger's own reader of that file. A ledger
    with no state path touches no file."""
    ledger = Ledger(candidates_path=candidates_path, state_path=None)
    found: dict[str, str] = {}
    for code in codes:
        cand = ledger.candidate(code)
        if cand is not None and cand.invited_at:
            found[code] = cand.invited_at
    return found


def read_baseline(path: Path = BASELINE_PATH) -> Baseline:
    """The CSV's own hours_to_book, by channel. The file starts with a comment line marking it synthetic."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    hours: dict[str, list[float]] = {ch: [] for ch in BASELINE_CHANNELS}
    never: dict[str, int] = dict.fromkeys(BASELINE_CHANNELS, 0)
    for row in csv.DictReader(lines):
        channel = row["channel"]
        hours.setdefault(channel, [])
        never.setdefault(channel, 0)
        if row["hours_to_book"]:
            hours[channel].append(float(row["hours_to_book"]))
        else:
            never[channel] += 1
    return Baseline(hours, never)


# The numbers, each over the calls as read.


def calls_by_channel(calls: Sequence[CallTrace]) -> dict[str, int]:
    """Calls by the channel the path wrote: a call in is `voice`, the line's own dial is `outbound` (DR-025)."""
    counts = {"voice": 0, "outbound": 0, "text": 0}
    for c in calls:
        if c.call.outcome == CLOSED_OUTCOME:
            continue  # answered with the closed line and no stream: not a call taken
        counts[c.call.channel] = counts.get(c.call.channel, 0) + 1
    return counts


def closed_at_cap(calls: Sequence[CallTrace]) -> int:
    return sum(1 for c in calls if c.call.outcome == CLOSED_OUTCOME)


def _ok_tool(span: SpanRow, name: str) -> bool:
    return span.kind == "tool" and span.name == name and not span.meta.get("is_error")


def verified_calls(calls: Sequence[CallTrace]) -> int:
    """Calls with a verify_caller span that matched. The span's one line is built from named fields
    (`turn._one_line`), so "verified " starts it only on a match."""
    return sum(
        1
        for c in calls
        if any(_ok_tool(s, "verify_caller") and (s.text or "").startswith("verified ") for s in c.spans)
    )


def bookings_kept(spans: Sequence[SpanRow]) -> int:
    """Successful book_slot spans on one call, less the ones the line took back. Two take-backs leave their tool
    spans in the trace: a turn the caller talked over, marked by a `hook/superseded` span after its tier span
    (media.py), and a turn that hit the five-call cap, whose last model span asked for tools that never ran
    (`turn._take_back`)."""
    total = 0
    in_turn = 0  # bookings since the last tier span
    closed = 0  # bookings of the turn the last tier span closed, the ones a superseded span takes back
    asked = False  # the latest model span asked for tools and no tool span has run since
    for s in spans:
        if s.kind == "model":
            asked, closed = bool(s.meta.get("tool_calls")), 0
        elif s.kind == "tool":
            asked, closed = False, 0
            if _ok_tool(s, "book_slot"):
                in_turn += 1
        elif s.kind == "tier":
            closed = 0 if asked else in_turn
            total += closed
            in_turn, asked = 0, False
        elif s.kind == "hook" and s.name == "superseded":
            total -= closed
            closed = 0
    # A turn cut off before its tier span (a brain error) keeps what its tools did, so its bookings stand.
    return total + in_turn


def hand_offs(calls: Sequence[CallTrace]) -> dict[str, int]:
    """Tier-2 hand-offs by the tool that posted them, and the screening hand-off by its kind, whichever tool posted
    it (DR-025 fix 10). A repeat on one call is marked `duplicate` and was never posted; a superseded turn's
    hand-off was posted, and has no undo (DR-021), so it counts."""
    counts = dict.fromkeys((*HAND_OFF_TOOLS, "screening"), 0)
    for c in calls:
        for s in c.spans:
            if s.kind != "escalation" or s.meta.get("duplicate") or "tool" not in s.meta:
                continue
            tool = s.meta.get("tool")
            if (s.text or "").startswith(SCREENING_KIND):
                counts["screening"] += 1
            elif tool in HAND_OFF_TOOLS:
                counts[str(tool)] += 1
    return counts


def brain_ms(calls: Sequence[CallTrace]) -> dict[str, list[int]]:
    """Each model span's milliseconds, by model id. A 0 ms span is left out, as the eval runner leaves it out:
    the echo brain reports 0, and a zero would drag a median of real calls down."""
    found: dict[str, list[int]] = {}
    for c in calls:
        for s in c.spans:
            if s.kind == "model" and s.ms:
                found.setdefault(s.name, []).append(s.ms)
    return found


def turn_gaps_ms(calls: Sequence[CallTrace]) -> list[int]:
    """The phone's own turn gap, from the speech spans that carry one (media.py writes it on a turn's first
    audio byte; the greeting and text mode have none)."""
    return [
        int(s.meta["first_audio_gap_ms"])
        for c in calls
        for s in c.spans
        if s.kind == "speech" and isinstance(s.meta.get("first_audio_gap_ms"), int | float)
    ]


def call_cost_usd(spans: Sequence[SpanRow]) -> float | None:
    """The brain's cost of one call, its model spans priced again by rates.py, so the page follows the rate table
    and not the price a span was written with. None when a model has no rate: an unpriced call is never free."""
    total = 0.0
    for s in spans:
        if s.kind != "model":
            continue
        cost = cost_usd(
            Reply(
                text="",
                input_tokens=s.tokens_in or 0,
                output_tokens=s.tokens_out or 0,
                latency_ms=s.ms or 0,
                provider=str(s.meta.get("provider") or ""),
                model=s.name,
                cached_input_tokens=int(s.meta.get("cached_input_tokens") or 0),
                cache_write_input_tokens=int(s.meta.get("cache_write_input_tokens") or 0),
            )
        )
        if cost is None:
            return None
        total += cost
    return total


def call_costs(calls: Sequence[CallTrace]) -> tuple[list[float], int, int]:
    """The priced calls' costs, the calls with an unpriced model, and the calls with no model span at all."""
    priced: list[float] = []
    unpriced = 0
    no_model = 0
    for c in calls:
        if not any(s.kind == "model" for s in c.spans):
            no_model += 1
            continue
        cost = call_cost_usd(c.spans)
        if cost is None:
            unpriced += 1
        else:
            priced.append(cost)
    return priced, unpriced, no_model


def invite_to_booked_hours(
    bookings: Mapping[str, str], invited: Mapping[str, str]
) -> tuple[list[float], int]:
    """Hours from each booked candidate's invite to the booking's stamp, and the bookings left out (no candidate
    with that code, or a time that does not parse), counted so that none vanishes from the page."""
    hours: list[float] = []
    skipped = 0
    for code, at in bookings.items():
        sent = invited.get(code)
        try:
            delta = datetime.fromisoformat(at) - datetime.fromisoformat(sent or "")
        except (ValueError, TypeError):
            skipped += 1
            continue
        hours.append(delta.total_seconds() / 3600)
    return hours, skipped


# The outbound rows (DR-025 section 17).


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def read_screen_minutes(path: Path = SCREENS_BASELINE_PATH) -> tuple[float, ...]:
    """The minutes of each synthetic recruiter phone screen in the CSV, which starts with a comment line."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    return tuple(float(row["minutes"]) for row in csv.DictReader(lines) if row.get("minutes"))


def read_seconds(calls: Sequence[CallTrace]) -> tuple[int, ...]:
    """Every read the cockpit logged: a hook span named read with its seconds (traces/cockpit.py)."""
    return tuple(
        int(s.meta["read_seconds"])
        for c in calls
        for s in c.spans
        if s.kind == "hook" and s.name == "read" and isinstance(s.meta.get("read_seconds"), int)
    )


def call_backs(calls: Sequence[CallTrace]) -> dict[str, tuple[datetime, ...]]:
    """When a recruiter logged a call-back, by screening call: the cockpit's called_back spans only. A reply to the
    hand-off is not counted, because the generic reply box takes "no answer, will try tomorrow" as readily as a
    call made, and spec 9.14 asks for hand-offs called back inside the promised time."""
    found: dict[str, list[datetime]] = {}
    for c in calls:
        for s in c.spans:
            at = _instant(s.meta.get("called_at")) if s.kind == "hook" and s.name == "called_back" else None
            if at is not None:
                found.setdefault(c.call.call_id, []).append(at)
    return {call: tuple(sorted(times)) for call, times in found.items()}


def read_outbound(
    state_path: Path | None,
    calls: Sequence[CallTrace] = (),
    applications_path: Path = APPLICATIONS_PATH,
    roles_path: Path = ROLES_PATH,
    screens_path: Path = SCREENS_BASELINE_PATH,
    now: datetime | None = None,
) -> Outbound:
    """The outbound records, the state file read as the cockpit reads it (never through a Ledger)."""
    common: dict[str, Any] = {
        "read_seconds": read_seconds(calls),
        "call_backs": call_backs(calls),
        "screen_minutes": read_screen_minutes(screens_path),
        "now": now or datetime.now(UTC),
    }
    state = read_state(state_path)
    if state is None:
        return Outbound(readable=False, **common)
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    dials = state.get("dials") if isinstance(state.get("dials"), list) else []
    return Outbound(
        applications=tuple(applications(state, applications_path)),
        answers={str(k): v for k, v in answers.items() if isinstance(v, dict)},
        dials=tuple(d for d in dials if isinstance(d, dict)),
        question_counts={role: len(plan.questions) for role, plan in load_role_plans(roles_path)[0].items()},
        **common,
    )


@dataclass(frozen=True)
class FirstContact:
    in_window: tuple[float, ...]  # minutes, arrivals inside the calling window
    waited: tuple[float, ...]  # minutes, arrivals that waited for the window to open
    never: int  # dialled to the last attempt and no person reached
    still: int  # a dial still due or under way and no person reached yet

    @property
    def every(self) -> tuple[float, ...]:
        return self.in_window + self.waited


def first_contact(outbound: Outbound) -> FirstContact:
    """Minutes from each application to the first dial a person answered, apart for arrivals inside the window
    and those that waited for it. An application never dialled (no consent, off the list) is not counted here."""
    in_window: list[float] = []
    waited: list[float] = []
    never = still = 0
    for app in outbound.applications:
        dials = sorted(
            (d for d in outbound.dials if d.get("code") == app.get("code")),
            key=lambda d: int(d.get("attempt") or 0),
        )
        received = _instant(app.get("received_at"))
        if not dials or received is None:
            continue
        reached = [
            (when, d)
            for d in dials
            if d.get("answered_by") in PERSON
            and (d.get("outcome") in REACHED_OUTCOMES or d.get("status") == "in-progress")
            and (when := _instant(d.get("answered_at"))) is not None
        ]
        if not reached:
            if any(d.get("status") in LIVE_OR_DUE for d in dials):
                still += 1
            else:
                never += 1
            continue
        answered = min(when for when, _ in reached)
        minutes = (answered - received).total_seconds() / 60
        first_due = _instant(dials[0].get("due_at"))
        prompt = first_due is not None and (first_due - received).total_seconds() <= IN_WINDOW_SECONDS
        (in_window if prompt else waited).append(minutes)
    return FirstContact(tuple(in_window), tuple(waited), never, still)


@dataclass(frozen=True)
class Screen:
    code: str
    result: str  # met or not_met
    call_id: str | None
    promised_by: datetime | None
    posted: int  # the role's question count
    values: tuple[str, ...]  # the recorded values


def finished_screens(outbound: Outbound) -> list[Screen]:
    """Every screen the line finished with its last line, for an application still on record."""
    roles = {str(a.get("code")): str(a.get("role")) for a in outbound.applications}
    found: list[Screen] = []
    for code, entry in outbound.answers.items():
        screen = entry.get("screen")
        posted = outbound.question_counts.get(roles.get(code, ""), 0)
        if not isinstance(screen, dict) or code not in roles or not posted:
            continue
        by_question = entry.get("by_question") if isinstance(entry.get("by_question"), dict) else {}
        found.append(
            Screen(
                code=code,
                result=str(screen.get("result")),
                call_id=str(screen["call_id"]) if screen.get("call_id") else None,
                promised_by=_instant(screen.get("promised_by")),
                posted=posted,
                values=tuple(str(r.get("value")) for r in by_question.values() if isinstance(r, dict)),
            )
        )
    return found


def _minutes(value: float) -> str:
    return f"{value:.1f} min"


def _outbound_rows(outbound: Outbound) -> list[Row]:
    unread = "the ledger's state file could not be read; nothing was computed from it"
    if not outbound.readable:
        return [
            Row(name, "none", "0", unread)
            for name in (
                "minutes from application to first contact",
                "answers captured per applicant",
                "recruiter minutes saved (estimate)",
                "the promise (a check row)",
            )
        ]
    contact = first_contact(outbound)
    every = contact.every

    def spread(values: Sequence[float]) -> str:
        return f"median {_minutes(statistics.median(values))} over {len(values)}" if values else "none"

    rows = [
        Row(
            "minutes from application to first contact",
            _minutes(statistics.median(every)) if every else "none",
            _plural(len(every), "application") + " reached",
            (f"worst {_minutes(max(every))}; " if every else "")
            + "from the application's received_at to the answered_at of the first dial a person answered "
            "(detection human or unknown, and the media session started), from the ledger's dials; arrivals inside "
            f"the window: {spread(contact.in_window)}; arrivals that waited for the window: {spread(contact.waited)};"
            f" never reached after the last attempt: {contact.never}; still being dialled: {contact.still}",
        )
    ]
    screens = finished_screens(outbound)
    captured = [sum(1 for v in s.values if v != "unclear") / s.posted for s in screens]
    declined = sum(s.values.count("declined") for s in screens)
    unclear = sum(s.values.count("unclear") for s in screens)
    rows.append(
        Row(
            "answers captured per applicant",
            f"{statistics.median(captured):.0%}" if captured else "none",
            _plural(len(screens), "finished screen"),
            (f"lowest {min(captured):.0%}; " if captured else "")
            + "recorded answers other than unclear over the role's posted question count, per screen the line "
            f"finished with its last line; median; declined (skipped) beside it: {declined}; unclear: {unclear}",
        )
    )
    met = [s for s in screens if s.result == "met"]
    baseline = statistics.median(outbound.screen_minutes) if outbound.screen_minutes else 0.0
    reading = sum(outbound.read_seconds) / 60
    saved = len(met) * baseline - reading
    rows.append(
        Row(
            "recruiter minutes saved (estimate)",
            _minutes(saved) if screens else "none",
            _plural(len(screens), "finished screen"),
            f"an estimate on a synthetic baseline: {len(met)} met screens times {_minutes(baseline)}, the median "
            f"recruiter phone screen over {len(outbound.screen_minutes)} synthetic screens in "
            f"{_shown(SCREENS_BASELINE_PATH)}, less {_minutes(reading)} of reading the cockpit logged "
            f"({_plural(len(outbound.read_seconds), 'read')}, hook/read spans); a not-met hand-off saves nothing, "
            "because a recruiter calls it back",
        )
    )
    offered = sum(1 for s in met if s.promised_by is None)
    promised = [s for s in screens if s.promised_by is not None]
    kept = still_open = 0
    for s in promised:
        assert s.promised_by is not None
        backs = outbound.call_backs.get(s.call_id or "", ())
        if any(at <= s.promised_by for at in backs):
            kept += 1
        elif outbound.now < s.promised_by:
            still_open += 1
    due = len(promised) - still_open
    rows.append(
        Row(
            "the promise (a check row)",
            f"slots offered {offered} of {len(met)}; called back in time {kept} of {due}",
            f"{_plural(len(screens), 'finished screen')}, {_plural(len(promised), 'hand-off')}",
            "met screens whose last line offered interview times, n of the met screens; screening hand-offs (a "
            "posted requirement not met, or met with no open slot) whose called-back span in the cockpit came at "
            "or before the promised time, n of those whose time has come"
            f" ({still_open} still open before their time); short of n is a defect",
        )
    )
    return rows


# The page.


def _ms(value: float) -> str:
    return f"{round(value):,} ms"


def _hours(value: float) -> str:
    return f"{value:.1f} h"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def scorecard(
    calls: Sequence[CallTrace],
    bookings: Mapping[str, str] | None,
    invited: Mapping[str, str],
    baseline: Baseline,
    outbound: Outbound | None = None,
) -> list[Row]:
    """Every row on the page, from the data as read. `bookings` is None when the state file could not be read."""
    n_calls = _plural(len(calls), "call")
    channels = calls_by_channel(calls)
    by_channel = ", ".join(f"{count} {ch}" for ch, count in channels.items())
    rows = [
        Row(
            "calls taken",
            by_channel,
            n_calls,
            "one row in the store's calls table per call, whatever its length, less the calls the daily cap "
            "closed; the channel as the path wrote it, the line's own dials (outbound) apart from calls in",
        ),
        Row(
            "calls closed by the daily cap",
            str(closed_at_cap(calls)),
            n_calls,
            "call rows whose outcome is the daily cap's (telephony/app.py): answered with the closed line, no stream",
        ),
        Row(
            "verified callers",
            str(verified_calls(calls)),
            n_calls,
            "calls with a verify_caller tool span that matched a code and PIN, counted once a call",
        ),
        Row(
            "bookings made",
            str(sum(bookings_kept(c.spans) for c in calls)),
            n_calls,
            "book_slot tool spans that succeeded, less those the line took back: a turn the caller talked over "
            "(a hook/superseded span) or one that hit the five-call cap",
        ),
    ]
    handed = hand_offs(calls)
    for tool, label in (("request_callback", "callback hand-offs"), ("move_slot", "move hand-offs")):
        rows.append(
            Row(
                label,
                str(handed[tool]),
                n_calls,
                f"tier-2 escalation spans posted by {tool}; a repeat on one call is marked duplicate and not "
                "counted",
            )
        )
    rows.append(
        Row(
            "screening hand-offs",
            str(handed["screening"]),
            n_calls,
            "tier-2 escalation spans whose reason is a screening hand-off (a posted requirement not met, or met "
            "with no open slot), whichever tool posted it; a repeat on one call is marked duplicate and not counted",
        )
    )
    rows.extend(_brain_rows(brain_ms(calls)))
    gaps = turn_gaps_ms(calls)
    rows.append(
        Row(
            "median turn gap, phone",
            _ms(statistics.median(gaps)) if gaps else "none",
            _plural(len(gaps), "turn"),
            (f"worst {_ms(max(gaps))}; " if gaps else "")
            + "from the turn's first final transcript to its first audio byte sent to Twilio, on the line's own "
            f"clock (speech spans with first_audio_gap_ms, media.py), not the probe's clock and not a recording; "
            f"DR-001's budget for the median is {_ms(TURN_BUDGET_MS)}",
        )
    )
    priced, unpriced, no_model = call_costs(calls)
    left_out = [
        part
        for part in (
            _plural(unpriced, "call") + " with a model rates.py has no row for" if unpriced else "",
            _plural(no_model, "call") + " with no model span" if no_model else "",
        )
        if part
    ]
    rows.append(
        Row(
            "brain cost per call",
            f"{statistics.mean(priced):.5f} USD" if priced else "none",
            _plural(len(priced), "priced call"),
            f"total {sum(priced):.5f} USD; the mean over calls of their model spans priced by rates.py (tokens in "
            "and out, cache reads at 0.10 and writes at 1.25 times the input rate); the brain only, speech and "
            "the phone are not priced here" + (f"; left out: {', '.join(left_out)}" if left_out else ""),
        )
    )
    rows.extend(_invite_rows(bookings, invited, baseline))
    rows.extend(_outbound_rows(outbound or Outbound()))
    return rows


def _brain_rows(by_model: Mapping[str, list[int]]) -> list[Row]:
    every = [ms for spans in by_model.values() for ms in spans]
    method = (
        "each model span's ms: one model call, request to reply, on the brain's own clock, not the caller's "
        "turn; a 0 ms span (the echo brain) is left out"
    )
    rows = [
        Row(
            "median brain time",
            _ms(statistics.median(every)) if every else "none",
            _plural(len(every), "model span"),
            (f"worst {_ms(max(every))}; " if every else "") + method,
        )
    ]
    if len(by_model) > 1:
        for model, spans in sorted(by_model.items()):
            rows.append(
                Row(
                    f"  {model}",
                    _ms(statistics.median(spans)),
                    _plural(len(spans), "model span"),
                    "the same, for this model id only",
                )
            )
    return rows


def _invite_rows(
    bookings: Mapping[str, str] | None, invited: Mapping[str, str], baseline: Baseline
) -> list[Row]:
    if bookings is None:
        line = Row(
            "invite-to-booked, this line",
            "none",
            "0 bookings",
            "the ledger's state file could not be read; nothing was computed from it",
        )
    else:
        hours, skipped = invite_to_booked_hours(bookings, invited)
        line = Row(
            "invite-to-booked, this line",
            _hours(statistics.median(hours)) if hours else "none",
            _plural(len(hours), "booking"),
            "median hours from the candidate's invited_at (data/candidates.yaml) to the booking's time in the "
            "ledger (STATE_PATH), over every booking the line made that still stands"
            + (f"; {_plural(skipped, 'booking')} left out, no candidate or no time" if skipped else ""),
        )
    rows = [line]
    for channel in BASELINE_CHANNELS:
        hours = baseline.hours.get(channel, [])
        never = baseline.never.get(channel, 0)
        rows.append(
            Row(
                f"invite-to-booked, baseline {channel}",
                _hours(statistics.median(hours)) if hours else "none",
                f"{len(hours)} of {_plural(len(hours) + never, 'invite')}",
                f"median hours_to_book over the {channel} invites that booked in data/baseline_invites.csv; "
                f"{never} never booked and are not in the median",
            )
        )
    return rows


def _shown(path: Path | str) -> str:
    """A path inside the repository as the reader would type it; any other path as given."""
    if str(path) == ":memory:":
        return str(path)
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def header(calls: Sequence[CallTrace], store: str, state: Path | None, store_found: bool) -> list[str]:
    started = sorted(c.call.started_at for c in calls)
    window = f"first call {started[0]}, last {started[-1]}" if started else "no calls"
    where = _shown(store) if store_found else f"{_shown(store)} (no such file, so no calls)"
    ledger = _shown(state) if state is not None else "in memory (STATE_PATH=:memory:), so no bookings"
    return [
        "Candidate Line scorecard: synthetic data, synthetic baseline.",
        f"Trace store: {where}; {window}.",
        (
            f"Ledger: {ledger}. Baselines: {_shown(BASELINE_PATH)}, {_shown(SCREENS_BASELINE_PATH)}. "
            "Rates: candidate_line/evals/rates.py."
        ),
        "No caller is named: the store masks a number before writing it, and this page prints none.",
    ]


def render(head: Sequence[str], rows: Sequence[Row]) -> str:
    """A plain table: number, value and n on one line, the method wrapped under it."""
    first = max([len("number"), *(len(r.number) for r in rows)])
    second = max([len("value"), *(len(r.value) for r in rows)])
    lines = [*head, "", f"{'number':<{first}}  {'value':<{second}}  n", "-" * WIDTH]
    for r in rows:
        lines.append(f"{r.number:<{first}}  {r.value:<{second}}  {r.n}")
        lines.extend(textwrap.wrap(r.method, WIDTH, initial_indent="    ", subsequent_indent="    "))
    return "\n".join(lines)


def build(
    store_path: str,
    state_path: Path | None,
    candidates_path: Path = CANDIDATES_PATH,
    baseline_path: Path = BASELINE_PATH,
    now: datetime | None = None,
) -> str:
    """The whole page. A store file that does not exist is read as empty and never created, so the scorecard
    leaves no file behind."""
    found = store_path == ":memory:" or Path(store_path).exists()
    store = TraceStore(store_path) if found else None
    calls = read_calls(store) if store is not None else []
    outbound = read_outbound(state_path, calls, now=now)
    bookings = ledger_bookings(state_path)
    # An applicant's interview booking has no invitation, so invite-to-booked reads the candidates' bookings only.
    applicants = {str(a.get("code")) for a in outbound.applications}
    if bookings is not None:
        bookings = {code: at for code, at in bookings.items() if code not in applicants}
    invited = invited_at(bookings or {}, candidates_path)
    rows = scorecard(calls, bookings, invited, read_baseline(baseline_path), outbound)
    return render(header(calls, store_path, state_path, found), rows)


def main() -> int:
    settings = Settings.from_env()
    state = None if settings.state_path is None else Path(settings.state_path)
    print(build(settings.trace_store_path or str(DEFAULT_PATH), state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
