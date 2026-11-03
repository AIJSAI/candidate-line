"""One turn, the same for voice and text: hooks before the brain, the brain, hooks before the caller hears it.

Why one function: the eval runner, the text REPL and the media stream all call it, so a rule the room adds on
Wednesday holds in all three without three edits.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from candidate_line.brain import Brain, Message, Reply
from candidate_line.escalation import EscalationQueue
from candidate_line.hooks import Hooks
from candidate_line.persona import REPLY_MAX_TOKENS
from candidate_line.traces.store import TraceStore

Channel = Literal["voice", "text"]


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


def run_turn(
    brain: Brain, hooks: Hooks, ctx: TurnContext, user_text: str, max_tokens: int | None = None
) -> TurnResult:
    cap = REPLY_MAX_TOKENS if max_tokens is None else max_tokens
    heard = hooks.on_turn(ctx, user_text)
    heard = user_text if heard is None else heard
    ctx.history.append(Message("user", heard))
    # Card 04 writes the tool loop here: declare the tools, pass them to the brain, and while the reply carries
    # tool calls, run them, append the assistant message with its calls and a "tool" message with the results,
    # and call the brain again (DR-003). The brain speaks that channel natively on both providers.
    reply = brain.reply(ctx.system, ctx.history, max_tokens=cap)
    spoken = hooks.before_speak(ctx, reply.text)
    spoken = reply.text if spoken is None else spoken
    # The history keeps what was said to the caller, not what the model wrote, so a guard's replacement
    # is what the next turn builds on.
    ctx.history.append(Message("assistant", spoken))
    # A turn-path hook (the kill switch in on_turn, card 06) asks for the hang-up the way the silence hook does,
    # through ctx.data, so the phone and text mode read one field on the result (DR-008).
    return TurnResult(heard=heard, spoken=spoken, reply=reply, hang_up=bool(ctx.data.pop("hang_up", False)))


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
