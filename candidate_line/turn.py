"""One turn, the same for voice and text: hooks before the brain, the brain, hooks before the caller hears it.

Why one function: the eval runner, the text REPL and the media stream all call it, so a rule the room adds on
Wednesday holds in all three without three edits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from candidate_line.brain import Brain, Message, Reply
from candidate_line.hooks import Hooks

Channel = Literal["voice", "text"]


@dataclass
class TurnContext:
    call_id: str
    channel: Channel
    system: str
    history: list[Message] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class TurnResult:
    heard: str
    spoken: str
    reply: Reply


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
