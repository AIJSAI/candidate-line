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
from candidate_line.hooks import Hooks
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


def run_turn(
    brain: Brain, hooks: Hooks, ctx: TurnContext, user_text: str, max_tokens: int = 200
) -> TurnResult:
    heard = hooks.on_turn(ctx, user_text)
    heard = user_text if heard is None else heard
    ctx.history.append(Message("user", heard))
    reply = brain.reply(ctx.system, ctx.history, max_tokens=max_tokens)
    spoken = hooks.before_speak(ctx, reply.text)
    spoken = reply.text if spoken is None else spoken
    # The history keeps what was said to the caller, not what the model wrote, so a guard's replacement
    # is what the next turn builds on.
    ctx.history.append(Message("assistant", spoken))
    return TurnResult(heard=heard, spoken=spoken, reply=reply)


def run_silence(hooks: Hooks, ctx: TurnContext, seconds: float) -> str | None:
    line = hooks.on_silence(ctx, seconds)
    if line:
        ctx.history.append(Message("assistant", line))
    return line
