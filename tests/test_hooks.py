"""The line's hooks: the transcript normaliser, the stop word and the kill switch, the holding lines, the guard and
the tier-3 write-up after the call."""

from __future__ import annotations

import pytest

from candidate_line import hooks
from candidate_line.escalation import EscalationQueue, LogPoster
from candidate_line.hooks import LineHooks
from candidate_line.persona import FALLBACK_LINE, HOLD_LIMIT_LINE, HOLDING_LINE, KILL_LINE, STOP_LINE
from candidate_line.traces.store import TraceStore
from candidate_line.turn import TurnContext, run_silence


def _ctx(store: TraceStore | None = None) -> TurnContext:
    return TurnContext(call_id="CA-hooks", channel="voice", system="", store=store)


# The normaliser, on what the transcriber wrote.


@pytest.mark.parametrize(
    ("heard", "brain_reads"),
    [
        ("acne 3233 PI 9683", "ACME-3233 PIN 9683"),
        ("My code is acne 3,233 and my pin is 96 83.", "My code is ACME-3233 and my PIN 9683."),
        ("coat 3233", "code ACME-3233"),
        ("Acme three two three three, pin zero nine six three", "ACME-3233, PIN 0963"),
        ("A C M E 1431, pen 963", "ACME-1431, PIN 963"),
        ("it's 3,233", "it's 3233"),
    ],
)
def test_on_turn_writes_the_code_and_pin_the_way_the_records_do(heard: str, brain_reads: str) -> None:
    assert LineHooks().on_turn(_ctx(), heard) == brain_reads


@pytest.mark.parametrize(
    "heard",
    [
        "ACME-3233 PIN 9683",
        "Can I book Thursday at 9 30?",
        "Friday 6 November at 9:30",
        "my zip code is 68102",
        "I have 2 questions",
    ],
)
def test_on_turn_leaves_words_it_has_nothing_to_fix_alone(heard: str) -> None:
    assert LineHooks().on_turn(_ctx(), heard) is None


def test_a_normaliser_that_fails_lets_the_brain_hear_the_caller_as_said(monkeypatch, caplog) -> None:
    def broken(text: str) -> str:
        raise RuntimeError("regex down")

    monkeypatch.setattr(hooks, "normalise_transcript", broken)
    assert LineHooks().on_turn(_ctx(), "acne 3233") is None
    assert "on_turn failed for CA-hooks" in caplog.text


# The caller's stop and the kill switch.


@pytest.mark.parametrize(
    "heard",
    [
        "stop",
        "Stop.",
        "stop please",
        "Please stop!",
        "STOP",
        "Okay stop",
        "stop now",
        "just stop",
        "Stop, goodbye.",
        "stop the call",
        "stop it",
    ],
)
def test_a_caller_who_says_only_stop_is_hung_up_on_with_the_stop_line(heard: str) -> None:
    ctx = _ctx()
    assert LineHooks().on_turn(ctx, heard) is None
    assert ctx.data["hang_up"] is True and ctx.data["say"] == STOP_LINE


@pytest.mark.parametrize(
    "heard",
    [
        "stop the booking",
        "don't stop",
        "please",
        "Can you stop by Friday?",
        "I want to stop by the office",
        "please stop calling me",
        "can you stop",
    ],
)
def test_stop_inside_a_sentence_goes_to_the_brain(heard: str) -> None:
    ctx = _ctx()
    LineHooks().on_turn(ctx, heard)
    assert "hang_up" not in ctx.data


def test_the_kill_switch_file_closes_every_call_while_it_exists(monkeypatch, tmp_path) -> None:
    flag = tmp_path / "kill"
    monkeypatch.setattr(hooks, "KILL_SWITCH", flag)
    store = TraceStore(":memory:")
    store.start_call("CA-hooks", "voice")
    ctx = _ctx(store)
    LineHooks().on_turn(ctx, "hello")
    assert "hang_up" not in ctx.data
    flag.touch()
    LineHooks().on_turn(ctx, "hello")
    assert ctx.data["hang_up"] is True and ctx.data["say"] == KILL_LINE
    assert [(s.kind, s.name) for s in store.spans("CA-hooks")] == [("kill", "switch")]


def test_a_quiet_caller_on_a_closed_line_hears_the_closing_line_not_the_holding_line(
    monkeypatch, tmp_path
) -> None:
    flag = tmp_path / "kill"
    monkeypatch.setattr(hooks, "KILL_SWITCH", flag)
    flag.touch()
    store = TraceStore(":memory:")
    store.start_call("CA-hooks", "voice")
    reply = run_silence(LineHooks(), _ctx(store), 6.0)
    assert reply.said == KILL_LINE and reply.hang_up is True
    assert [(s.kind, s.name) for s in store.spans("CA-hooks")] == [("kill", "switch")]


# The holding lines.


def test_the_holding_line_comes_first_and_the_hold_limit_after_thirty_more_seconds() -> None:
    line, ctx = LineHooks(), _ctx()
    assert run_silence(line, ctx, 6.0).said == HOLDING_LINE
    for _ in range(4):  # the phone fires again after each further six quiet seconds
        assert run_silence(line, ctx, 6.0).said is None
    closing = run_silence(line, ctx, 6.0)
    assert closing.said == HOLD_LIMIT_LINE and closing.hang_up is True


def test_the_callers_words_start_the_hold_count_again() -> None:
    line, ctx = LineHooks(), _ctx()
    assert line.on_silence(ctx, 6.0) == HOLDING_LINE
    assert line.on_silence(ctx, 24.0) is None
    line.on_turn(ctx, "Sorry, I'm back.")
    assert line.on_silence(ctx, 6.0) == HOLDING_LINE  # the first stretch again, not the limit
    assert line.on_silence(ctx, 30.0) == HOLD_LIMIT_LINE and ctx.data["hang_up"] is True


# The guard.


def test_the_guard_replaces_the_caught_sentence_and_records_the_verdicts() -> None:
    ctx = _ctx()
    spoken = LineHooks().before_speak(ctx, "Thursday at 9:30 works. You're a strong candidate.")
    assert spoken == f"Thursday at 9:30 works. {FALLBACK_LINE}"
    assert ctx.data["guard"] == ["clean", "p01"]
    assert ctx.data["tier3"] == ["the guard replaced a sentence (p01)"]


def test_a_clean_reply_or_a_quoted_refusal_passes_unchanged() -> None:
    ctx = _ctx()
    assert LineHooks().before_speak(ctx, "Thirty minutes, by video. That is from F2.1.") is None
    assert LineHooks().before_speak(ctx, "I can't tell you whether you'll move on.") is None
    assert ctx.data["guard"] == ["clean"] and "tier3" not in ctx.data


@pytest.mark.parametrize(
    "said",
    [
        "I can't repeat the PIN aloud. You did say nine six eight three, and the check passed.",
        "I have 9683 on file for you.",
        "Nine, six, eight, three.",
    ],
)
def test_a_pin_given_on_this_call_is_caught_however_it_is_said_back(said: str) -> None:
    ctx = _ctx()
    ctx.data["pins_heard"] = ["9683"]  # what verify_caller keeps (synthetic, Hannah's)
    spoken = LineHooks().before_speak(ctx, said)
    assert spoken is not None and "nine six" not in spoken.lower() and "9683" not in spoken
    assert "pin-heard" in ctx.data["guard"] and "pin-heard" in ctx.data["tier3"][0]


@pytest.mark.parametrize(
    "said",
    ["Your code is ACME, 3 2 3 3, and you're verified.", "Thursday 5 November at 9:30 AM Central is open."],
)
def test_the_code_and_a_slot_time_are_not_taken_for_a_heard_pin(said: str) -> None:
    ctx = _ctx()
    ctx.data["pins_heard"] = ["9683"]
    assert LineHooks().before_speak(ctx, said) is None


@pytest.mark.parametrize(
    "said",
    [
        "I can't tell you anything except that you're a strong candidate.",
        "I don't have access to notes that say you did well.",
    ],
)
def test_a_refusal_cue_does_not_excuse_a_judgement_after_except_or_that_say(said: str) -> None:
    ctx = _ctx()
    assert LineHooks().before_speak(ctx, said) == FALLBACK_LINE


def test_a_guard_that_fails_says_the_fallback_line_not_the_unchecked_words(monkeypatch, caplog) -> None:
    class Broken:
        def check(self, text: str, extra: object = None) -> list:
            raise RuntimeError("lexicon gone")

    monkeypatch.setattr(hooks, "GUARD", Broken())
    ctx = _ctx()
    assert LineHooks().before_speak(ctx, "anything at all") == FALLBACK_LINE
    assert ctx.data["guard"] == ["error"] and "before_speak failed" in caplog.text


# The write-up after the call.


def test_the_call_end_posts_one_tier_three_hand_off_with_every_reason_once() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-hooks", "voice", caller="+15555550142")
    poster = LogPoster()
    queue = EscalationQueue(store, poster)
    ctx = _ctx(store)
    ctx.escalations = queue
    ctx.data["tier3"] = [
        "the guard replaced a sentence (p01)",
        "the refusal line was said",
        "the guard replaced a sentence (p01)",
    ]
    LineHooks().on_call_end(ctx, "3 turns")
    queue.drain()
    [row] = store.escalations("CA-hooks")
    assert row.tier == "3" and row.suggested_action == "read the trace"
    assert row.reason == "the guard replaced a sentence (p01); the refusal line was said"
    assert "http://127.0.0.1:8001/calls/CA-hooks" in poster.posted[0] and "***-***-0142" in poster.posted[0]
    assert [(s.kind, s.name) for s in store.spans("CA-hooks")] == [("escalation", "3")]


def test_a_call_with_nothing_to_write_up_posts_nothing() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-hooks", "voice")
    ctx = _ctx(store)
    ctx.escalations = EscalationQueue(store, LogPoster())
    LineHooks().on_call_end(ctx, "1 turns")
    ctx.escalations.drain()
    assert store.escalations("CA-hooks") == []
