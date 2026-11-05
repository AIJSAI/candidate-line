"""`make scorecard`: what the line did, in the numbers a recruiting lead asks for, each with its method and its n.

Why pure functions over the store and the files: card 07 allows no number from anywhere but the trace store, the
ledger's state file, the rate table and the synthetic baseline, so each number is one function a test can feed
synthetic calls and a reader can check against its source (AGENTS.md rule 13). Why the booking count comes from the
spans and invite-to-booked from the ledger: a span shows what happened on a call, while the ledger holds only the
bookings that still stand, with their time, which is the clock invite-to-booked is about.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import textwrap
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from candidate_line.brain import Reply
from candidate_line.evals.rates import cost_usd
from candidate_line.settings import Settings
from candidate_line.telephony.app import CLOSED_OUTCOME
from candidate_line.tools.ledger import CANDIDATES_PATH, DATA, Ledger
from candidate_line.traces.store import DEFAULT_PATH, CallRow, SpanRow, TraceStore

BASELINE_PATH = DATA / "baseline_invites.csv"
ROOT = DATA.parent
# A day of traces is tens of calls; the cap only keeps a forgotten store from making the page slow.
MAX_CALLS = 10_000
HAND_OFF_TOOLS = ("request_callback", "move_slot")
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
    counts = {"voice": 0, "text": 0}
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
    """Tier-2 hand-offs by the tool that posted them. A repeat on one call is marked `duplicate` and was never
    posted; a superseded turn's hand-off was posted, and has no undo (DR-021), so it counts."""
    counts = dict.fromkeys(HAND_OFF_TOOLS, 0)
    for c in calls:
        for s in c.spans:
            tool = s.meta.get("tool")
            if s.kind == "escalation" and tool in counts and not s.meta.get("duplicate"):
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
            "closed; the channel as the path wrote it",
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
        f"Ledger: {ledger}. Baseline: {_shown(BASELINE_PATH)}. Rates: candidate_line/evals/rates.py.",
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
) -> str:
    """The whole page. A store file that does not exist is read as empty and never created, so the scorecard
    leaves no file behind."""
    found = store_path == ":memory:" or Path(store_path).exists()
    calls = read_calls(TraceStore(store_path)) if found else []
    bookings = ledger_bookings(state_path)
    invited = invited_at(bookings or {}, candidates_path)
    rows = scorecard(calls, bookings, invited, read_baseline(baseline_path))
    return render(header(calls, store_path, state_path, found), rows)


def main() -> int:
    settings = Settings.from_env()
    state = None if settings.state_path is None else Path(settings.state_path)
    print(build(settings.trace_store_path or str(DEFAULT_PATH), state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
