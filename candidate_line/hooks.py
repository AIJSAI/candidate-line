"""Four hooks the turn loop calls, and one the call's end calls: the normaliser and the switches, the guard, the
holding lines and the tier-3 write-up.

Why hooks and not subclasses: the guard, the observer, the kill switch and the override log are written in the
room, each as one small object that plugs into a loop nobody rewrites. Each hook may return None (no change) or
a replacement; `before_speak` may return "" to say nothing. A chain runs its hooks in order, each seeing the
previous one's result, so the guard can run after the kill switch and both can be read in one place.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from candidate_line import tiers
from candidate_line.guard import Guard
from candidate_line.persona import (
    FALLBACK_LINE,
    HOLD_LIMIT_LINE,
    HOLDING_LINE,
    KILL_LINE,
    OUTBOUND_STOP_LINE,
    PIN_ASK,
    STOP_LINE,
)
from candidate_line.text import straighten
from candidate_line.tools import screening
from candidate_line.tools.actions import _ledger
from candidate_line.tools.codes import normalise_transcript

if TYPE_CHECKING:
    from candidate_line.turn import TurnContext

log = logging.getLogger("candidate_line.hooks")

ROOT = Path(__file__).resolve().parent.parent
# The kill switch is a file, so anyone at the Mac can close the line with `touch var/kill` and reopen it with `rm`,
# with no restart; it is read on every turn and every quiet stretch, and never cached (card 06).
KILL_SWITCH = ROOT / "var" / "kill"
# Built once from the committed lexicon. A broken lexicon raises here, at start, never on a live call (card 05).
GUARD = Guard()
# Spec section 7: the holding line after the first quiet stretch, the closing line once the quiet after it adds
# up to thirty seconds. The caller's next words start the count again.
HOLD_LIMIT_S = 30.0
# A caller's "stop" ends the call with no model call (spec section 7, F8.3). "Okay stop" and "stop the call" count;
# "stop the booking" does not, and goes to the model.
_STOP_WORDS = frozenset(
    {
        "stop",
        "please",
        "okay",
        "ok",
        "now",
        "just",
        "right",
        "yes",
        "thanks",
        "thank",
        "you",
        "bye",
        "goodbye",
        "the",
        "call",
        "it",
        "that's",
        "all",
    }
)
# The outbound stop phrases (DR-025 section 14, fix 4), matched as whole phrases so "don't stop" is never one;
# _STOP_WORDS above is not widened for them. The first four ask for no more calls; the last three say the dial
# reached the wrong person, which only means that before the PIN has proved who answered.
_OPT_OUT = re.compile(
    r"\b(?:don't call me|do not call me|stop calling|take me off|wrong number|not me|you have the wrong person)\b"
)
_WRONG_PERSON = re.compile(r"\b(?:wrong number|not me|you have the wrong person)\b")
# Before the PIN matches, a transcript made only of these is a person picking up, not a turn for the model (spec
# 9.7, DR-025 section 14): it gets the PIN ask by code, at most twice a call, and a third goes to the model.
_HELLO_WORDS = ("hello", "hi", "hey", "yes", "yeah", "speaking", "this is she", "this is he")
MAX_HELLO_ASKS = 2
_SPELLED_DIGIT = re.compile(r"\b(zero|oh|one|two|three|four|five|six|seven|eight|nine)\b", re.IGNORECASE)
_WORD_TO_DIGIT = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def _says_a_heard_pin(sentence: str, pins: Sequence[str]) -> bool:
    """A PIN given on this call, said back as numerals or words, spaced or not. The lexicon's pin- rules need the
    word PIN beside the digits, and "you did say nine six eight three" has none (the review walk, 2026-11-04)."""
    numerals = _SPELLED_DIGIT.sub(lambda m: _WORD_TO_DIGIT[m.group(1).lower()], sentence)
    return any(re.search(r"(?<!\d)" + r"[\s,.-]*".join(pin) + r"(?!\d)", numerals) for pin in pins)


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
    """The line's own hooks. Every runtime path gets one through `default_hooks()`, so a body here runs on the
    phone, in text mode and in the eval runner alike; `on_call_end` alone runs only on the phone and in text mode,
    where a call really ends. Each body is wrapped: a hook that fails is logged and the turn goes on, because a
    caller on the line must never hear nothing. `NoHooks` above stays truly empty, for the tests."""

    def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
        try:
            if KILL_SWITCH.exists():
                ctx.data["hang_up"] = True
                ctx.data["say"] = KILL_LINE
                _span(ctx, "kill", "switch", text="the kill switch file is set; the line closed this call")
                return None
            if self._opt_out(ctx, user_text):
                return None
            if _is_stop(user_text):
                ctx.data["hang_up"] = True
                ctx.data["say"] = STOP_LINE
                return None
            ctx.data.pop("silences", None)  # the caller spoke, so the hold count starts again
            if self._hello(ctx, user_text):
                return None
            normalised = normalise_transcript(user_text)
            return None if normalised == user_text else normalised
        except Exception:  # the brain still hears the caller's own words
            log.exception("on_turn failed for %s", ctx.call_id)
            return None

    def _opt_out(self, ctx: TurnContext, text: str) -> bool:
        """On an outbound call or for an applicant on the line, "stop" or a stop phrase ends the calls at once with
        the outbound stop line and no model call (spec 9.12). From anyone else, "stop" keeps today's stop line
        and a phrase goes to the model. True when it closed the call."""
        said = straighten(text).lower()
        stop, phrase = _is_stop(text), _is_opt_out(said)
        if (not stop and not phrase) or not (ctx.data.get("outbound") or ctx.data.get("candidate")):
            return False
        ledger = _ledger(ctx)
        if screening.opt_out_code(ctx, ledger) is None:
            return False
        proved = screening.applicant(ctx, ledger) is not None
        wrong = not stop and not proved and bool(_WRONG_PERSON.search(said))
        if not stop and proved and not _OPT_OUT.search(_WRONG_PERSON.sub(" ", said)):
            # After the PIN, "no, not me" is an answer, never a wrong person: it goes to the model.
            return False
        how = screening.WRONG_PERSON if wrong else screening.SAID_STOP
        try:
            screening.record_opt_out(ctx, how)
        except Exception:  # the stop is still honoured on the call; a person must make it stick
            log.exception("opt-out not saved for %s", ctx.call_id)
            ctx.data["tier_request"] = (
                "an opt-out could not be saved: cancel this application's dials by hand"
            )
            ctx.data["hang_up"] = True
            ctx.data["say"] = STOP_LINE
            return True
        if wrong:
            ctx.data["tier_request"] = (
                "a wrong person answered the dial, so the line will not call this number again"
            )
        ctx.data["hang_up"] = True
        ctx.data["say"] = OUTBOUND_STOP_LINE
        _span(ctx, "hook", "opt-out", text=f"the calls were stopped: {how}")
        return True

    def _hello(self, ctx: TurnContext, text: str) -> bool:
        seed = screening.dialled(ctx)
        if seed is None or ctx.data.get("candidate"):
            return False
        asked = int(ctx.data.get("hello_asks", 0))
        if asked >= MAX_HELLO_ASKS or not is_hello(text, str(seed.get("first_name") or "")):
            return False
        ctx.data["hello_asks"] = asked + 1
        ctx.data["say"] = PIN_ASK
        return True

    def before_speak(self, ctx: TurnContext, text: str) -> str | None:
        try:
            pins = tuple(ctx.data.get("pins_heard") or ())
            extra = (lambda s: "pin-heard" if _says_a_heard_pin(s, pins) else None) if pins else None
            verdicts = GUARD.check(text, extra)
            ctx.data["guard"] = [v.label for v in verdicts]
            spoken, hits = GUARD.apply(text, FALLBACK_LINE, extra)
        except Exception:  # fails closed: unchecked words are never spoken
            log.exception("before_speak failed for %s", ctx.call_id)
            ctx.data["guard"] = ["error"]
            ctx.data.setdefault("tier3", []).append("the guard failed, so the fallback line was said")
            return FALLBACK_LINE
        if not hits:
            return None
        ctx.data.setdefault("tier3", []).extend(tiers.write_ups(guard_hits=hits))
        return spoken

    def on_silence(self, ctx: TurnContext, seconds: float) -> str | None:
        try:
            if KILL_SWITCH.exists():
                # A caller who stays quiet on a closed line still hears the closing line, at the first quiet stretch.
                ctx.data["hang_up"] = True
                _span(ctx, "kill", "switch", text="the kill switch file is set; the line closed this call")
                return KILL_LINE
            stretches: list[float] = ctx.data.setdefault("silences", [])
            stretches.append(float(seconds))
            if len(stretches) == 1:
                return HOLDING_LINE
            if sum(stretches[1:]) >= HOLD_LIMIT_S:
                ctx.data["hang_up"] = True
                return HOLD_LIMIT_LINE
            return None
        except Exception:
            log.exception("on_silence failed for %s", ctx.call_id)
            return None

    def on_tool(self, ctx: TurnContext, name: str, args: Mapping[str, Any], result: Any) -> None:
        # The loop records every tool's span, state and hand-off itself (turn.py), so nothing is needed here.
        return None

    def on_call_end(self, ctx: TurnContext, outcome: str | None) -> None:
        # Tier 3 is written up once, after the call: every reason the turns gathered, in one post. The summary
        # job (Sonnet 5.5) is the next work item; until then the post carries the reasons and the trace link.
        try:
            if ctx.data.get("length_capped") and screening.screen_unfinished(ctx):
                # Set by the media session when its length cap ended the call (spec section 7).
                ctx.data.setdefault("tier3", []).append(
                    "the length cap ended the call before the last question"
                )
            reasons = list(dict.fromkeys(ctx.data.get("tier3") or ()))
            if not reasons or ctx.escalations is None:
                return
            hand_off = tiers.escalation(ctx, "3", "; ".join(reasons), "read the trace")
            submitted = tiers.submit(ctx, hand_off)
            _span(
                ctx,
                "escalation",
                "3",
                text=hand_off.reason,
                meta={"suggested_action": hand_off.suggested_action, "submitted": submitted},
            )
        except Exception:  # a hook never breaks a hang-up
            log.exception("on_call_end failed for %s", ctx.call_id)


def _is_stop(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return bool(words) and "stop" in words and set(words) <= _STOP_WORDS


def _is_opt_out(text: str) -> bool:
    """One of the outbound stop phrases, as a whole phrase anywhere in what was said."""
    return bool(_OPT_OUT.search(straighten(text).lower()))


def is_hello(text: str, first_name: str = "") -> bool:
    """A transcript made only of hello words or the applicant's first name ("Hello? Yes, speaking."). The media
    session reads it too, so these words never barge in on the PIN ask (DR-025 fix 2)."""
    words = list(_HELLO_WORDS)
    name = first_name.strip().lower()
    if name:
        words += [name, f"this is {name}"]
    pattern = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return bool(re.fullmatch(rf"(?:[\s,.!?]*(?:{pattern})\b)+[\s,.!?]*", straighten(text).lower()))


def _span(ctx: TurnContext, kind: str, name: str, **fields: Any) -> None:
    """A span from a hook, when the call has a store. A failed write is logged; the call goes on."""
    if ctx.store is None:
        return
    try:
        ctx.store.span(ctx.call_id, kind, name, **fields)
    except Exception:
        log.exception("%s span failed for %s", kind, ctx.call_id)


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
