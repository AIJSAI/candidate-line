import json
from datetime import UTC, datetime

import pytest

from candidate_line import hooks as hooks_module
from candidate_line import turn as turn_module
from candidate_line.brain import EchoBrain, Message, Reply, ToolCall
from candidate_line.hooks import HookChain, NoHooks, default_hooks
from candidate_line.persona import FALLBACK_LINE, KILL_LINE, RECOVERY_LINE, REFUSAL_LINE, STOP_LINE
from candidate_line.tools import TOOL_SPECS, Ledger, actions
from candidate_line.traces.store import TraceStore
from candidate_line.turn import SilenceReply, TurnContext, run_silence, run_turn


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

    def on_call_end(self, ctx, outcome):
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

    def on_call_end(self, ctx, outcome):
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
    assert run_silence(HookChain([Guard()]), c, 2) == SilenceReply(said=None, hang_up=False)
    assert run_silence(HookChain([Guard()]), c, 6) == SilenceReply(said="Still there?", hang_up=False)
    assert c.history == [Message("assistant", "Still there?")]


def test_a_silence_hook_that_asks_for_the_hang_up_gets_it_once() -> None:
    class Holding(Guard):
        def on_silence(self, ctx, seconds):
            ctx.data["hang_up"] = True  # the holding line at the hold limit (card 06)
            return "I'll let you go. Call back any time."

    c = ctx()
    reply = run_silence(HookChain([Holding()]), c, 30)
    assert reply == SilenceReply(said="I'll let you go. Call back any time.", hang_up=True)
    assert "hang_up" not in c.data  # popped, so a later silence does not inherit the request
    assert run_silence(HookChain([Guard()]), c, 6).hang_up is False


def test_the_chain_runs_every_call_end_hook_in_order() -> None:
    seen: list[tuple[str, str | None]] = []

    class Recorder(Guard):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        def on_call_end(self, ctx, outcome):
            seen.append((self.name, outcome))

    HookChain([Recorder("first"), Recorder("second")]).on_call_end(ctx(), "2 turns")
    assert seen == [("first", "2 turns"), ("second", "2 turns")]
    assert NoHooks().on_call_end(ctx(), None) is None


def test_later_hooks_see_earlier_replacements() -> None:
    class Upper(Guard):
        def before_speak(self, ctx, text):
            self.seen.append(text)
            return text.upper()

    first, second = Guard(), Upper()
    run_turn(EchoBrain(), HookChain([first, second]), ctx(), "you look strong")
    assert second.seen == ["I don't evaluate people."]


def test_a_turn_hook_that_asks_for_the_hang_up_gets_it_on_the_result_once() -> None:
    class KillSwitch(NoHooks):
        def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
            ctx.data["hang_up"] = True
            return user_text

    c = ctx()
    assert run_turn(EchoBrain(), KillSwitch(), c, "hello").hang_up is True
    assert "hang_up" not in c.data and run_turn(EchoBrain(), NoHooks(), c, "again").hang_up is False


# The tool loop (card 04), the stop word and the kill switch (card 06), and the spans (card 03), against a scripted
# brain that asks for tools the way the native channel does. Every ledger pins its clock to the afternoon before the
# first slot, so no test waits for the calendar.

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
HANNAH = {"code": "ACME-3233", "pin": "9683"}  # invited, no slot (data/candidates.yaml, synthetic)
PRIYA = {"code": "ACME-6792", "pin": "4731"}  # booked S1109-1400


def pinned() -> Ledger:
    return Ledger(now=lambda: NOW)


class ScriptedBrain:
    """Returns its replies in order and records what it was sent; one call too many fails the test."""

    name = "scripted"
    model = "scripted"

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[Message], tuple]] = []

    def reply(self, system, messages, max_tokens=200, tools=()):
        self.calls.append((list(messages), tuple(tools)))
        if not self.replies:
            raise AssertionError("the brain was called once more than the script allows")
        return self.replies.pop(0)


def said(text: str) -> Reply:
    return Reply(text, 50, 10, 100, "scripted", "scripted")


def asks(*calls: tuple[str, dict], text: str = "") -> Reply:
    tool_calls = tuple(ToolCall(f"tu-{name}-{i}", name, args) for i, (name, args) in enumerate(calls))
    return Reply(text, 50, 10, 100, "scripted", "scripted", tool_calls=tool_calls, stop_reason="tool_use")


def tool_ctx(store: TraceStore | None = None, channel: str = "text") -> TurnContext:
    return TurnContext(call_id="CA-turn", channel=channel, system="sys", store=store, ledger=pinned())


def test_verify_then_book_across_two_model_calls_in_one_turn() -> None:
    brain = ScriptedBrain(
        asks(("verify_caller", HANNAH)),
        asks(("book_slot", {"slot_id": "S1105-0930"})),
        said(
            "Booked, Thursday 5 November at 9:30 AM Central. A confirmation email follows within a few minutes."
        ),
    )
    c = tool_ctx()
    result = run_turn(brain, NoHooks(), c, "ACME-3233 PIN 9683. Thursday at 9:30, please.")
    assert result.tools_called == ("verify_caller", "book_slot")
    assert result.state == {"booked_slot": "S1105-0930", "moves_used": 0, "callback_requested": False}
    assert result.spoken.startswith("Booked, Thursday 5 November") and result.tier == "1"
    # One Reply for the whole turn: three model calls folded.
    assert (result.reply.latency_ms, result.reply.input_tokens, result.reply.output_tokens) == (300, 150, 30)
    assert len(brain.calls) == 3 and brain.calls[0][1] == TOOL_SPECS
    assert [m.role for m in c.history] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert c.history[1].tool_calls[0].name == "verify_caller" and not c.history[2].tool_results[0].is_error
    assert all("9683" not in r.content for m in c.history for r in m.tool_results)
    # The booking's reversal waits in the undo list; the phone runs it when the caller's next words supersede.
    [undo] = c.data["undo"]
    undo()
    assert c.ledger is not None and c.ledger.is_open("S1105-0930")


def test_tools_default_to_the_line_s_specs_and_can_be_narrowed() -> None:
    brain = ScriptedBrain(said("Hello."))
    run_turn(brain, NoHooks(), tool_ctx(), "hi", tools=TOOL_SPECS[:1])
    assert brain.calls[0][1] == TOOL_SPECS[:1]


def test_a_question_the_faq_covers_is_answered_and_cited() -> None:
    brain = ScriptedBrain(
        asks(("answer_question", {"section_ids": ["F2.1"]})),
        said(
            "Thirty minutes, by video, with one engineer. That is from F2.1, how long it is and in what format."
        ),
    )
    result = run_turn(brain, NoHooks(), c := tool_ctx(), "How long is the first interview?")
    assert result.cited == ("F2.1",) and result.tools_called == ("answer_question",) and result.tier == "1"
    assert "tier3" not in c.data or c.data["tier3"] == []


def test_a_question_the_faq_does_not_cover_speaks_the_refusal_line_with_no_second_model_call() -> None:
    brain = ScriptedBrain(asks(("answer_question", {"section_ids": ["F9.9"]})))
    store = TraceStore(":memory:")
    store.start_call("CA-turn", "text")
    c = tool_ctx(store)
    result = run_turn(brain, NoHooks(), c, "What does the job pay?")
    assert result.spoken == REFUSAL_LINE and len(brain.calls) == 1
    assert result.cited == () and result.tools_called == ("answer_question",)
    assert result.tier == "3" and c.data["tier3"] == [
        "the refusal line was said: the FAQ has no answer to the question"
    ]
    assert c.history[-1] == Message("assistant", REFUSAL_LINE)
    [cite] = [span for span in store.spans("CA-turn") if span.kind == "cite"]
    assert (cite.name, cite.meta) == ("none", {"refused": True})


def test_a_refusal_the_model_says_itself_cites_none_of_the_sections_it_fetched() -> None:
    brain = ScriptedBrain(asks(("answer_question", {"section_ids": ["F1"]})), said(REFUSAL_LINE))
    result = run_turn(brain, NoHooks(), c := tool_ctx(), "What does the job pay?")
    assert result.spoken == REFUSAL_LINE and result.cited == () and result.tier == "3"
    assert c.data["tier3"] == ["the refusal line was said: the FAQ has no answer to the question"]


def test_a_tool_that_raises_is_an_error_result_and_the_turn_goes_on(monkeypatch) -> None:
    def broken(args, ctx):
        raise RuntimeError("calendar file gone")

    monkeypatch.setitem(actions._TOOLS, "list_open_slots", broken)
    brain = ScriptedBrain(asks(("list_open_slots", {})), said("Sorry, I couldn't read the slots."))
    c = tool_ctx()
    result = run_turn(brain, NoHooks(), c, "What slots are open?")
    [error] = c.history[2].tool_results
    assert error.is_error and "callback" in json.loads(error.content)["error"]
    assert result.spoken == "Sorry, I couldn't read the slots." and result.tools_called == (
        "list_open_slots",
    )


def test_a_dispatcher_that_raises_is_still_an_error_result_never_an_exception(monkeypatch) -> None:
    def exploding(name, args, ctx):
        raise RuntimeError("dispatcher down")

    monkeypatch.setattr(turn_module, "run_tool", exploding)
    brain = ScriptedBrain(asks(("verify_caller", HANNAH)), said("Something went wrong on my side."))
    result = run_turn(brain, NoHooks(), c := tool_ctx(), "ACME-3233 PIN 9683")
    assert c.history[2].tool_results[0].is_error and result.spoken == "Something went wrong on my side."


def test_the_caller_saying_stop_ends_the_call_with_no_model_call() -> None:
    brain = ScriptedBrain()  # any model call fails the test
    result = run_turn(brain, default_hooks(), c := tool_ctx(), "Stop, please.")
    assert result.spoken == STOP_LINE and result.hang_up is True and brain.calls == []
    assert result.tier == "1" and result.tools_called == () and result.reply.latency_ms == 0
    assert c.history[-1] == Message("assistant", STOP_LINE) and "hang_up" not in c.data


def test_the_kill_switch_file_closes_the_call_inside_one_turn(monkeypatch, tmp_path) -> None:
    flag = tmp_path / "kill"
    monkeypatch.setattr(hooks_module, "KILL_SWITCH", flag)
    flag.touch()
    result = run_turn(ScriptedBrain(), default_hooks(), tool_ctx(), "I'd like to book a slot.")
    assert result.spoken == KILL_LINE and result.hang_up is True
    flag.unlink()  # read on every turn, never cached
    reopened = run_turn(ScriptedBrain(said("Sure.")), default_hooks(), tool_ctx(), "I'd like to book a slot.")
    assert reopened.spoken == "Sure." and reopened.hang_up is False


def test_end_call_hangs_up_on_the_goodbye_that_came_with_it() -> None:
    brain = ScriptedBrain(asks(("end_call", {}), text="Goodbye."))
    result = run_turn(brain, NoHooks(), tool_ctx(), "That's all, thanks.")
    assert result.spoken == "Goodbye." and result.hang_up is True and len(brain.calls) == 1


def test_the_loop_gives_up_after_five_model_calls_and_takes_back_what_the_turn_did() -> None:
    brain = ScriptedBrain(
        asks(("verify_caller", HANNAH)),
        asks(("list_open_slots", {})),
        asks(("book_slot", {"slot_id": "S1105-0930"})),
        asks(("answer_question", {"section_ids": ["F3.1"]})),
        asks(("list_open_slots", {})),
    )
    c = tool_ctx()
    result = run_turn(brain, NoHooks(), c, "ACME-3233 PIN 9683, book me Thursday at 9:30.")
    assert result.spoken == RECOVERY_LINE and len(brain.calls) == 5
    assert result.tools_called == ("verify_caller", "list_open_slots", "book_slot", "answer_question")
    # The caller heard only the recovery line, so no booking or verification stands that they never heard.
    assert c.ledger is not None and c.ledger.is_open("S1105-0930") and "candidate" not in c.data
    assert result.cited == () and result.state is None and c.data["undo"] == []
    assert [m.role for m in c.history] == ["user", "assistant"]


def test_an_empty_reply_after_a_tool_is_the_recovery_line_never_silence() -> None:
    brain = ScriptedBrain(asks(("verify_caller", HANNAH)), said(""))
    c = tool_ctx()
    result = run_turn(brain, NoHooks(), c, "ACME-3233 PIN 9683")
    assert result.spoken == RECOVERY_LINE
    # Bedrock refuses an empty assistant message on every later turn of the call.
    assert all(m.text or m.tool_calls or m.tool_results for m in c.history)


def test_a_refusal_beside_a_booking_says_the_booking_and_then_the_line() -> None:
    brain = ScriptedBrain(
        asks(("verify_caller", HANNAH)),
        asks(("book_slot", {"slot_id": "S1105-0930"}), ("answer_question", {"section_ids": []})),
        said("Booked, Thursday 5 November at 9:30 AM Central."),
    )
    result = run_turn(
        brain, NoHooks(), c := tool_ctx(), "ACME-3233 PIN 9683. Thursday 9:30, and what's the pay?"
    )
    assert result.spoken == f"Booked, Thursday 5 November at 9:30 AM Central. {REFUSAL_LINE}"
    assert result.state is not None and result.state["booked_slot"] == "S1105-0930"
    assert result.tier == "3" and result.cited == () and len(brain.calls) == 3
    assert "the refusal line was said" in " ".join(c.data["tier3"])


def test_a_refusal_in_the_model_s_own_words_becomes_the_refusal_line() -> None:
    brain = ScriptedBrain(said("I don't have salary information. Would you like a callback?"))
    result = run_turn(brain, NoHooks(), c := tool_ctx(), "What's the salary for the role?")
    assert result.spoken == REFUSAL_LINE and result.tier == "3" and result.cited == ()
    assert c.data["tier3"] == ["the refusal line was said: the FAQ has no answer to the question"]


def test_own_refusal_words_beside_a_verification_are_kept_so_the_code_is_still_read_back() -> None:
    brain = ScriptedBrain(
        asks(("verify_caller", HANNAH)), said("You're verified, ACME 3 2 3 3. The FAQ doesn't cover parking.")
    )
    result = run_turn(brain, NoHooks(), tool_ctx(), "ACME-3233 PIN 9683, where do I park?")
    assert result.spoken.startswith("You're verified") and result.tier == "1"


def test_a_returned_section_the_model_left_unnamed_is_named_aloud_by_heading_and_id() -> None:
    brain = ScriptedBrain(
        asks(("answer_question", {"section_ids": ["F2.1", "F5.1"]})),
        said("Thirty minutes, by video. Per the logistics section, F5.1, the email carries the link."),
    )
    result = run_turn(brain, NoHooks(), tool_ctx(), "How long is the first interview, and is it on video?")
    assert result.spoken.endswith("That is from the first-round interview section, F2.1.")
    assert result.cited == ("F2.1", "F5.1")


def test_a_long_reply_is_cut_to_two_sentences_and_the_one_naming_a_section() -> None:
    brain = ScriptedBrain(
        asks(("answer_question", {"section_ids": ["F2.1"]})),
        said("Thirty minutes. By video. With one engineer. That is from F2.1. Would you like to book?"),
    )
    result = run_turn(brain, NoHooks(), tool_ctx(), "How long is the first interview?")
    assert result.spoken == "Thirty minutes. By video. That is from F2.1."


def test_a_brain_error_mid_turn_closes_the_history_before_it_is_raised() -> None:
    class Failing(ScriptedBrain):
        def reply(self, system, messages, max_tokens=200, tools=()):
            if self.calls:
                raise RuntimeError("the model is down")
            return super().reply(system, messages, max_tokens, tools)

    c = tool_ctx()
    with pytest.raises(RuntimeError):
        run_turn(Failing(asks(("verify_caller", HANNAH))), NoHooks(), c, "ACME-3233 PIN 9683")
    assert c.history[-1] == Message("assistant", RECOVERY_LINE)  # the next turn's messages still alternate


def test_a_move_posts_a_tier_two_hand_off_at_once_with_the_masked_caller() -> None:
    class Queue:
        def __init__(self) -> None:
            self.items: list = []

        def submit(self, e) -> bool:
            self.items.append(e)
            return True

    store = TraceStore(":memory:")
    store.start_call("CA-turn", "voice", caller="+15555550142")
    c = tool_ctx(store, channel="voice")
    c.escalations = Queue()  # type: ignore[assignment]
    brain = ScriptedBrain(
        asks(("verify_caller", PRIYA)),
        asks(("move_slot", {"preferred": "Friday morning"})),
        said("I've passed that to the coordinator, who returns calls within one business day."),
    )
    result = run_turn(brain, NoHooks(), c, "ACME-6792 PIN 4731, can I move my slot to Friday morning?")
    assert result.tier == "2" and result.tools_called == ("verify_caller", "move_slot")
    [hand_off] = c.escalations.items
    assert hand_off.tier == "2" and hand_off.reason.startswith("move request from ACME-6792")
    assert hand_off.caller == "***-***-0142" and hand_off.trace_url.endswith("/calls/CA-turn")
    kinds = [(s.kind, s.name) for s in store.spans("CA-turn")]
    assert ("escalation", "2") in kinds and kinds[-1] == ("tier", "2")
    assert not any(k == "transcribe" or k == "speech" for k, _ in kinds)  # media.py writes those on a call


# What the model wrote on CL-033 by voice (the voice regression of 2026-11-05, DR-024), read from its model span.
CL_033_REPLY = (
    "I've asked the coordinator to call you back tomorrow after 3 p.m. about your notice period. "
    "They'll call within one business day."
)


def test_the_spoken_cap_keeps_the_promise_after_a_p_m_inside_a_sentence() -> None:
    # "p.m." read as a sentence end made three sentences of two, and the cap cut the one spec 7.2 requires.
    assert turn_module._spoken_cap(CL_033_REPLY) == CL_033_REPLY
    result = run_turn(ScriptedBrain(said(CL_033_REPLY)), NoHooks(), tool_ctx(), "Call me after 3 PM?")
    assert result.spoken == CL_033_REPLY
    # The cap still cuts a third sentence.
    assert turn_module._spoken_cap("Open at 9 a.m. on Friday. Then 2 p.m. Central. And more.") == (
        "Open at 9 a.m. on Friday. Then 2 p.m. Central."
    )


def test_the_spoken_cap_drops_a_greeting_and_a_filler_before_the_ask() -> None:
    # CL-005 on the eval step of 2026-11-05: four sentences, and the first two said nothing.
    reply = (
        "Hi Hannah. I can help with that. First I need your application code and your four-digit PIN. "
        'Please say the code first, starting with "Application" and then the four digits.'
    )
    assert turn_module._spoken_cap(reply) == (
        "First I need your application code and your four-digit PIN. "
        'Please say the code first, starting with "Application" and then the four digits.'
    )
    # A closing offer goes before a sentence that says something; a section name still rides along.
    assert turn_module._spoken_cap(
        "Sure. The interview runs 45 minutes. That is in section F2.1. Anything else?"
    ) == ("The interview runs 45 minutes. That is in section F2.1.")
    # Two sentences are never touched, filler or not; all filler keeps its first two.
    assert turn_module._spoken_cap("Hi Hannah. I can help with that.") == "Hi Hannah. I can help with that."
    assert turn_module._spoken_cap("Hi. Sure. Of course.") == "Hi. Sure."
    # A sentence that opens with a greeting word but says something is not filler.
    assert turn_module._spoken_cap(
        "Thanks, Hannah, you are verified. Thursday at 9:30 is open. Shall I book it?"
    ) == ("Thanks, Hannah, you are verified. Thursday at 9:30 is open.")


class Posted:
    """The escalation queue's submit, kept in a list: what the operator would be sent."""

    def __init__(self) -> None:
        self.items: list = []

    def submit(self, e) -> bool:
        self.items.append(e)
        return True


def test_one_request_asked_again_by_a_superseded_turn_s_carried_words_posts_one_hand_off() -> None:
    # CL-033 by voice (DR-024): the first final asked for the callback and the line posted it; the caller went on,
    # and the carried words asked again with a reason, which the reason-text check let through as a second email.
    store = TraceStore(":memory:")
    store.start_call("CA-turn", "voice")
    c = tool_ctx(store, channel="voice")
    c.escalations = Posted()  # type: ignore[assignment]
    run_turn(ScriptedBrain(asks(("verify_caller", HANNAH)), said("You're verified.")), NoHooks(), c, "x")
    half = "Could the coordinator call me back tomorrow after 3 PM?"
    before = len(c.history)
    first = ScriptedBrain(asks(("request_callback", {"best_time": "tomorrow after 3 PM"})), said("Done."))
    run_turn(first, NoHooks(), c, half)
    # Superseded, as media.py takes it back: never heard, its effects undone, its words carried into the next turn.
    del c.history[before:]
    for reverse in reversed(c.data.pop("undo")):
        reverse()
    again = {"best_time": "tomorrow after 3 PM", "reason": "notice period"}
    second = ScriptedBrain(asks(("request_callback", again)), said("They'll call within one business day."))
    result = run_turn(second, NoHooks(), c, f"{half} It's about my notice period.")
    assert result.tier == "2"
    [posted] = c.escalations.items
    assert posted.reason.startswith("callback request from ACME-3233")
    spans = [s for s in store.spans("CA-turn") if s.kind == "escalation"]
    assert [bool(s.meta.get("duplicate")) for s in spans] == [False, True]
    # The repeat's fuller words stay in the trace that the posted hand-off links to.
    assert "notice period" in (spans[1].text or "")


def test_two_different_requests_on_one_call_post_two_hand_offs_and_another_call_posts_its_own() -> None:
    def call() -> TurnContext:
        c = tool_ctx()
        c.escalations = Posted()  # type: ignore[assignment]
        move = ScriptedBrain(
            asks(("verify_caller", PRIYA)),
            asks(("move_slot", {"preferred": "Friday morning"})),
            said("I've passed that to the coordinator."),
        )
        run_turn(move, NoHooks(), c, "ACME-6792 PIN 4731, can I move to Friday morning?")
        callback = ScriptedBrain(
            asks(("request_callback", {"reason": "a visa question"})), said("I've asked the coordinator.")
        )
        run_turn(callback, NoHooks(), c, "And could someone call me about a visa?")
        return c

    for c in (call(), call()):
        reasons = [e.reason for e in c.escalations.items]
        assert [r.split(" from ")[0] for r in reasons] == ["move request", "callback request"]


def test_a_second_miss_is_tier_three_and_a_superseded_turn_takes_its_miss_back() -> None:
    wrong = {"code": "ACME-3233", "pin": "1111"}
    c = tool_ctx()
    first = run_turn(
        ScriptedBrain(asks(("verify_caller", wrong)), said("That didn't match.")), NoHooks(), c, "x"
    )
    assert first.tier == "1" and c.data["verify_failures"] == 1
    second = run_turn(
        ScriptedBrain(asks(("verify_caller", wrong)), said("Still no match.")), NoHooks(), c, "y"
    )
    assert second.tier == "3" and "verification failed 2 times" in second_reason(c)
    for reverse in reversed(c.data["undo"]):  # what media.py does when the caller's next words supersede
        reverse()
    assert c.data["verify_failures"] == 1 and c.data["tier3"] == []


def second_reason(c: TurnContext) -> str:
    return " ".join(c.data.get("tier3") or ())


def test_a_guard_hit_through_the_line_s_hooks_is_replaced_and_written_up() -> None:
    brain = ScriptedBrain(said("Honestly, you're a strong candidate."))
    result = run_turn(brain, default_hooks(), c := tool_ctx(), "How am I doing?")
    assert result.spoken == FALLBACK_LINE and result.tier == "3"
    assert c.data["guard"] == ["p01"] and c.data["tier3"] == ["the guard replaced a sentence (p01)"]


def test_a_turn_s_spans_land_in_the_store_in_reading_order_and_carry_no_pin() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-turn", "text")
    brain = ScriptedBrain(
        asks(("verify_caller", HANNAH)),
        asks(("answer_question", {"section_ids": ["F2.1"]})),
        said("Thirty minutes, by video. That is from F2.1."),
    )
    run_turn(brain, NoHooks(), tool_ctx(store), "ACME-3233, PIN 9683. How long is the interview?")
    spans = store.spans("CA-turn")
    assert [(s.kind, s.name) for s in spans] == [
        ("transcribe", "heard"),
        ("model", "scripted"),
        ("tool", "verify_caller"),
        ("model", "scripted"),
        ("tool", "answer_question"),
        ("model", "scripted"),
        ("cite", "F2.1"),
        ("speech", "spoken"),
        ("hook", "guard"),
        ("tier", "1"),
    ]
    heard, _, verify = spans[:3]
    assert heard.text == "ACME-****, PIN ****. How long is the interview?"
    assert verify.meta["args"] == {"code": "ACME-3233", "pin": "****"} and verify.text == "verified ACME-3233"
    assert spans[-1].meta["model_calls"] == 3 and spans[-1].meta["model_ms"] == 300
    assert "9683" not in repr(spans)


def test_text_mode_runs_on_the_ledger_it_is_given() -> None:
    from candidate_line.text_mode import repl

    ledger = pinned()
    ctx = repl(ScriptedBrain(said("Hello.")), NoHooks(), ["hi", "/quit"], [].append, ledger=ledger)
    assert ctx.ledger is ledger


def test_each_eval_case_gets_its_own_ledger_so_two_cases_can_book_one_slot(monkeypatch) -> None:
    from candidate_line.evals import runner
    from candidate_line.evals.schema import parse_case

    made: list[Ledger] = []

    def fresh() -> Ledger:
        made.append(pinned())
        return made[-1]

    monkeypatch.setattr(runner, "Ledger", fresh)
    case = parse_case(
        {
            "id": "book",
            "title": "books Thursday at 9:30",
            "kind": "regression",
            "turns": [
                {
                    "user": "ACME-3233 PIN 9683, Thursday 9:30",
                    "checks": [{"state": {"booked_slot": "S1105-0930"}}],
                }
            ],
        }
    )
    for _ in range(2):
        brain = ScriptedBrain(
            asks(("verify_caller", HANNAH)), asks(("book_slot", {"slot_id": "S1105-0930"})), said("Booked.")
        )
        assert runner.run_case(case, brain, NoHooks()).passed
    assert len(made) == 2 and made[0] is not made[1]


def test_one_utterance_read_two_ways_in_one_turn_spends_one_try_and_the_right_pair_still_verifies() -> None:
    c = tool_ctx()
    # The caller said one pair once; the model tried two readings of the PIN in one turn.
    brain = ScriptedBrain(
        asks(("verify_caller", {"code": "ACME-3233", "pin": "9863"})),
        asks(("verify_caller", {"code": "ACME-3233", "pin": "9836"})),
        said("Sorry, that didn't match. Could you say the PIN again, digit by digit?"),
    )
    run_turn(brain, NoHooks(), c, "ACME 3233, PIN nine eight six three... no wait")
    assert c.data["verify_failures"] == 1
    brain2 = ScriptedBrain(asks(("verify_caller", HANNAH)), said("Thanks, you're verified."))
    run_turn(brain2, NoHooks(), c, "It's 9683.")
    assert c.data["candidate"] == "ACME-3233"


def test_a_five_call_cap_turn_takes_back_its_miss_with_the_rest_of_what_it_did() -> None:
    c = tool_ctx()
    wrong = {"code": "ACME-3233", "pin": "1111"}
    brain = ScriptedBrain(
        asks(("verify_caller", wrong)),
        asks(("verify_caller", wrong)),
        asks(("list_open_slots", {})),
        asks(("list_open_slots", {})),
        asks(("list_open_slots", {})),
    )
    result = run_turn(brain, NoHooks(), c, "ACME 3233 PIN 1111")
    # The caller heard only "say it again", so no try was spent and they can still verify.
    assert result.spoken == RECOVERY_LINE and c.data.get("verify_failures") == 0
    brain2 = ScriptedBrain(asks(("verify_caller", HANNAH)), said("Thanks, you're verified."))
    run_turn(brain2, NoHooks(), c, "ACME 3233 PIN 9683")
    assert c.data["candidate"] == "ACME-3233"


# The say branch (DR-025 sections 2 and 3, fix 3): a tool's words said by code, with no further model call.

LONG_FIXED = (
    "That's every question, thank you. A recruiter will read all your answers before the interview. The nearest "
    "open interview times are Thursday 5 November at 9:00 AM Central and Friday 6 November at 9:00 AM Central. "
    "Which suits you?"
)


def _say_tool(words: str, **extra: object):
    def tool(args, ctx):
        return actions.ToolOutcome(content='{"recorded":true}', say=words, **extra)

    return tool


def test_a_tools_say_is_spoken_whole_with_no_further_model_call(monkeypatch) -> None:
    monkeypatch.setitem(actions._TOOLS, "record_answer", _say_tool(f"Noted: yes. {LONG_FIXED}"))
    brain = ScriptedBrain(asks(("record_answer", {"question_id": "q5", "value": "yes", "heard": "yes"})))
    result = run_turn(brain, default_hooks(), c := tool_ctx(), "Yes, that range works.")
    # Four sentences and no section named: the cap and the section naming would both have changed it.
    assert result.spoken == f"Noted: yes. {LONG_FIXED}" and len(brain.calls) == 1
    assert [m.role for m in c.history] == ["user", "assistant", "tool", "assistant"]
    assert c.history[-1] == Message("assistant", result.spoken) and result.tier == "1"


def test_a_say_in_the_models_own_refusal_words_is_still_said_as_given(monkeypatch) -> None:
    words = (
        "That PIN didn't match. I don't have that information on file. Please say the four digits once more."
    )
    monkeypatch.setitem(actions._TOOLS, "confirm_applicant", _say_tool(words))
    brain = ScriptedBrain(asks(("confirm_applicant", {"pin": "1111"})))
    result = run_turn(brain, NoHooks(), tool_ctx(), "1111")
    assert result.spoken == words and result.cited == () and result.tier == "1"


def test_the_guard_still_reads_a_tools_say(monkeypatch) -> None:
    monkeypatch.setitem(
        actions._TOOLS, "record_answer", _say_tool("Noted: yes. You qualify for an interview.")
    )
    brain = ScriptedBrain(asks(("record_answer", {"question_id": "q1", "value": "yes", "heard": "yes"})))
    result = run_turn(brain, default_hooks(), tool_ctx(), "yes")
    assert result.spoken == f"Noted: yes. {FALLBACK_LINE}" and result.tier == "3"


def test_the_last_say_wins_and_a_refusal_beside_it_is_neither_said_nor_written_up(monkeypatch) -> None:
    monkeypatch.setitem(actions._TOOLS, "record_answer", _say_tool("Noted: no. Next question?"))
    brain = ScriptedBrain(
        asks(
            ("record_answer", {"question_id": "q1", "value": "no", "heard": "no"}),
            ("answer_question", {"section_ids": []}),
        )
    )
    result = run_turn(brain, NoHooks(), c := tool_ctx(), "No. And what's the pay?")
    assert result.spoken == "Noted: no. Next question?" and len(brain.calls) == 1
    assert result.tier == "1" and c.data.get("tier3", []) == []


def test_a_hooks_say_without_a_hang_up_is_spoken_with_no_model_call() -> None:
    class Asker(NoHooks):
        def on_turn(self, ctx: TurnContext, user_text: str) -> str | None:
            ctx.data["say"] = "To go on, please say the four-digit PIN you chose when you applied."
            return None

    c = tool_ctx()
    result = run_turn(ScriptedBrain(), Asker(), c, "Hello?")
    assert result.spoken.startswith("To go on") and result.hang_up is False and "say" not in c.data
    assert c.history == [Message("user", "Hello?"), Message("assistant", result.spoken)]


def test_the_hand_offs_a_turn_posted_are_on_its_result_and_make_it_tier_two(monkeypatch) -> None:
    hand_off = actions.HandOff(
        reason="screening hand-off from ACME-3108 (Lerato): Home Care Aide; recruiter call promised by x",
        suggested_action="read the record",
        record_code="ACME-3108",
    )
    monkeypatch.setitem(
        actions._TOOLS, "record_answer", _say_tool("Noted: no. A recruiter will call.", escalate=hand_off)
    )

    class Queue:
        def __init__(self) -> None:
            self.items: list = []

        def submit(self, e) -> bool:
            self.items.append(e)
            return True

    c = tool_ctx()
    c.escalations = Queue()  # type: ignore[assignment]
    brain = ScriptedBrain(asks(("record_answer", {"question_id": "q5", "value": "no", "heard": "no"})))
    result = run_turn(brain, NoHooks(), c, "No.")
    assert result.tier == "2" and result.tools_called == ("record_answer",)
    [posted] = result.hand_offs
    assert (
        c.escalations.items == [posted] and posted.record_url == "http://127.0.0.1:8001/applicants/ACME-3108"
    )
    # The same hand-off again on the call is not posted twice, and the turn has none on its result.
    again = run_turn(
        ScriptedBrain(asks(("record_answer", {"question_id": "q5", "value": "no", "heard": "no"}))),
        NoHooks(),
        c,
        "No.",
    )
    assert again.hand_offs == () and len(c.escalations.items) == 1


def test_an_answers_value_is_kept_in_the_span_and_anything_else_there_is_masked(monkeypatch) -> None:
    monkeypatch.setitem(actions._TOOLS, "record_answer", _say_tool("Noted."))
    store = TraceStore(":memory:")
    store.start_call("CA-turn", "text")
    for value in ("weekends", "25", "9683"):
        brain = ScriptedBrain(
            asks(("record_answer", {"question_id": "q2", "value": value, "heard": f"it is {value}"}))
        )
        run_turn(brain, NoHooks(), tool_ctx(store), value)
    args = [s.meta["args"] for s in store.spans("CA-turn") if s.kind == "tool"]
    assert [a["value"] for a in args] == ["weekends", "25", "****"]
    assert [a["heard"] for a in args] == ["it is weekends", "it is 25", "it is ****"]
    assert all(a["question_id"] == "q2" for a in args) and "9683" not in repr(store.spans("CA-turn"))


def test_the_state_on_an_outbound_call_before_the_pin_is_the_dialled_applicants() -> None:
    class Ledgerish:
        def state(self, code: str) -> dict:
            return {"code": code, "opted_out": False}

    c = TurnContext(call_id="CA-out", channel="voice", system="", ledger=Ledgerish())  # type: ignore[arg-type]
    c.data["outbound"] = {
        "code": "ACME-3108",
        "first_name": "Lerato",
        "dial_id": "D-0123456789ab",
        "attempt": 1,
    }
    result = run_turn(ScriptedBrain(said("Please say your PIN.")), NoHooks(), c, "Who is this?")
    assert result.state == {"code": "ACME-3108", "opted_out": False}
