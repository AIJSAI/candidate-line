"""One turn, the same for voice and text: hooks before the brain, the brain and its tools, hooks before the caller
hears it, then the tier.

Why one function: the eval runner, the text REPL and the media stream all call it, so a rule the room adds on
Wednesday holds in all three without three edits. Why the tools run here and not in a hook: a tool call is the
model's own turn on the native channel (DR-003), and the loop must fold every model call into one Reply so the
latency and cost lines count the whole turn (card 04).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from candidate_line import tiers
from candidate_line.brain import Brain, Message, Reply, ToolCall, ToolResult, ToolSpec
from candidate_line.escalation import Escalation, EscalationQueue
from candidate_line.evals.rates import cost_usd
from candidate_line.hooks import Hooks
from candidate_line.persona import RECOVERY_LINE, REFUSAL_LINE, REPLY_MAX_TOKENS, STOP_LINE
from candidate_line.telephony.audio import split_sentences
from candidate_line.text import straighten
from candidate_line.tools import TOOL_SPECS, HandOff, ToolOutcome, run_tool
from candidate_line.tools.codes import code_digits, code_label
from candidate_line.tools.faq import lookup
from candidate_line.tools.ledger import Ledger
from candidate_line.traces.store import TraceStore

log = logging.getLogger("candidate_line.turn")

Channel = Literal["voice", "text"]

# A turn that is still calling tools after this many model calls is lost, and the caller hears the recovery line
# instead of a sixth wait. A booking said in one breath is verify, list, book and a reply, four calls (text mode,
# 2026-11-04, 1 of 3 runs); the fifth is the margin.
MAX_MODEL_CALLS = 5
# Said when end_call came with no words of its own, so the caller never hangs up on silence.
GOODBYE_LINE = "Goodbye."
_TOOL_FAILED = json.dumps({"error": "That did not work. Offer a callback from the coordinator."})
# Arguments that are ids, kept as given in a tool span; every other text argument has its digit runs masked. An
# answer's value is a posted id or a number of three digits at most, never a PIN (DR-025 section 3); one that is
# anything else is masked like free text, since the model may have put a PIN there by mistake.
_ID_ARGS = frozenset({"slot_id", "section_ids", "day", "time_zone", "question_id", "value"})
_PLAIN_VALUE = re.compile(r"[A-Za-z_-]{1,40}|[0-9]{1,3}")
# A refusal in the model's own words (the review walk of 2026-11-04: salary, dress code, other applicants), which
# skips the spec's refusal line and its tier-3 write-up, so the loop says the line itself (spec sections 6 and 7).
_OWN_REFUSAL = re.compile(
    r"(?i)\b(don't|do not|doesn't|does not) have (any |that |this )?([\w-]+ )?(information|details|an answer|data)\b"
    r"|\bno (information|details|data) (on|about)\b|\b(doesn't|does not|don't|do not) cover\b"
    r"|\bnone of the (sections|FAQ)\b|\b(isn't|is not|not) (in|covered (by|in)) the FAQ\b"
    r"|\bnot something (the FAQ|this line) covers\b"
    r"|\bI (can't|cannot|can not|am not able to|'m not able to) (give|share|provide|quote|tell you)( you)?"
    r" (a |the |any |that )?(salary|pay|figure|number|range|information|details|answer)\b"
)
# The tools whose result a refusal may replace: a booking or a verification the caller has not heard must be said.
_REFUSAL_MAY_REPLACE = frozenset({"answer_question"})
_CITE = re.compile(r"\bF\d+\.\d+\b")


@dataclass
class TurnContext:
    call_id: str
    channel: Channel
    system: str
    history: list[Message] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    # The trace store this turn writes into (card 03 writes the spans through it). Each path opens its own and
    # starts and ends the call: the phone and text mode on the room's store, the eval runner on its own file, a
    # unit test on ":memory:" or None. None means no tracing.
    store: TraceStore | None = field(default=None, repr=False, compare=False)
    # The escalation queue the tier rule submits hand-offs to (card 06), built per path beside the store; None in
    # unit tests. The eval runner's queue has the log poster, so an eval never reaches a real channel.
    escalations: EscalationQueue | None = field(default=None, repr=False, compare=False)
    # The bookings, moves and callbacks the tools read and write (candidate_line/tools/ledger.py). None means
    # Ledger.default(), which the first tool of the call then keeps here, so an in-memory ledger lasts the call.
    ledger: Ledger | None = field(default=None, repr=False, compare=False)
    # Per-call scratch for the components the room builds: the verified candidate, the in-memory slots, the
    # tier so far. Nothing here outlives the call.
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnResult:
    heard: str
    spoken: str
    reply: Reply
    # Filled by the components the room builds: card 04's tool loop sets `cited`, `tools_called` and `state`,
    # card 06's tier rule sets `tier`. None means the component has not landed, so an eval check that reads it is
    # pending, not failed (DR-010); the checks never guess.
    cited: tuple[str, ...] = ()
    tools_called: tuple[str, ...] | None = None
    state: Mapping[str, Any] | None = None
    tier: str | None = None
    # Card 06's kill switch sets this on the turn that says the closing line; the phone then ends the call after
    # the line has played, and text mode ends the session.
    hang_up: bool = False
    # The hand-offs posted on the turn, for the eval's hand-off checks (DR-025 section 18).
    hand_offs: tuple[Escalation, ...] = ()


@dataclass
class _Loop:
    """What the tool loop gathered over one turn's model calls."""

    replies: list[Reply] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)  # the tools that did what was asked (no is_error)
    cited: list[str] = field(default_factory=list)
    answered: list[str] = field(
        default_factory=list
    )  # the sections answer_question returned, to be named aloud
    state: dict[str, Any] | None = None
    hang_up: bool = False
    refused: bool = False
    tool_ms: int = 0
    # The last `say` a tool outcome carried, and whether the loop spoke code's words in place of the model's.
    say: str | None = None
    said_by_code: bool = False
    carried: list[HandOff] = field(default_factory=list)  # the hand-offs the turn's outcomes carried
    posted: list[Escalation] = field(default_factory=list)  # the ones the turn posted


def run_turn(
    brain: Brain,
    hooks: Hooks,
    ctx: TurnContext,
    user_text: str,
    max_tokens: int | None = None,
    tools: Sequence[ToolSpec] | None = None,
) -> TurnResult:
    started = time.perf_counter()
    cap = REPLY_MAX_TOKENS if max_tokens is None else max_tokens
    specs = TOOL_SPECS if tools is None else tuple(tools)
    # The per-turn keys. The undo list is what the phone runs if the caller's next words supersede this turn.
    ctx.data["undo"] = []
    ctx.data.pop("guard", None)
    # A hook's request that the turn be written up (a wrong person answered the dial): the reason, said by no one.
    ctx.data.pop("tier_request", None)
    ctx.data.pop("missed_this_turn", None)
    failures_before = int(ctx.data.get("verify_failures", 0))
    tier3_before = len(ctx.data.get("tier3") or ())
    heard = hooks.on_turn(ctx, user_text)
    heard = user_text if heard is None else heard
    if ctx.data.pop("not_a_turn", False):
        # Hello words before the PIN once the PIN ask has been said twice (spec 9.7): not a turn, so no model call,
        # no reply and nothing in the history, as the phone lets them go (telephony/media.py).
        return TurnResult(
            heard=heard,
            spoken="",
            reply=_fold((), brain),
            tools_called=(),
            state=_current_state(ctx),
            tier="1",
        )
    ctx.history.append(Message("user", heard))
    if ctx.channel == "text":
        # On a call media.py writes the heard span, with the transcriber's confidence and lag (card 03).
        _span(ctx, "transcribe", "heard", text=_masked(heard))
    loop = _Loop()
    if ctx.data.get("hang_up") or ctx.data.get("say"):
        # The kill switch, the caller's "stop", an opt-out, or the PIN ask said again for a hello: the fixed line,
        # and no model call to wait for or to reword it.
        text = str(ctx.data.pop("say", None) or STOP_LINE)
    else:
        text = _tool_loop(brain, hooks, ctx, cap, specs, loop)
        if loop.said_by_code:
            # Fixed lines and posted questions are said whole: the cap would cut the met line before its slots and
            # its question (DR-025 fix 3), and none of them is the model's refusal or names a section.
            pass
        elif (
            not loop.refused
            and set(loop.done) <= _REFUSAL_MAY_REPLACE
            and _OWN_REFUSAL.search(straighten(text))
        ):
            text, loop.refused = REFUSAL_LINE, True
        elif not loop.refused:
            text = _spoken_cap(text)
            if text != RECOVERY_LINE:
                text = _name_sections(text, loop.answered)
    reply = _fold(loop.replies, brain)
    spoken = hooks.before_speak(ctx, text)
    spoken = text if spoken is None else spoken
    # The history keeps what was said to the caller, not what the model wrote, so a guard's replacement
    # is what the next turn builds on.
    ctx.history.append(Message("assistant", spoken))
    # A refusal cites nothing, even when the model fetched sections and then found no answer in them and said the
    # refusal line itself (seen on the first live walk): cite or refuse, never both (spec section 6).
    refused = loop.refused or REFUSAL_LINE in straighten(spoken)
    cited = () if refused else tuple(loop.cited)
    if cited or refused:
        meta: dict[str, Any] = {"refused": refused}
        if refused and loop.cited:
            meta["returned"] = list(loop.cited)
        _span(ctx, "cite", " ".join(cited) or "none", meta=meta)
    if ctx.channel == "text":
        # On a call media.py writes the spoken span once the audio is out.
        _span(ctx, "speech", "spoken", text=_masked(spoken), chars=len(spoken))
    labels = list(ctx.data.get("guard") or ())
    guard_hits = tuple(label for label in labels if label != "clean")
    _span(ctx, "hook", "guard", text=" ".join(labels) or "clean", meta={"hits": list(guard_hits)})
    failures_now = int(ctx.data.get("verify_failures", 0))
    added_miss = failures_now if failures_now > failures_before else 0
    tier = tiers.assign(loop.done, guard_hits, refused, added_miss, spoken, hand_offs=tuple(loop.carried))
    requested = ctx.data.get("tier_request")
    if requested and tier.tier == "1":
        tier = tiers.Tier("3", str(requested))
    # The guard's own write-up is added by its hook; the refusal and the second miss are added here.
    ctx.data.setdefault("tier3", []).extend(tiers.write_ups((), refused, added_miss, spoken))
    if requested:
        ctx.data["tier3"].append(str(requested))
    _undo_scratch(ctx, failures_before, tier3_before)
    state = loop.state if loop.state is not None else _current_state(ctx)
    model_ms = sum(r.latency_ms for r in loop.replies)
    _span(
        ctx,
        "tier",
        tier.tier,
        text=tier.reason,
        meta={
            "turn_ms": round((time.perf_counter() - started) * 1000),
            "model_ms": model_ms,
            "tool_ms": loop.tool_ms,
            "model_calls": len(loop.replies),
            "tools": list(loop.tools_called),
        },
    )
    # A turn-path hook (the kill switch in on_turn, card 06) asks for the hang-up the way the silence hook does,
    # through ctx.data, so the phone and text mode read one field on the result (DR-008).
    hang_up = bool(ctx.data.pop("hang_up", False)) or loop.hang_up
    return TurnResult(
        heard=heard,
        spoken=spoken,
        reply=reply,
        cited=cited,
        tools_called=tuple(loop.tools_called),
        state=state,
        tier=tier.tier,
        hang_up=hang_up,
        hand_offs=tuple(loop.posted),
    )


def _tool_loop(
    brain: Brain, hooks: Hooks, ctx: TurnContext, cap: int, specs: Sequence[ToolSpec], loop: _Loop
) -> str:
    """Calls the brain until it answers without a tool, and returns the words to say. A brain error is raised to
    the path (the phone speaks its recovery line); the history is first closed with that line, so the next
    turn's messages still alternate the way both APIs require."""
    start = len(ctx.history)
    candidate_before = ctx.data.get("candidate")
    failures_before = int(ctx.data.get("verify_failures", 0))
    try:
        for _ in range(MAX_MODEL_CALLS):
            reply = brain.reply(ctx.system, ctx.history, max_tokens=cap, tools=specs)
            loop.replies.append(reply)
            _model_span(ctx, reply)
            if not reply.tool_calls:
                if loop.refused:
                    # A refusal that came beside another tool: the model says what the other tool did, then the
                    # line, which the model would reword.
                    words = _spoken_cap(reply.text)
                    if REFUSAL_LINE in straighten(words):
                        return words
                    return f"{words} {REFUSAL_LINE}".strip()
                if reply.text.strip():
                    return reply.text
                # An empty end_turn after a tool result would be silence on the line, and an empty assistant message
                # that Bedrock refuses on every later turn of the call.
                log.warning("empty reply for %s", ctx.call_id)
                return RECOVERY_LINE
            if len(loop.replies) == MAX_MODEL_CALLS:
                # Its calls are never run, and what the earlier calls did is taken back: the caller hears only the
                # recovery line, so no booking may stand that they never heard (spec section 8).
                log.warning("tool loop hit %d model calls for %s", MAX_MODEL_CALLS, ctx.call_id)
                _take_back(ctx, loop, start, candidate_before, failures_before)
                return RECOVERY_LINE
            ctx.history.append(Message("assistant", reply.text, tool_calls=reply.tool_calls))
            results = tuple(_run_call(hooks, ctx, call, loop) for call in reply.tool_calls)
            ctx.history.append(Message("tool", tool_results=results))
            if loop.say is not None:
                # A tool gave the words (a fixed line of spec 9.9 or a posted question): said as given, with no
                # further model call, so no applicant hears a reaction the model worded (DR-025 section 3). A
                # refusal beside it is not said, so it is not written up as said either.
                loop.said_by_code, loop.refused = True, False
                return loop.say
            if loop.refused and all(call.name in _REFUSAL_MAY_REPLACE for call in reply.tool_calls):
                # Asked to say the refusal line, the model rewords it (card 04's dry run), so the loop says it.
                return REFUSAL_LINE
            if loop.hang_up:
                # end_call came with its goodbye; a further model call would only make the caller wait.
                return reply.text.strip() or GOODBYE_LINE
    except BaseException:
        if not ctx.history or ctx.history[-1].role != "assistant" or ctx.history[-1].tool_calls:
            ctx.history.append(Message("assistant", RECOVERY_LINE))
        raise
    return RECOVERY_LINE  # not reached: the last call returns above


def _take_back(
    ctx: TurnContext, loop: _Loop, start: int, candidate_before: object, failures_before: int
) -> None:
    """Undoes a lost turn: its tool effects newest first, its messages, a verification it made and a miss it
    counted, so the call stands as the caller last heard it. The caller heard only "say it again", so a miss kept
    here would spend a try they were asked to make. A reversal that fails is logged and the rest still run."""
    for reverse in reversed(ctx.data.get("undo") or ()):
        try:
            reverse()
        except Exception:
            log.exception("undo failed for %s", ctx.call_id)
    ctx.data["undo"] = []
    del ctx.history[start:]
    if candidate_before is None:
        ctx.data.pop("candidate", None)
    else:
        ctx.data["candidate"] = candidate_before
    ctx.data["verify_failures"] = failures_before
    loop.done.clear()
    loop.cited.clear()
    loop.answered.clear()
    loop.state = None


def _name_sections(text: str, ids: Sequence[str]) -> str:
    """Every section answer_question returned, named aloud by heading and id (spec section 6). The model names
    them itself on most turns; on the review's eval run of 2026-11-04 it named F5.1 and left out F2.1, the
    section it answered from (CL-027). A refusal names nothing: cite or refuse, never both."""
    if REFUSAL_LINE in straighten(text):
        return text
    unnamed = [cid for cid in ids if not re.search(rf"\b{re.escape(cid)}\b", text)]
    by_heading: dict[str, list[str]] = {}
    for section in lookup(unnamed) if unnamed else ():
        by_heading.setdefault(_heading_words(section.heading), []).append(section.id)
    if not by_heading:
        return text
    parts = [f"the {heading} section, {_and(found)}" for heading, found in by_heading.items()]
    return f"{text.strip()} That is from {_and(parts)}."


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _heading_words(heading: str) -> str:
    """A heading as said in a sentence: "The first-round interview" is "first-round interview"."""
    words = heading.strip().removeprefix("The ").strip()
    return words[:1].lower() + words[1:]


def _spoken_cap(text: str) -> str:
    """Two sentences, plus the one that names a section. The brief asks for two and the model wrote three or more
    in 23 of 38 replies on the review walk of 2026-11-04; a caller is waiting (DR-003)."""
    sentences = split_sentences(text)
    if len(sentences) <= 2:
        return text
    kept = sentences[:2] + [s for s in sentences[2:] if _CITE.search(s)][:1]
    return " ".join(kept)


def _run_call(hooks: Hooks, ctx: TurnContext, call: ToolCall, loop: _Loop) -> ToolResult:
    """Runs one tool call and records it. Never raises: a tool or a hook that fails is a result the model reads."""
    started = time.perf_counter()
    try:
        outcome = run_tool(call.name, call.args, ctx)
    except Exception as error:  # noqa: BLE001  (run_tool never raises; this keeps a turn alive if it ever does)
        log.error("tool %s raised out of run_tool: %s", call.name, type(error).__name__)
        outcome = ToolOutcome(content=_TOOL_FAILED, is_error=True)
    ms = round((time.perf_counter() - started) * 1000)
    loop.tool_ms += ms
    loop.tools_called.append(call.name)
    if not outcome.is_error:
        loop.done.append(call.name)
    try:
        hooks.on_tool(ctx, call.name, call.args, outcome.content)
    except Exception:  # an observer never breaks the turn it observes
        log.exception("on_tool failed for %s", ctx.call_id)
    body = _body(outcome.content)
    loop.state = outcome.state
    for cid in outcome.cited:
        if cid not in loop.cited:
            loop.cited.append(cid)
    if outcome.undo is not None:
        ctx.data.setdefault("undo", []).append(outcome.undo)
    if outcome.hang_up:
        loop.hang_up = True
    if outcome.say:
        loop.say = outcome.say
    if call.name == "answer_question" and not outcome.is_error and not outcome.cited:
        loop.refused = True
    if call.name == "answer_question":
        loop.answered.extend(cid for cid in outcome.cited if cid not in loop.answered)
    meta: dict[str, Any] = {
        "args": _traced_args(call.args),
        "keys": sorted(body),
        "is_error": outcome.is_error,
    }
    for key in ("slot", "slot_id", "invited_at"):  # card 07's invite-to-booked number reads these
        if call.name == "book_slot" and key in body:
            meta[key] = body[key]
    _span(ctx, "tool", call.name, ms=ms, text=_one_line(call.name, body, outcome), meta=meta)
    if outcome.escalate is not None:
        loop.carried.append(outcome.escalate)
        posted = _hand_off(ctx, call.name, outcome.escalate)
        if posted is not None:
            loop.posted.append(posted)
    return ToolResult(call.id, outcome.content, outcome.is_error)


def _traced_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments as the tool span keeps them. The store masks a pin key; free text (a callback's reason, a
    move's preferred time) can hold a PIN or a number too, so its digit runs are masked here, and the code is
    kept only as the code the records hold."""
    traced: dict[str, Any] = {}
    for key, value in args.items():
        if key == "code":
            digits = code_digits(value)
            traced[key] = code_label(digits) if digits else _masked(str(value))
        elif key == "value" and not _PLAIN_VALUE.fullmatch(str(value).strip()):
            traced[key] = _masked(str(value))
        elif isinstance(value, str) and key not in _ID_ARGS:
            traced[key] = _masked(value)
        else:
            traced[key] = value
    return traced


def _hand_off(ctx: TurnContext, tool: str, escalate: HandOff) -> Escalation | None:
    """Posts a tier-2 hand-off at once (spec section 7: nobody staffs the cockpit, so no hold) and returns it. The
    same request posted twice on one call, as a superseded turn's carried words would, goes once."""
    posted: list[str] = ctx.data.setdefault("handed_off", [])
    if escalate.reason in posted:
        _span(ctx, "escalation", escalate.tier, text=escalate.reason, meta={"tool": tool, "duplicate": True})
        return None
    hand_off = tiers.escalation(
        ctx, escalate.tier, escalate.reason, escalate.suggested_action, record_code=escalate.record_code
    )
    submitted = tiers.submit(ctx, hand_off)
    posted.append(escalate.reason)
    _span(
        ctx,
        "escalation",
        escalate.tier,
        text=escalate.reason,
        meta={"tool": tool, "suggested_action": escalate.suggested_action, "submitted": submitted},
    )
    return hand_off


def _undo_scratch(ctx: TurnContext, failures_before: int, tier3_before: int) -> None:
    """A superseded turn is never heard, so its miss and its write-ups are taken back with its booking: one
    utterance cut in two must not reach the second failed verification on its own (media.py runs the list)."""
    undo: list[Any] = ctx.data.setdefault("undo", [])
    if int(ctx.data.get("verify_failures", 0)) != failures_before:
        undo.append(lambda: ctx.data.__setitem__("verify_failures", failures_before))
    if len(ctx.data.get("tier3") or ()) != tier3_before:
        undo.append(lambda: ctx.data.__setitem__("tier3", list(ctx.data.get("tier3") or ())[:tier3_before]))


def _current_state(ctx: TurnContext) -> dict[str, Any] | None:
    """The verified candidate's state when no tool reported one this turn, so a check on a later turn reads the
    call's bookings and not a pending verdict. On an outbound call before the PIN it is the dialled applicant's,
    so a wrong person's opt-out is checkable; it is never spoken (DR-025 section 18)."""
    seed = ctx.data.get("outbound")
    dialled = seed.get("code") if isinstance(seed, Mapping) else None
    code = ctx.data.get("candidate") or dialled
    if not code or ctx.ledger is None:
        return None
    try:
        return ctx.ledger.state(code)
    except Exception:  # a state read never breaks a turn
        log.exception("state read failed for %s", ctx.call_id)
        return None


def _fold(replies: Sequence[Reply], brain: Brain) -> Reply:
    """One Reply for the turn: the latency, tokens and cache counts summed, the last call's words and model."""
    if not replies:
        return Reply("", 0, 0, 0, str(getattr(brain, "name", "none")), str(getattr(brain, "model", "none")))
    last = replies[-1]
    return Reply(
        text=last.text,
        input_tokens=sum(r.input_tokens for r in replies),
        output_tokens=sum(r.output_tokens for r in replies),
        latency_ms=sum(r.latency_ms for r in replies),
        provider=last.provider,
        model=last.model,
        stop_reason=last.stop_reason,
        cached_input_tokens=sum(r.cached_input_tokens for r in replies),
        cache_write_input_tokens=sum(r.cache_write_input_tokens for r in replies),
    )


def _model_span(ctx: TurnContext, reply: Reply) -> None:
    meta: dict[str, Any] = {
        "provider": reply.provider,
        "stop_reason": reply.stop_reason,
        "cached_input_tokens": reply.cached_input_tokens,
        "cache_write_input_tokens": reply.cache_write_input_tokens,
        "cost_usd": cost_usd(reply),
    }
    if reply.tool_calls:
        meta["tool_calls"] = [call.name for call in reply.tool_calls]
    _span(
        ctx,
        "model",
        reply.model,
        ms=reply.latency_ms,
        tokens_in=reply.input_tokens,
        tokens_out=reply.output_tokens,
        text=_masked(reply.text),
        meta=meta,
    )


def _body(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _one_line(name: str, body: Mapping[str, Any], outcome: ToolOutcome) -> str:
    """The tool's result in one line for the cockpit. Built from named fields, so no PIN can reach it."""
    if outcome.is_error:
        return f"refused: {body.get('error', 'no reason given')}"
    if name == "verify_caller":
        if body.get("verified"):
            return f"verified {body.get('code')}"
        return f"no match, {body.get('failures')} failed on this call"
    if name == "list_open_slots":
        ids = [str(s.get("id")) for s in body.get("slots") or () if isinstance(s, Mapping)]
        return f"{len(ids)} open: {', '.join(ids)}" if ids else "no open slots"
    if name == "book_slot":
        return f"booked {body.get('slot_id')}, {body.get('slot')}"
    if name == "move_slot":
        return f"move request recorded for {body.get('booked_slot')}, prefers {body.get('preferred') or '-'}"
    if name == "answer_question":
        return f"sections {', '.join(outcome.cited)}" if outcome.cited else "no section covers it"
    if name == "request_callback":
        return f"callback recorded, best time {body.get('best_time') or 'not given'}"
    if name == "end_call":
        return "ending the call"
    if name == "confirm_applicant":
        if body.get("confirmed"):
            return "confirmed the applicant"
        return f"no match, {body.get('failures')} failed on this call"
    if name == "record_answer":
        if body.get("asked_again"):
            return f"asked {body.get('question_id')} again"
        return f"recorded {body.get('question_id')}: {body.get('value')}"
    if name == "stop_calls":
        return "stopped every further call"
    return "done"


def _masked(text: str) -> str:
    """Span text with every run of three or more digits masked, as media.py masks the phone's spans (spec
    section 5, Never 4). Imported here because media.py imports this module."""
    from candidate_line.telephony.media import mask_spoken_digits

    return mask_spoken_digits(text)


def _span(ctx: TurnContext, kind: str, name: str, **fields: Any) -> None:
    """One span when the call has a store. A failed write is logged and the turn goes on: a trace is never worth
    a dropped turn."""
    if ctx.store is None:
        return
    try:
        ctx.store.span(ctx.call_id, kind, name, **fields)
    except Exception:
        log.exception("%s span failed for %s", kind, ctx.call_id)


@dataclass(frozen=True)
class SilenceReply:
    """What a stretch of silence produced: the line to say, if any, and whether the call should then end."""

    said: str | None
    hang_up: bool


def run_silence(hooks: Hooks, ctx: TurnContext, seconds: float) -> SilenceReply:
    line = hooks.on_silence(ctx, seconds)
    if line:
        ctx.history.append(Message("assistant", line))
    # A hook asks for the hang-up through the call's scratch (card 06's holding line at the hold limit), so
    # on_silence keeps returning only the line to say. Popped, so one request ends the call once and a later
    # silence does not inherit it.
    hang_up = bool(ctx.data.pop("hang_up", False))
    return SilenceReply(said=line or None, hang_up=hang_up)
