"""The tier rule (card 06, spec.md section 7): handled alone, a person now, or written up after the call.

Why a pure function: the eval's tier check, the trace's tier span and the hand-offs all read one answer, and a
function of the turn's facts alone is tested without a call, a model or a queue. The two helpers below it build
and post a hand-off; they are the one place an Escalation is made, so the turn loop's tier-2 post and the
call-end tier-3 post carry the same trace link and the same masked caller.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from candidate_line.escalation import SCREENING_HAND_OFF, Escalation, record_link, trace_link
from candidate_line.persona import (
    HOLD_LIMIT_LINE,
    KILL_LINE,
    OUTBOUND_STOP_LINE,
    PIN_ASK,
    REFUSAL_LINE,
    STOP_LINE,
)
from candidate_line.settings import DEFAULT_COCKPIT_BASE_URL, Settings
from candidate_line.text import straighten

if TYPE_CHECKING:
    from candidate_line.tools import HandOff
    from candidate_line.turn import TurnContext

log = logging.getLogger("candidate_line.tiers")

TierName = Literal["1", "2", "3"]

# The tools whose request a person must act on. Each posts its hand-off the moment it runs (spec.md section 4).
HAND_OFF_TOOLS = {
    "move_slot": "a move request went to the coordinator",
    "request_callback": "a callback request went to the coordinator",
}
# A posted hand-off in the words the tier span reads, by the kind its reason starts with. One tool,
# record_answer, ends one screen with a booking offer and another with a hand-off, so the tier reads the hand-off
# the turn posted and not the tool's name (spec section 7, DR-025 fix 10).
_HAND_OFF_KINDS = {
    "move request": HAND_OFF_TOOLS["move_slot"],
    "callback request": HAND_OFF_TOOLS["request_callback"],
    SCREENING_HAND_OFF: "a screening hand-off went to the role's recruiter",
}
# Spec section 7 writes up the second failed verification, not the first, which is a mishearing more often than not.
SECOND_MISS = 2
_DONE_ALONE = {
    "verify_caller": "checked the code and PIN",
    "list_open_slots": "read the open slots",
    "book_slot": "booked a slot",
    "answer_question": "answered from the FAQ",
    "end_call": "said goodbye",
    "confirm_applicant": "confirmed the applicant by PIN",
    "record_answer": "recorded an answer",
    "stop_calls": "stopped every further call",
}


@dataclass(frozen=True)
class Tier:
    tier: TierName
    reason: str  # one line a recruiter reads on the cockpit and in a hand-off


def write_ups(
    guard_hits: Sequence[str] = (), refused: bool = False, verify_failures: int = 0, spoken: str = ""
) -> tuple[str, ...]:
    """The turn's reasons to write the call up afterwards (tier 3), in reading order. The guard's rule ids name
    what it caught; the caught sentence is never quoted, because a pin- rule's sentence holds the PIN."""
    reasons: list[str] = []
    if guard_hits:
        reasons.append(f"the guard replaced a sentence ({', '.join(dict.fromkeys(guard_hits))})")
    if refused or REFUSAL_LINE in straighten(spoken):
        reasons.append("the refusal line was said: the FAQ has no answer to the question")
    if verify_failures >= SECOND_MISS:
        reasons.append(f"verification failed {verify_failures} times on this call")
    return tuple(reasons)


def assign(
    tools_called: Sequence[str],
    guard_hits: Sequence[str] = (),
    refused: bool = False,
    verify_failures: int = 0,
    spoken: str = "",
    hand_offs: Sequence[HandOff] = (),
) -> Tier:
    """The turn's tier. `tools_called` are the tools that did what was asked this turn (a refused move posts no
    hand-off); `hand_offs` are the hand-offs the turn's outcomes carried, and any one makes the turn tier 2
    whatever the tool; the tool-name rule stays for a caller that passes none. `verify_failures` is the call's
    count when this turn added a miss, else 0, so a booking after two misses is not written up again. A hand-off
    outranks a write-up, because it is posted at once either way; the write-up still reaches the call's end
    through write_ups()."""
    if hand_offs:
        handed = list(dict.fromkeys(_hand_off_words(h.reason) for h in hand_offs))
    else:
        handed = [HAND_OFF_TOOLS[name] for name in dict.fromkeys(tools_called) if name in HAND_OFF_TOOLS]
    notes = write_ups(guard_hits, refused, verify_failures, spoken)
    if handed:
        also = f"; to write up after the call: {'; '.join(notes)}" if notes else ""
        return Tier("2", "; ".join(handed) + also)
    if notes:
        return Tier("3", "; ".join(notes))
    return Tier("1", _alone(tools_called, spoken))


def _hand_off_words(reason: str) -> str:
    kind = reason.split(" from ", 1)[0].strip()
    return _HAND_OFF_KINDS.get(
        kind, f"a hand-off went to a person ({kind})" if kind else "a hand-off went to a person"
    )


def _alone(tools_called: Sequence[str], spoken: str) -> str:
    said = straighten(spoken).strip()
    if said == KILL_LINE:
        return "handled alone: the kill switch closed the call"
    if said == STOP_LINE:
        return "handled alone: the caller said stop"
    if said == OUTBOUND_STOP_LINE:
        return "handled alone: the applicant asked for no more calls, and every dial still due was cancelled"
    if said == PIN_ASK:
        return "handled alone: the PIN ask, said again by code"
    if said == HOLD_LIMIT_LINE:
        return "handled alone: the caller went quiet past the hold limit"
    done = [_DONE_ALONE[name] for name in dict.fromkeys(tools_called) if name in _DONE_ALONE]
    return f"handled alone: {', '.join(done)}" if done else "handled alone: a spoken answer, no tool"


def escalation(
    ctx: TurnContext, tier: str, reason: str, suggested_action: str, record_code: str | None = None
) -> Escalation:
    """A hand-off for this call: the cockpit link and the caller's number as the store masked it ("-" in text
    mode, where there is none), and for a screening hand-off the applicant's record link. Never a raw number
    (AGENTS.md rule 7)."""
    caller = "-"
    if ctx.store is not None:
        try:
            row = ctx.store.call(ctx.call_id)
        except Exception:  # a store read never stops a hand-off
            log.exception("caller lookup failed for %s", ctx.call_id)
            row = None
        if row is not None and row.caller_masked:
            caller = row.caller_masked
    base = _cockpit_base_url()
    return Escalation(
        call_id=ctx.call_id,
        tier=tier,
        reason=reason,
        suggested_action=suggested_action,
        trace_url=trace_link(base, ctx.call_id),
        caller=caller,
        record_url=record_link(base, record_code) if record_code else None,
    )


def submit(ctx: TurnContext, hand_off: Escalation) -> bool:
    """Posts through the call's queue, which never blocks the turn. False when there is no queue (a unit test)
    or the queue was full."""
    if ctx.escalations is None:
        return False
    return ctx.escalations.submit(hand_off)


def _cockpit_base_url() -> str:
    try:
        return Settings.from_env().cockpit_base_url
    except ValueError:  # a bad unrelated setting must not lose a hand-off's link
        return DEFAULT_COCKPIT_BASE_URL
