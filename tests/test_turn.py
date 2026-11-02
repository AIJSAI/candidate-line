from candidate_line.brain import EchoBrain, Message
from candidate_line.hooks import HookChain, NoHooks
from candidate_line.turn import TurnContext, run_silence, run_turn


def ctx() -> TurnContext:
    return TurnContext(call_id="t1", channel="text", system="sys")


def test_a_turn_with_no_hooks_passes_the_words_both_ways() -> None:
    result = run_turn(EchoBrain(), NoHooks(), c := ctx(), "hello")
    assert (result.heard, result.spoken) == ("hello", "hello")
    assert c.history == [Message("user", "hello"), Message("assistant", "hello")]


class Rewriter:
    def on_turn(self, ctx, user_text):
        return user_text.replace("one two", "12")

    def before_speak(self, ctx, text):
        return None

    def on_silence(self, ctx, seconds):
        return None

    def on_tool(self, ctx, name, args, result):
        return None


class Guard:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def on_turn(self, ctx, user_text):
        return None

    def before_speak(self, ctx, text):
        self.seen.append(text)
        return "I don't evaluate people." if "strong" in text else None

    def on_silence(self, ctx, seconds):
        return "Still there?" if seconds >= 5 else None

    def on_tool(self, ctx, name, args, result):
        return None


def test_on_turn_rewrites_what_the_brain_hears() -> None:
    result = run_turn(EchoBrain(), HookChain([Rewriter()]), ctx(), "code one two")
    assert result.heard == "code 12" and result.spoken == "code 12"


def test_before_speak_replaces_and_the_history_keeps_the_replacement() -> None:
    guard = Guard()
    c = ctx()
    result = run_turn(EchoBrain(), HookChain([Rewriter(), guard]), c, "you look strong")
    assert result.spoken == "I don't evaluate people."
    assert guard.seen == ["you look strong"]
    assert c.history[-1] == Message("assistant", "I don't evaluate people.")


def test_before_speak_can_silence_gus() -> None:
    class Mute(Guard):
        def before_speak(self, ctx, text):
            return ""

    result = run_turn(EchoBrain(), HookChain([Mute()]), ctx(), "anything")
    assert result.spoken == ""


def test_silence_hook_speaks_only_past_its_threshold() -> None:
    c = ctx()
    assert run_silence(HookChain([Guard()]), c, 2) is None
    assert run_silence(HookChain([Guard()]), c, 6) == "Still there?"
    assert c.history == [Message("assistant", "Still there?")]


def test_later_hooks_see_earlier_replacements() -> None:
    class Upper(Guard):
        def before_speak(self, ctx, text):
            self.seen.append(text)
            return text.upper()

    first, second = Guard(), Upper()
    run_turn(EchoBrain(), HookChain([first, second]), ctx(), "you look strong")
    assert second.seen == ["I don't evaluate people."]
