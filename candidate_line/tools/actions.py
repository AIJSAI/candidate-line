"""The tools Gus calls, one per May and Must-ask-first line of spec.md, over the ledger and the FAQ.

Why plain functions behind one dispatcher: the turn loop runs whatever the model asked for through run_tool, which
never raises, so a bad argument or an unknown tool becomes one sentence the model recovers from instead of a dead
turn on a live call. The tools that need a person (move_slot, request_callback) change nothing a person must
decide and return the hand-off for the loop to post.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from candidate_line.brain import ToolSpec
from candidate_line.tools.codes import code_digits, pin_digits, spoken_digits
from candidate_line.tools.faq import lookup
from candidate_line.tools.ledger import Candidate, Ledger, LedgerError, parse_day, spoken_label
from candidate_line.traces.store import mask_number

if TYPE_CHECKING:
    from candidate_line.turn import TurnContext

log = logging.getLogger("candidate_line.tools")

# Two misses on one call and the line stops checking (spec 3.1): every further pair would be one more guess at
# someone's PIN, and a caller with the invitation in hand has the right one. The second miss offers a callback
# instead, and spec section 7 writes it up as tier 3.
MAX_VERIFY_ATTEMPTS = 2
# Said by the tool and not only by the brief, because with the brief alone the model asked for a third try (the
# review's baseline run of 2026-11-04, CL-024).
OFFER_CALLBACK = "Offer a callback from the coordinator. No other code or PIN is checked on this call."
# Free text a caller gave (a reason, a time) goes into a hand-off a person reads; a paragraph is the model
# rambling, not the caller.
MAX_TEXT = 200
COORDINATOR_CALLS_BACK = "within one business day"


@dataclass(frozen=True)
class HandOff:
    """What the loop needs to build an Escalation: the call id, the trace link and the masked caller are its own."""

    reason: str
    suggested_action: str
    tier: str = "2"


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # compact JSON the model reads; never a PIN
    is_error: bool = False  # the tool did not do what was asked: a refusal or a bad argument
    # The verified candidate's booked_slot, moves_used and callback_requested after the tool, which the eval's
    # state check reads; None while nobody is verified.
    state: dict[str, Any] | None = None
    cited: tuple[str, ...] = ()  # the FAQ section ids answer_question returned
    hang_up: bool = False
    escalate: HandOff | None = None
    undo: Callable[[], None] | None = field(default=None, repr=False, compare=False)


class BadArgument(ValueError):
    """An argument the tool cannot use; its message is the one sentence the model reads."""


ToolFn = Callable[[Mapping[str, Any], "TurnContext"], ToolOutcome]


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _error(sentence: str, state: dict[str, Any] | None = None) -> ToolOutcome:
    return ToolOutcome(content=_json({"error": sentence}), is_error=True, state=state)


def _ledger(ctx: TurnContext) -> Ledger:
    """The call's ledger. Kept on the context after the first tool, so an in-memory one lasts the whole call."""
    if ctx.ledger is None:
        ctx.ledger = Ledger.default()
    return ctx.ledger


def _verified(ctx: TurnContext, ledger: Ledger) -> Candidate | None:
    code = ctx.data.get("candidate")
    return ledger.candidate(code) if code else None


def _state(ctx: TurnContext, ledger: Ledger | None) -> dict[str, Any] | None:
    cand = _verified(ctx, ledger) if ledger is not None else None
    return ledger.state(cand.code) if ledger is not None and cand else None


def _text(args: Mapping[str, Any], key: str, required: str | None = None) -> str | None:
    """A free-text argument, whitespace collapsed and capped. `required` is the sentence the model reads when it
    left the argument out."""
    value = args.get(key)
    if isinstance(value, Mapping | list | tuple):
        raise BadArgument(f"The {key} must be plain text.")
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()[:MAX_TEXT]
    if not text and required:
        raise BadArgument(required)
    return text or None


_PIN_PHRASE = re.compile(r"(?i)\bpin\b(?:\s*(?:is|was|number|[:,]))*\s*[0-9](?:[ ,.-]?[0-9])*")
# Seven digits or more, standing alone. A slot id (S1106-0930) is part of a word, and an ISO date is kept.
_PHONE = re.compile(r"(?<![A-Za-z0-9])\+?[0-9](?:[\s().-]*[0-9]){6,}(?![A-Za-z0-9])")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}")
# A run of three or more digits, numerals or spelled, standing alone. The code stays readable as ACME-dddd and a
# masked number keeps its last four, because a hyphen before the run keeps it; a time keeps its colon.
_BARE_DIGITS = re.compile(r"(?<![\w*-])[0-9](?:[ ,.]{0,2}[0-9]){2,}(?![\w:*-])")
_SPELLED = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
_SPELLED_DIGITS = re.compile(rf"(?i)\b{_SPELLED}(?:[\s,.-]{{1,2}}{_SPELLED}){{2,}}\b")


def _mask_phone(match: re.Match[str]) -> str:
    found = match.group(0)
    return found if _ISO_DATE.fullmatch(found) else str(mask_number(found))


def _scrub(text: str | None, ctx: TurnContext, ledger: Ledger) -> str | None:
    """Free text a person will read, with any PIN and any phone number taken out: a caller who says "my PIN 9683
    didn't work, call me on another number" must not have either posted to the hand-off channel or saved in the
    state file. A number is masked the way the store masks the caller's (AGENTS.md rule 7)."""
    if not text:
        return text
    cleaned = _PIN_PHRASE.sub("PIN ****", text)
    cand = _verified(ctx, ledger)
    if cand is not None:
        cleaned = ledger.mask_pin(cand.code, cleaned)
    cleaned = _PHONE.sub(_mask_phone, cleaned)
    # A caller nobody verified has no record to mask a PIN by, and a verified one may give a wrong PIN, so any
    # other bare run of three or more digits goes too, written or spoken (spec 5.4: never in a trace).
    cleaned = _BARE_DIGITS.sub(lambda m: re.sub(r"[0-9]", "*", m.group(0)), cleaned)
    return _SPELLED_DIGITS.sub("****", cleaned)


def _need_verified(ctx: TurnContext, ledger: Ledger) -> Candidate:
    cand = _verified(ctx, ledger)
    if cand is None:
        raise BadArgument("The caller is not verified yet. Ask for the application code and PIN first.")
    return cand


def _tool(fn: ToolFn) -> ToolFn:
    """A refusal or a bad argument becomes the outcome the model reads, so each tool returns and never raises for
    anything the caller or the model did."""

    @functools.wraps(fn)
    def run(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
        try:
            return fn(args, ctx)
        except (BadArgument, LedgerError) as refusal:
            return _error(str(refusal), _state(ctx, ctx.ledger))

    return run


def _hear_pin(ctx: TurnContext, pin: str) -> None:
    """Every PIN given on this call, right or wrong, so before_speak can catch one said back in any form. It stays
    in the call's scratch, which no span, log or file ever carries."""
    heard: list[str] = ctx.data.setdefault("pins_heard", [])
    if pin not in heard:
        heard.append(pin)


# The tools.


@_tool
def verify_caller(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    failures = int(ctx.data.get("verify_failures", 0))
    raw_code, raw_pin = args.get("code"), args.get("pin")
    if failures >= MAX_VERIFY_ATTEMPTS:
        # The pair is never checked, but a caller who insists has just said a PIN, and before_speak must still be
        # able to catch it if Gus says it back.
        insisted = pin_digits(raw_pin) if raw_pin not in (None, "") else None
        if insisted is not None:
            _hear_pin(ctx, insisted)
        return _error(f"Two misses already on this call. {OFFER_CALLBACK}")
    if raw_code in (None, ""):
        raise BadArgument("Ask for the application code, ACME and four digits.")
    if raw_pin in (None, ""):
        raise BadArgument("Ask for the four-digit PIN.")
    code = code_digits(raw_code)
    if code is None:
        raise BadArgument("The code was not four digits. Ask the caller to say it again, digit by digit.")
    pin = pin_digits(raw_pin)
    if pin is None:
        raise BadArgument("The PIN was not four digits. Ask the caller to say it again, digit by digit.")
    _hear_pin(ctx, pin)
    verified = ctx.data.get("candidate")
    if verified and code_digits(verified) != code:
        # Spec 3.1: a match makes the caller that candidate for the rest of the call; a second code never switches
        # it. The same code again is allowed, because a superseded turn's carried words verify once more.
        return _error(
            "The caller is already verified on this call. Another candidate calls in with their own code and PIN.",
            _state(ctx, ledger),
        )
    cand = ledger.match(code, pin)
    if cand is None:
        # One thing the caller said is one try: a model that reads the same words two ways in one turn must not
        # use up both of the caller's tries (spec 3.1).
        if not ctx.data.get("missed_this_turn"):
            failures += 1
            ctx.data["verify_failures"] = failures
            ctx.data["missed_this_turn"] = True
        miss: dict[str, Any] = {
            "verified": False,
            "reason": "That code and PIN do not match an invitation.",
            "code_heard": spoken_digits(code),
            "failures": failures,
            "tries_left": max(MAX_VERIFY_ATTEMPTS - failures, 0),
        }
        if failures >= MAX_VERIFY_ATTEMPTS:
            miss["next"] = OFFER_CALLBACK
        return ToolOutcome(content=_json(miss), state=_state(ctx, ledger))
    ctx.data["candidate"] = cand.code
    booked = ledger.booked_slot(cand.code)
    return ToolOutcome(
        content=_json(
            {
                "verified": True,
                "code": cand.code,
                "code_digits": spoken_digits(code),
                "first_name": cand.first_name,
                "name": cand.name,
                "role": cand.role,
                "stage": cand.stage,
                "booked_slot": booked.label if booked else None,
                "booked_slot_id": booked.id if booked else None,
                "can_book": booked is None and cand.stage != "first_round_done",
            }
        ),
        state=ledger.state(cand.code),
    )


@_tool
def list_open_slots(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    cand = _need_verified(ctx, ledger)
    day = _text(args, "day")
    wanted = parse_day(day) if day else None
    found = ledger.open_slots(wanted)
    zone_name = _text(args, "time_zone")
    zone = _caller_zone(zone_name)
    slots: list[dict[str, Any]] = []
    for s in found:
        slot: dict[str, Any] = {"id": s.id, "label": s.label}
        if zone is not None and zone_name:
            # F3.4 promises the slot in the caller's zone; the model says both, Central first.
            local = spoken_label(s.start.astimezone(zone)).removesuffix(" Central")
            slot["local"] = f"{local} {_zone_words(zone_name)}"
        slots.append(slot)
    body: dict[str, Any] = {"slots": slots}
    if zone_name and zone is None:
        body["note_time_zone"] = "That time zone was not understood. Say the slots in Central time only."
    if day and wanted is None:
        # The line has no calendar arithmetic, so the model must not guess which day "tomorrow" is either.
        body["note"] = (
            "That day was not understood, so these are the nearest open slots. You do not know today's date: "
            "read each slot by its label and never call one today or tomorrow."
        )
    elif wanted is not None and not found:
        body["note"] = "No open slots match that day."
    booked = ledger.booked_slot(cand.code)
    if booked is not None:
        body["booked_slot"] = booked.label
        body["note_booked"] = "The caller already holds a slot; a move goes to the coordinator."
    return ToolOutcome(content=_json(body), state=ledger.state(cand.code))


def _caller_zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name.strip().replace(" ", "_"))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _zone_words(name: str) -> str:
    """An IANA name the way a caller hears it: "Europe/London" is "London time"."""
    return f"{name.strip().rsplit('/', 1)[-1].replace('_', ' ')} time"


@_tool
def book_slot(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    cand = _need_verified(ctx, ledger)
    slot_id = _text(args, "slot_id", required="Name the slot by its id, from list_open_slots.")
    try:
        slot = ledger.book(cand.code, slot_id, ctx.call_id)
    except LedgerError as refusal:
        state = ledger.state(cand.code)
        if refusal.kind == "already_booked":
            held = ledger.booked_slot(cand.code)
            return ToolOutcome(
                content=_json(
                    {
                        "booked": False,
                        "error": "The caller already holds a slot. A move goes to the coordinator.",
                        "booked_slot": held.label if held else None,
                    }
                ),
                is_error=True,
                state=state,
            )
        if refusal.kind == "not_open":
            return _error("That slot is not open any more. List the open slots again.", state)
        if refusal.kind == "unknown_slot":
            return _error("There is no slot with that id. List the open slots first.", state)
        return _error(str(refusal), state)
    booking = slot.id

    def undo() -> None:
        ledger.unbook(cand.code, booking)

    # The confirmation is F3.1's own sentence, returned by the tool and cited, so a booking turn that names the
    # section has the cite record to match (spec section 6).
    return ToolOutcome(
        content=_json(
            {
                "booked": True,
                "slot_id": slot.id,
                "slot": slot.label,
                "invited_at": cand.invited_at,
                "confirmation": "A confirmation email follows within a few minutes (F3.1).",
            }
        ),
        state=ledger.state(cand.code),
        cited=("F3.1",),
        undo=undo,
    )


@_tool
def move_slot(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    cand = _need_verified(ctx, ledger)
    current = ledger.booked_slot(cand.code)
    if current is None:
        return _error("The caller holds no slot to move. Offer to book one instead.", ledger.state(cand.code))
    preferred = _text(args, "preferred")
    named = ledger.find_slot(preferred) if preferred else None
    wants = named.label if named else _scrub(preferred, ctx, ledger)
    ledger.request_move(cand.code, current.id, wants, ctx.call_id)
    state = ledger.state(cand.code)
    body: dict[str, Any] = {
        "recorded": True,
        "moved": False,
        "booked_slot": current.label,
        "preferred": wants,
        "coordinator_calls_back": COORDINATOR_CALLS_BACK,
    }
    if cand.moves_used:
        body["note"] = "This candidate has moved once already; a second move is the coordinator's decision."
    return ToolOutcome(
        content=_json(body),
        state=state,
        escalate=HandOff(
            reason=(
                f"move request from {cand.code} ({cand.name}): booked {current.label}, "
                f"prefers {wants or 'no time given'}; moves used {cand.moves_used}"
            ),
            suggested_action="call the candidate back about the move",
        ),
    )


@_tool
def answer_question(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    raw = args.get("section_ids")
    if isinstance(raw, str):
        # A model sometimes sends the list as JSON text; brackets and quotes are never part of an id.
        ids: list[object] = [part for part in re.split(r"[\s,;\[\]\"']+", raw) if part]
    elif isinstance(raw, list | tuple):
        ids = list(raw)
    else:
        raise BadArgument("Name the FAQ section ids from the index, like F2.1.")
    found = lookup(ids)
    body = {"sections": [{"id": s.id, "title": s.title, "heading": s.heading, "text": s.text} for s in found]}
    # No ledger is opened for a question: the FAQ is public, and the state is only carried when one exists.
    return ToolOutcome(content=_json(body), cited=tuple(s.id for s in found), state=_state(ctx, ctx.ledger))


@_tool
def request_callback(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    cand = _verified(ctx, ledger)
    best_time = _scrub(_text(args, "best_time"), ctx, ledger)
    reason = _scrub(_text(args, "reason"), ctx, ledger)
    ledger.request_callback(cand.code if cand else None, best_time, reason, ctx.call_id)
    who = f"{cand.code} ({cand.name})" if cand else "the caller"
    return ToolOutcome(
        content=_json(
            {
                "recorded": True,
                "for": cand.first_name if cand else "the caller",
                "best_time": best_time,
                "coordinator_calls_back": COORDINATOR_CALLS_BACK,
            }
        ),
        state=ledger.state(cand.code) if cand else None,
        escalate=HandOff(
            reason=(
                f"callback request from {who}: {reason or 'no reason given'}; "
                f"best time {best_time or 'not given'}"
            ),
            suggested_action="call the candidate back"
            if cand
            else "call the caller back on the masked number",
        ),
    )


@_tool
def end_call(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    return ToolOutcome(content=_json({"ending": True}), hang_up=True, state=_state(ctx, ctx.ledger))


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    # An empty "required" is left out rather than sent as [], the one shape both providers are known to take.
    return {"type": "object", "properties": properties, **({"required": list(required)} if required else {})}


# The examples in these descriptions are never a real record's code or slot: a model told "like S1105-0930" may
# book that slot without listing the open ones first. answer_question no longer offers a heading for all of it:
# told it could, the model swept all eight headings for a salary question and then refused in its own words while
# citing eight sections (card 02's fourth live run, DR-017); an empty list is the path to the refusal line.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "verify_caller",
        "Check the caller's application code and PIN. Pass both as heard, once the caller has given both.",
        _schema(
            {
                "code": {
                    "type": "string",
                    "description": "The application code as heard: ACME and four digits.",
                },
                "pin": {"type": "string", "description": "The four-digit PIN as heard."},
            },
            ("code", "pin"),
        ),
    ),
    ToolSpec(
        "list_open_slots",
        "The open first-round slots, nearest first, at most six, each with its id and the words to say.",
        _schema(
            {
                "day": {
                    "type": "string",
                    "description": "Optional: a weekday or a date, like Friday 6 November.",
                },
                "time_zone": {
                    "type": "string",
                    "description": "Optional: the caller's time zone as an IANA name, like Europe/London.",
                },
            }
        ),
    ),
    ToolSpec(
        "book_slot",
        "Book the open slot the caller chose, by its id. Only for a verified caller who holds no slot.",
        _schema(
            {"slot_id": {"type": "string", "description": "The slot's id, as list_open_slots gave it."}},
            ("slot_id",),
        ),
    ),
    ToolSpec(
        "move_slot",
        "Hand a request to move the caller's booked slot to the coordinator. It moves nothing.",
        _schema(
            {"preferred": {"type": "string", "description": "Optional: when the caller would rather go."}}
        ),
    ),
    ToolSpec(
        "answer_question",
        "The FAQ sections by id from the index; the only source for a process answer. Name only the sections "
        "whose titles fit, or an empty list when none does: the line then says the refusal itself.",
        _schema(
            {
                "section_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Section ids like F2.1, only those whose titles fit the question.",
                }
            },
            ("section_ids",),
        ),
    ),
    ToolSpec(
        "request_callback",
        "Ask the coordinator to call the caller back, as soon as the caller asks; works before verification too. "
        "Never ask for a reason or a time first.",
        _schema(
            {
                "best_time": {"type": "string", "description": "Optional: when to call."},
                "reason": {
                    "type": "string",
                    "description": "Optional: what the call is about, in a few words.",
                },
            }
        ),
    ),
    ToolSpec(
        "end_call", "End the call once the caller is done or says stop, after saying goodbye.", _schema({})
    ),
)

_TOOLS: dict[str, ToolFn] = {
    "verify_caller": verify_caller,
    "list_open_slots": list_open_slots,
    "book_slot": book_slot,
    "move_slot": move_slot,
    "answer_question": answer_question,
    "request_callback": request_callback,
    "end_call": end_call,
}
TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOL_SPECS)


def run_tool(name: str, args: Mapping[str, Any] | None, ctx: TurnContext) -> ToolOutcome:
    """Runs one tool and never raises: a caller on the line hears a recovery, never a dead turn."""
    fn = _TOOLS.get(str(name))
    if fn is None:
        return _error(f"There is no tool named {str(name)[:40]}.")
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        return _error("The tool's input must be an object.")
    try:
        return fn(args, ctx)
    except Exception as error:  # noqa: BLE001  (any failure becomes a sentence the model can recover from)
        # The type and the line only: an exception's text could carry an argument, and an argument can be a PIN.
        where = traceback.extract_tb(error.__traceback__)[-1] if error.__traceback__ else None
        at = f" at {where.filename.rsplit('/', 1)[-1]}:{where.lineno}" if where else ""
        log.error("tool %s failed: %s%s", name, type(error).__name__, at)
        return _error("That did not work. Offer a callback from the coordinator.")
