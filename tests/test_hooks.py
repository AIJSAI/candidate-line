"""The line's hooks: the transcript normaliser, the stop word and the kill switch, the holding lines, the guard and
the tier-3 write-up after the call, and on an outbound call the stop phrases and the hello rule (DR-025)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from candidate_line import hooks
from candidate_line.escalation import EscalationQueue, LogPoster
from candidate_line.hooks import LineHooks, is_hello
from candidate_line.persona import (
    FALLBACK_LINE,
    HOLD_LIMIT_LINE,
    HOLDING_LINE,
    KILL_LINE,
    OUTBOUND_STOP_LINE,
    PIN_ASK,
    STOP_LINE,
)
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


# The outbound stop phrases (DR-025 section 14, fix 4) and the hello rule (spec 9.7, fix 2).


class StopLedger:
    """The ledger reads and the one write the opt-out rule makes (DR-025 section 7), so these tests need no data."""

    def __init__(self, applicants: tuple[str, ...] = (), fail: bool = False) -> None:
        self.stops: list[tuple[str, str, str | None]] = []
        self._applicants = set(applicants)
        self._fail = fail

    def candidate(self, code: object) -> None:
        return None

    def applicant(self, code: object) -> SimpleNamespace | None:
        if code not in self._applicants:
            return None
        return SimpleNamespace(code=code, first_name="Lerato", role="care-aide", zone="America/Chicago")

    def opt_out(self, code: str, how: str, call_id: str | None = None, number_hmac: str | None = None) -> int:
        if self._fail:
            raise OSError("disk full")
        self.stops.append((code, how, call_id))
        return 1

    def screen(self, code: str) -> None:
        return None


def _outbound(ledger: StopLedger | None = None, confirmed: bool = False) -> TurnContext:
    ctx = _ctx()
    ctx.ledger = ledger or StopLedger(("ACME-3108",))  # type: ignore[assignment]
    ctx.data["outbound"] = {
        "code": "ACME-3108",
        "first_name": "Lerato",
        "dial_id": "D-0123456789ab",
        "attempt": 1,
    }
    if confirmed:
        ctx.data["candidate"] = "ACME-3108"
    return ctx


@pytest.mark.parametrize(
    "heard",
    [
        "Don't call me.",
        "Do not call me again, thanks.",
        "Please stop calling.",
        "Stop calling this number.",
        "Take me off your list.",
        "Stop.",
        "Okay stop",
        "Don’t call me",
    ],
)
def test_a_stop_phrase_on_an_outbound_call_stops_the_calls_with_the_outbound_stop_line(heard: str) -> None:
    ledger = StopLedger(("ACME-3108",))
    ctx = _outbound(ledger)
    assert LineHooks().on_turn(ctx, heard) is None
    assert ctx.data["hang_up"] is True and ctx.data["say"] == OUTBOUND_STOP_LINE
    assert ledger.stops == [("ACME-3108", "said stop", "CA-hooks")] and ctx.data["opted_out"] == "said stop"
    assert "tier_request" not in ctx.data


@pytest.mark.parametrize("heard", ["Wrong number.", "Sorry, not me.", "You have the wrong person."])
def test_a_wrong_person_before_the_pin_stops_the_calls_to_that_number_and_is_written_up(heard: str) -> None:
    ledger = StopLedger(("ACME-3108",))
    ctx = _outbound(ledger)
    LineHooks().on_turn(ctx, heard)
    assert ctx.data["say"] == OUTBOUND_STOP_LINE and ledger.stops == [
        ("ACME-3108", "wrong person", "CA-hooks")
    ]
    assert "wrong person" in ctx.data["tier_request"]


@pytest.mark.parametrize(
    "heard", ["don't stop", "stop the booking", "Can you stop by Friday?", "I'm nothing like that"]
)
def test_words_that_only_look_like_a_stop_go_to_the_model_on_an_outbound_call(heard: str) -> None:
    ledger = StopLedger(("ACME-3108",))
    ctx = _outbound(ledger, confirmed=True)
    LineHooks().on_turn(ctx, heard)
    assert "hang_up" not in ctx.data and "say" not in ctx.data and ledger.stops == []


def test_after_the_pin_not_me_is_an_answer_but_a_stop_phrase_still_stops() -> None:
    ledger = StopLedger(("ACME-3108",))
    ctx = _outbound(ledger, confirmed=True)
    LineHooks().on_turn(ctx, "No, not me, my back won't take it.")
    assert "hang_up" not in ctx.data and ledger.stops == []
    LineHooks().on_turn(ctx, "Actually, stop calling me.")
    assert ctx.data["say"] == OUTBOUND_STOP_LINE and ledger.stops == [("ACME-3108", "said stop", "CA-hooks")]


def test_an_applicant_who_called_in_stops_the_calls_and_anyone_else_keeps_todays_lines() -> None:
    ledger = StopLedger(("ACME-3108",))
    applicant = _ctx()
    applicant.ledger = ledger  # type: ignore[assignment]
    applicant.data["candidate"] = "ACME-3108"
    LineHooks().on_turn(applicant, "stop")
    assert applicant.data["say"] == OUTBOUND_STOP_LINE and ledger.stops[0][1] == "said stop"
    stranger = _ctx()
    stranger.ledger = StopLedger()  # type: ignore[assignment]
    LineHooks().on_turn(stranger, "stop")
    assert stranger.data["say"] == STOP_LINE
    LineHooks().on_turn(phrase := _ctx(), "please stop calling me")
    assert "hang_up" not in phrase.data  # from anyone else, a phrase goes to the model


def test_an_opt_out_that_cannot_be_saved_promises_nothing_and_is_written_up() -> None:
    ctx = _outbound(StopLedger(("ACME-3108",), fail=True))
    LineHooks().on_turn(ctx, "Don't call me.")
    assert ctx.data["say"] == STOP_LINE and ctx.data["hang_up"] is True
    assert "could not be saved" in ctx.data["tier_request"]


def test_a_stop_phrase_ends_the_turn_with_no_model_call_and_a_wrong_person_is_tier_three() -> None:
    from candidate_line.hooks import default_hooks
    from candidate_line.turn import run_turn

    class NoBrain:
        name = model = "none"

        def reply(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("no model call on a stop")

    stop = run_turn(NoBrain(), default_hooks(), _outbound(), "Stop calling me.")  # type: ignore[arg-type]
    assert stop.spoken == OUTBOUND_STOP_LINE and stop.hang_up is True and stop.tier == "1"
    wrong_ctx = _outbound()
    wrong = run_turn(NoBrain(), default_hooks(), wrong_ctx, "Wrong number.")  # type: ignore[arg-type]
    assert wrong.spoken == OUTBOUND_STOP_LINE and wrong.tier == "3"
    assert any("wrong person" in reason for reason in wrong_ctx.data["tier3"])


@pytest.mark.parametrize(
    "heard",
    [
        "Hello?",
        "Hello? Hello?",
        "Yes, speaking.",
        "Hi, this is Lerato.",
        "Lerato.",
        "Yeah, this is she.",
        "hey",
    ],
)
def test_a_hello_before_the_pin_gets_the_pin_ask_by_code(heard: str) -> None:
    ctx = _outbound()
    assert LineHooks().on_turn(ctx, heard) is None
    assert ctx.data["say"] == PIN_ASK and "hang_up" not in ctx.data


def test_the_hello_rule_says_the_pin_ask_twice_a_call_and_never_after_the_pin() -> None:
    ctx = _outbound()
    for _ in range(2):
        LineHooks().on_turn(ctx, "Hello?")
        assert ctx.data.pop("say") == PIN_ASK
    LineHooks().on_turn(ctx, "Hello?")
    assert "say" not in ctx.data  # a third goes to the model
    after = _outbound(confirmed=True)
    LineHooks().on_turn(after, "Yes.")
    assert "say" not in after.data
    inbound = _ctx()
    LineHooks().on_turn(inbound, "Hello?")
    assert "say" not in inbound.data


@pytest.mark.parametrize(
    "heard", ["Hello, my PIN is 4398.", "Who is this?", "hello there", "yes please call back"]
)
def test_more_than_hello_words_go_to_the_model(heard: str) -> None:
    assert is_hello(heard, "Lerato") is False


def test_the_length_cap_write_up_names_a_screen_left_unfinished() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-hooks", "outbound")
    ctx = _outbound()
    ctx.store = store
    poster = LogPoster()
    ctx.escalations = EscalationQueue(store, poster)
    ctx.data["length_capped"] = True  # what the media session sets when its cap ends the call (lane B)
    LineHooks().on_call_end(ctx, "9 turns")
    ctx.escalations.drain()
    [row] = store.escalations("CA-hooks")
    assert row.tier == "3" and "the length cap ended the call before the last question" in row.reason
