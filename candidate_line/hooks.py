"""Four hooks the turn loop calls, and one the call's end calls, empty today, to be filled in the live session.

Why hooks and not subclasses: the guard, the observer, the kill switch and the override log are written in the
room, each as one small object that plugs into a loop nobody rewrites. Each hook may return None (no change) or
a replacement; `before_speak` may return "" to say nothing. A chain runs its hooks in order, each seeing the
previous one's result, so the guard can run after the kill switch and both can be read in one place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from candidate_line.turn import TurnContext


class Hooks(Protocol):
    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        """Sees the caller's words before the brain does. May return a rewritten line (digits, codes, names)."""

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        """Sees Gus's words before the caller does. May replace them; "" means say nothing."""

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        """Called when the caller has said nothing for `seconds`. May return a line for Gus to say."""

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        """Sees every tool call after it ran. Observes only; the override log and the traces start here."""

    def on_call_end(self, ctx: TurnContext, outcome: str | None) -> None:
        """Called once when the call ends, just before the store records its end, with the outcome it records.
        Observes only. The phone runs it on the event loop, so slow work goes to a worker, never inline."""


class NoHooks:
    """The hooks, doing nothing. The default until the live session."""

    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        return None

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        return None

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        return None

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        return None

    def on_call_end(self, ctx: TurnContext, outcome: str | None) -> None:
        return None


class LineHooks:
    """The line's own hooks: empty bodies to be filled in the live session (card 04 `on_tool`, card 05
    `before_speak`, card 06 the tiers' observer on `on_tool`, the kill switch on `on_turn`, the holding line
    on `on_silence` and the summary on `on_call_end`). Every runtime path gets one through `default_hooks()`,
    so a body written here runs on the phone, in text mode and in the eval runner alike; `on_call_end` alone
    runs only on the phone and in text mode, where a call really ends. `NoHooks` above stays truly empty, for
    the tests."""

    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        return None

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        return None

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        return None

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        return None

    def on_call_end(self, ctx: TurnContext, outcome: str | None) -> None:
        # Card 06's tier-3 summary job runs here: the call is over, so the summary nobody waits on starts now,
        # handed to a worker so the hang-up is never held up by it.
        return None


def default_hooks() -> Hooks:
    """What the phone, text mode and the eval runner run: the line's hooks, in one chain."""
    return HookChain([LineHooks()])


class HookChain:
    """Runs hooks in order; a replacement from one hook is what the next hook sees."""

    def __init__(self, hooks: Sequence[Hooks]) -> None:
        self._hooks = tuple(hooks)

    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        current = user_text
        for hook in self._hooks:
            replaced = hook.on_turn(ctx, current)
            if replaced is not None:
                current = replaced
        return None if current == user_text else current

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        current = text
        for hook in self._hooks:
            replaced = hook.before_speak(ctx, current)
            if replaced is not None:
                current = replaced
        return None if current == text else current

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        line: str | None = None
        for hook in self._hooks:
            replaced = hook.on_silence(ctx, seconds)
            if replaced is not None:
                line = replaced
        return line

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        for hook in self._hooks:
            hook.on_tool(ctx, name, args, result)

    def on_call_end(self, ctx: TurnContext, outcome: str | None) -> None:
        for hook in self._hooks:
            hook.on_call_end(ctx, outcome)
