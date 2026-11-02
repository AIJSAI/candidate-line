"""Four hooks the turn loop calls, empty today, filled live on Wednesday.

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


class NoHooks:
    """The four hooks, doing nothing. The default until Wednesday."""

    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        return None

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        return None

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        return None

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        return None


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
