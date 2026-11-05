import asyncio
import base64
import threading
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candidate_line.brain import EchoBrain
from candidate_line.hooks import NoHooks
from candidate_line.persona import PIN_ASK
from candidate_line.settings import Settings
from candidate_line.telephony.app import Deps, create_app, twiml_stream
from candidate_line.telephony.audio import MULAW_FRAME_BYTES, mulaw_to_pcm16, pcm16_to_mulaw, split_sentences
from candidate_line.telephony.media import (
    RECOVERY_LINE,
    MediaSession,
    is_filler,
    is_hello,
    mask_spoken_digits,
)
from candidate_line.telephony.speech import FakeSpeaker, Heard, ScriptedTranscriber
from candidate_line.tools.ledger import Ledger
from candidate_line.traces.store import TraceStore

SID = "MZ123"
# The media tests count the sentences Gus says, so they greet in one sentence of their own; the persona's greeting
# (candidate_line.persona.GREETING) is three, and its words are not what these tests are about.
GREETING = "ACME candidate line, this is Gus."


def frame() -> dict:
    return {
        "event": "media",
        "streamSid": SID,
        "media": {"payload": base64.b64encode(b"\xff" * MULAW_FRAME_BYTES).decode()},
    }


def said_text(sent: list[dict]) -> int:
    """The fake speaker emits one mu-law byte per character, so the media bytes count the characters spoken."""
    return sum(len(base64.b64decode(m["media"]["payload"])) for m in sent if m["event"] == "media")


def test_codec_round_trip_and_sentence_split() -> None:
    pcm = b"\x00\x10\x00\x20\xf0\xff" * 10
    assert len(mulaw_to_pcm16(pcm16_to_mulaw(pcm))) == len(pcm)
    assert len(pcm16_to_mulaw(pcm)) == len(pcm) // 2
    assert split_sentences("Yes. Thursday at nine thirty works! Anything else?") == [
        "Yes.",
        "Thursday at nine thirty works!",
        "Anything else?",
    ]
    assert split_sentences("  one line no period ") == ["one line no period"]


# What the model wrote on CL-033 by voice (the voice regression of 2026-11-05, DR-024), read from its model span.
CL_033_REPLY = (
    "I've asked the coordinator to call you back tomorrow after 3 p.m. about your notice period. "
    "They'll call within one business day."
)
CL_033_SENTENCES = [
    "I've asked the coordinator to call you back tomorrow after 3 p.m. about your notice period.",
    "They'll call within one business day.",
]


@pytest.mark.parametrize(
    ("text", "sentences"),
    [
        (CL_033_REPLY, CL_033_SENTENCES),
        (
            "Slots at 9:30 a.m. and 2 P.M. are open. Which one?",
            ["Slots at 9:30 a.m. and 2 P.M. are open.", "Which one?"],
        ),
        (
            "Your slot is at 2 p.m. Central. Anything else?",
            ["Your slot is at 2 p.m. Central.", "Anything else?"],
        ),
        ("Say a weekday, e.g. Friday. Or a date.", ["Say a weekday, e.g. Friday.", "Or a date."]),
        (
            "Bring the invitation, i.e. the email. That's all.",
            ["Bring the invitation, i.e. the email.", "That's all."],
        ),
        ("Booking vs. moving is F3.1. A move waits.", ["Booking vs. moving is F3.1.", "A move waits."]),
        (
            "The panel is J. Doe and team. It is on video.",
            ["The panel is J. Doe and team.", "It is on video."],
        ),
        # a word in capitals is not an initial
        ("You called ACME. Goodbye.", ["You called ACME.", "Goodbye."]),
    ],
)
def test_a_full_stop_in_an_abbreviation_or_after_an_initial_does_not_end_the_sentence(
    text: str, sentences: list[str]
) -> None:
    assert split_sentences(text) == sentences


def test_polly_is_called_by_the_same_splitter_so_the_cl_033_reply_is_said_whole_in_two_sentences() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        transcriber.hear(CL_033_REPLY, is_partial=False)  # the echo brain says it back through the turn's cap
        await settle(lambda: len(speaker.said) == 3)
        yield {"event": "stop", "streamSid": SID}

    run_session(transcriber, speaker, script)
    assert speaker.said == [GREETING, *CL_033_SENTENCES]


def run_session(
    transcriber: ScriptedTranscriber, speaker: FakeSpeaker, script, greeting=GREETING, grace_ms=(50, 150)
) -> tuple[list[dict], MediaSession]:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send,
        transcriber,
        speaker,
        EchoBrain(),
        NoHooks(),
        "sys",
        "CA1",
        SID,
        greeting=greeting,
        grace_ms=grace_ms,
    )

    async def incoming():
        async for message in script(session, sent):
            yield message

    asyncio.run(session.run(incoming()))
    return sent, session


async def settle(predicate, seconds: float = 2.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.01)


def test_greets_echoes_and_clears_speaking_on_the_last_mark() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        yield frame()
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        assert session.speaking is True
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        await settle(lambda: not session.speaking)
        transcriber.hear("hello there", is_partial=False)
        await settle(lambda: "hello there" in speaker.said)
        await settle(lambda: sum(m["event"] == "mark" for m in sent) == 2)
        yield {"event": "stop", "streamSid": SID}

    sent, session = run_session(transcriber, speaker, script)
    assert transcriber.started and transcriber.stopped
    assert transcriber.fed == MULAW_FRAME_BYTES * 2  # one 20 ms frame, widened to 16-bit PCM
    assert speaker.said == [GREETING, "hello there"]
    assert said_text(sent) == len(GREETING) + len("hello there")
    assert [m["event"] for m in sent].count("clear") == 0
    assert session.turns == 1 and session.barge_ins == 0


def test_a_partial_while_speaking_sends_clear_and_drops_the_rest() -> None:
    gate = threading.Event()
    calls = {"n": 0}

    def delay() -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # hold the second sentence until the test has interrupted
            gate.wait(2)

    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker(delay=delay)

    async def script(session, sent):
        await settle(lambda: sum(m["event"] == "mark" for m in sent) == 1)
        transcriber.hear("wait", is_partial=True)
        await settle(lambda: any(m["event"] == "clear" for m in sent))
        gate.set()
        await asyncio.sleep(0.05)
        yield {"event": "stop", "streamSid": SID}

    sent, session = run_session(transcriber, speaker, script, greeting="First sentence. Second sentence.")
    assert session.barge_ins == 1 and session.speaking is False
    events = [m["event"] for m in sent]
    assert events.count("clear") == 1 and events.count("mark") == 1
    assert said_text(sent) == len("First sentence.")


def test_a_partial_while_quiet_is_ignored() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        yield {"event": "mark", "streamSid": SID, "mark": {"name": sent[-1]["mark"]["name"]}}
        await settle(lambda: not session.speaking)
        transcriber.hear("um", is_partial=True)
        await asyncio.sleep(0.05)
        yield {"event": "stop", "streamSid": SID}

    sent, session = run_session(transcriber, speaker, script)
    assert session.barge_ins == 0 and "clear" not in [m["event"] for m in sent]


def test_voice_answers_the_stream_verb_in_stream_mode_and_fails_closed_without_a_host() -> None:
    assert twiml_stream("https://abc.trycloudflare.com/") == (
        '<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="wss://abc.trycloudflare.com/media" /></Connect></Response>'
    )
    streaming = TestClient(
        create_app(
            Settings.from_env(
                {
                    "ALLOW_UNSIGNED_WEBHOOKS": "1",
                    "PUBLIC_BASE_URL": "https://h.example",
                    "TRACE_STORE_PATH": ":memory:",
                }
            )
        )
    )
    assert "<Connect><Stream" in streaming.post("/voice", data={"CallSid": "CA1"}).text
    no_host = TestClient(
        create_app(Settings.from_env({"ALLOW_UNSIGNED_WEBHOOKS": "1", "TRACE_STORE_PATH": ":memory:"}))
    )
    assert no_host.post("/voice", data={"CallSid": "CA1"}).status_code == 503
    saying = TestClient(
        create_app(
            Settings.from_env(
                {"ALLOW_UNSIGNED_WEBHOOKS": "1", "VOICE_MODE": "say", "TRACE_STORE_PATH": ":memory:"}
            )
        )
    )
    assert "<Say" in saying.post("/voice", data={"CallSid": "CA1"}).text


def test_the_media_websocket_runs_a_session_end_to_end() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    deps = Deps(
        transcriber=lambda: transcriber,
        speaker=lambda: speaker,
        brain=EchoBrain,
        hooks=NoHooks,
        greeting="Hi.",
    )
    client = TestClient(
        create_app(
            Settings.from_env(
                {"BRAIN_PROVIDER": "echo", "TRACE_STORE_PATH": ":memory:", "ALLOW_UNSIGNED_WEBHOOKS": "1"}
            ),
            deps,
        )
    )
    with client.websocket_connect("/media") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(
            {
                "event": "start",
                "streamSid": SID,
                "start": {"callSid": "CA9", "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}},
            }
        )
        first = ws.receive_json()
        assert first["event"] == "media" and base64.b64decode(first["media"]["payload"]) == b"\xff" * len(
            "Hi."
        )
        mark = ws.receive_json()
        assert mark["event"] == "mark"
        ws.send_json({"event": "mark", "streamSid": SID, "mark": {"name": mark["mark"]["name"]}})
        ws.send_json(frame())
        transcriber.hear("book me thursday", is_partial=False)
        echo = ws.receive_json()
        assert echo["event"] == "media" and len(base64.b64decode(echo["media"]["payload"])) == len(
            "book me thursday"
        )
        assert ws.receive_json()["event"] == "mark"
        ws.send_json({"event": "stop", "streamSid": SID})
    assert speaker.said == ["Hi.", "book me thursday"] and transcriber.stopped


async def quiet(session, sent, transcriber) -> None:
    """Lets the greeting finish and its mark come back, so the session is quiet before the caller speaks."""
    await settle(lambda: any(m["event"] == "mark" for m in sent))
    session._on_mark(sent[-1]["mark"]["name"])
    await settle(lambda: not session.speaking)


def test_two_finals_inside_the_grace_become_one_turn() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        transcriber.hear("Hi, I got an invite.", is_partial=False)
        await asyncio.sleep(0.02)  # inside the 150 ms grace that follows a full stop
        transcriber.hear("What should I expect?", is_partial=False)
        await settle(lambda: session.turns == 1 and len(speaker.said) == 3)  # the echo, spoken by sentence
        await asyncio.sleep(0.2)  # long enough for a second turn to have fired if the finals were not joined
        yield {"event": "stop", "streamSid": SID}

    _sent, session = run_session(transcriber, speaker, script)
    assert speaker.said == [GREETING, "Hi, I got an invite.", "What should I expect?"]
    assert session.turns == 1


def test_a_partial_inside_the_grace_holds_the_turn_for_the_next_final() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        transcriber.hear("Hi, I got an invite.", is_partial=False)
        await asyncio.sleep(0.03)
        transcriber.hear("what should", is_partial=True)  # the caller is still talking
        await asyncio.sleep(0.2)  # past the 150 ms grace: the partial must have held the turn
        assert session.turns == 0
        transcriber.hear("What should I expect?", is_partial=False)
        await settle(lambda: session.turns == 1 and len(speaker.said) == 3)
        yield {"event": "stop", "streamSid": SID}

    _sent, session = run_session(transcriber, speaker, script)
    assert speaker.said[1:] == ["Hi, I got an invite.", "What should I expect?"]
    assert session.barge_ins == 0


def test_a_question_mark_waits_less_than_a_full_stop() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    waits: dict[str, float] = {}

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        for line in ("Can I?", "Thanks."):
            t0 = time.monotonic()
            transcriber.hear(line, is_partial=False)
            await settle(lambda line=line: speaker.said[-1] == line)
            waits[line] = time.monotonic() - t0
        yield {"event": "stop", "streamSid": SID}

    run_session(transcriber, speaker, script, grace_ms=(50, 400))
    assert waits["Can I?"] < 0.3
    assert waits["Thanks."] >= 0.35


def test_a_turn_still_in_its_grace_is_dropped_when_the_caller_hangs_up() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        transcriber.hear("Hello", is_partial=False)  # 150 ms grace; the stop arrives first
        yield {"event": "stop", "streamSid": SID}

    _sent, session = run_session(transcriber, speaker, script)
    assert session.turns == 0 and speaker.said == [GREETING]


class GatedEcho:
    """An echo brain that answers only when the test opens the gate, so a turn can be caught mid-thought."""

    name = "gated-echo"
    model = "none"

    def __init__(self) -> None:
        self.gate = threading.Event()
        self._echo = EchoBrain()

    def reply(self, system, history, max_tokens=200, tools=()):
        self.gate.wait(2)
        return self._echo.reply(system, history, max_tokens=max_tokens, tools=tools)


def test_a_partial_while_the_reply_is_being_made_supersedes_it_and_the_words_carry_over() -> None:
    transcriber, speaker, brain = ScriptedTranscriber(), FakeSpeaker(), GatedEcho()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, brain, NoHooks(), "sys", "CA1", SID, greeting=GREETING, grace_ms=(50, 60)
    )

    async def script():
        await quiet(session, sent, transcriber)
        transcriber.hear("Hi, I got an invite.", is_partial=False)
        await settle(lambda: session._thinking)  # the grace passed and the reply is being made
        transcriber.hear("What should", is_partial=True)  # the caller went on before Gus spoke
        await asyncio.sleep(0.02)
        transcriber.hear("What should I expect?", is_partial=False)
        brain.gate.set()
        await settle(lambda: session.turns == 1 and len(speaker.said) == 3)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert session.superseded == 1 and session.turns == 1 and session.barge_ins == 0
    assert speaker.said[1:] == ["Hi, I got an invite.", "What should I expect?"]
    assert [m.role for m in session.ctx.history] == ["user", "assistant"]
    assert session.ctx.history[0].text == "Hi, I got an invite. What should I expect?"


class SilenceHooks(NoHooks):
    def on_silence(self, ctx, seconds):
        return "Still there?"


def test_the_silence_hook_fires_on_the_phone_after_a_quiet_stretch() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send,
        transcriber,
        speaker,
        EchoBrain(),
        SilenceHooks(),
        "sys",
        "CA1",
        SID,
        greeting=GREETING,
        silence_after_s=0.2,
    )

    async def script():
        await quiet(session, sent, transcriber)
        await settle(lambda: "Still there?" in speaker.said, seconds=2.0)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert speaker.said[:2] == [GREETING, "Still there?"]


def test_a_turn_that_says_hang_up_ends_the_call_after_its_line_has_played(monkeypatch) -> None:
    from candidate_line import turn as turn_module
    from candidate_line.brain import Reply
    from candidate_line.telephony import media as media_module
    from candidate_line.turn import TurnResult

    def closing(brain, hooks, ctx, text, max_tokens=None):
        return TurnResult(text, "Goodbye for today.", Reply("", 0, 0, 0, "echo", "none"), hang_up=True)

    monkeypatch.setattr(media_module, "run_turn", closing)
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []
    frames_after_close = {"n": 0}

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), NoHooks(), "sys", "CA1", SID, greeting=None
    )

    async def script():
        transcriber.hear("anything", is_partial=False)
        await settle(lambda: "Goodbye for today." in speaker.said)
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        for _ in range(50):  # the stream goes on sending frames; the session must stop reading them
            yield frame()
            frames_after_close["n"] += 1
            await asyncio.sleep(0.01)

    asyncio.run(session.run(script()))
    assert speaker.said == ["Goodbye for today."]
    assert frames_after_close["n"] < 50  # the loop ended before the stream did
    assert turn_module.TurnResult is TurnResult


class CallEndRecorder(NoHooks):
    """Records each call-end hook with whether the store had already recorded the end at that moment."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store
        self.seen: list[tuple[str, str | None, bool]] = []

    def on_call_end(self, ctx, outcome):
        row = self.store.call(ctx.call_id)
        self.seen.append((ctx.call_id, outcome, row is not None and row.ended_at is not None))


def stopped_session(hooks, store: TraceStore) -> MediaSession:
    """A session whose caller says one thing and hangs up, on the fake ears and mouth."""
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), hooks, "sys", "CA1", SID, greeting=None, store=store
    )

    async def script():
        transcriber.hear("hello there", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert transcriber.stopped  # the hang-up ran to its end
    return session


def test_the_phone_runs_the_call_end_hook_once_just_before_the_store_ends_the_call() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    hooks = CallEndRecorder(store)
    stopped_session(hooks, store)
    assert hooks.seen == [("CA1", "1 turns, 0 barge-ins, 0 superseded", False)]
    assert store.call("CA1").ended_at is not None


def test_a_call_end_hook_that_raises_never_breaks_the_phones_hang_up(caplog) -> None:
    class Broken(NoHooks):
        def on_call_end(self, ctx, outcome):
            raise RuntimeError("summary job down")

    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    stopped_session(Broken(), store)
    assert store.call("CA1").outcome == "1 turns, 0 barge-ins, 0 superseded"
    assert any("on_call_end failed" in r.getMessage() for r in caplog.records)


class HoldingLine(NoHooks):
    def on_silence(self, ctx, seconds):
        ctx.data["hang_up"] = True  # the holding line at the hold limit (card 06)
        return "I'll let you go. Call back any time."


def test_a_silence_hook_that_asks_for_the_hang_up_ends_the_call_after_its_line_has_played() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []
    frames_after_close = {"n": 0}

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send,
        transcriber,
        speaker,
        EchoBrain(),
        HoldingLine(),
        "sys",
        "CA1",
        SID,
        greeting=GREETING,
        silence_after_s=0.2,
    )

    async def script():
        await quiet(session, sent, transcriber)
        # The event is set only after the line's last mark has gone out, so every mark is in `sent` by then.
        await settle(lambda: session._hang_up.is_set())
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        for _ in range(50):  # the stream goes on sending frames; the session must stop reading them
            yield frame()
            frames_after_close["n"] += 1
            await asyncio.sleep(0.01)

    asyncio.run(session.run(script()))
    assert speaker.said == [GREETING, "I'll let you go.", "Call back any time."]  # spoken by sentence
    assert frames_after_close["n"] < 50  # the loop ended before the stream did
    assert "hang_up" not in session.ctx.data


class RaisingBrain:
    """A brain whose every reply raises, standing in for a model error or a tool that blew up on a turn."""

    model = "raising"

    def reply(self, *args, **kwargs):
        raise RuntimeError("the model is down")


def test_a_failed_turn_speaks_the_recovery_line_instead_of_silence(caplog) -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send,
        transcriber,
        speaker,
        RaisingBrain(),
        NoHooks(),
        "sys",
        "CA1",
        SID,
        greeting=GREETING,
        grace_ms=(50, 150),
    )

    async def script(*_):
        yield frame()
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        await settle(lambda: not session.speaking)
        transcriber.hear("book me thursday", is_partial=False)
        await settle(lambda: len(speaker.said) == 3)  # the greeting, then the recovery line's two sentences
        yield {"event": "stop", "streamSid": SID}

    async def incoming():
        async for message in script():
            yield message

    asyncio.run(session.run(incoming()))
    assert speaker.said[0] == GREETING and " ".join(speaker.said[1:]) == RECOVERY_LINE
    assert "turn failed for CA1" in caplog.text and "the model is down" in caplog.text


@pytest.mark.parametrize("text", ["Uh huh.", "Mm hmm.", "Huh?", "uh, huh", "MM HMM"])
def test_a_yes_in_two_filler_words_and_a_huh_asking_again_are_speech(text: str) -> None:
    assert not is_filler(text)


def test_a_transcript_made_only_of_fillers_is_a_filler() -> None:
    for text in ("Um,", "um", "Uh... hmm.", "MHM.", "Er, erm, ah?", "huh", "", "   ", "..."):
        assert is_filler(text), text
    for text in ("Um, I have a question.", "3233", "Mm-hmm.", "Uh-huh.", "ah, okay", "PIN"):
        assert not is_filler(text), text


def test_a_span_masks_every_run_of_three_or_more_digits_but_keeps_times_and_dates() -> None:
    assert mask_spoken_digits("My code is ACME-3233, PIN 4417.") == "My code is ACME-****, PIN ****."
    assert mask_spoken_digits("It's 32 33 and 0, 417") == "It's ** ** and *, ***"
    assert mask_spoken_digits("four four one seven") == "* * * *"
    assert (
        mask_spoken_digits("Thursday 5 November at 9:30 AM Central")
        == "Thursday 5 November at 9:30 AM Central"
    )
    assert mask_spoken_digits("one or two questions") == "one or two questions"


def test_a_filler_partial_while_speaking_neither_clears_nor_arms_the_grace() -> None:
    gate = threading.Event()
    calls = {"n": 0}

    def delay() -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # hold the second sentence while the caller says "Um,"
            gate.wait(2)

    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker(delay=delay)
    grace_seen: list[object] = []

    async def script(session, sent):
        await settle(lambda: sum(m["event"] == "mark" for m in sent) == 1)
        transcriber.hear("Um,", is_partial=True)
        await asyncio.sleep(0.05)
        grace_seen.append(session._grace)
        gate.set()
        await settle(lambda: sum(m["event"] == "mark" for m in sent) == 2)
        yield {"event": "stop", "streamSid": SID}

    sent, session = run_session(transcriber, speaker, script, greeting="First sentence. Second sentence.")
    assert session.barge_ins == 0 and "clear" not in [m["event"] for m in sent]
    assert speaker.said == ["First sentence.", "Second sentence."]
    assert grace_seen == [None]


def test_a_filler_partial_while_the_reply_is_being_made_does_not_supersede_it() -> None:
    transcriber, speaker, brain = ScriptedTranscriber(), FakeSpeaker(), GatedEcho()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, brain, NoHooks(), "sys", "CA1", SID, greeting=GREETING, grace_ms=(50, 60)
    )

    async def script():
        await quiet(session, sent, transcriber)
        transcriber.hear("Hi, I got an invite.", is_partial=False)
        await settle(lambda: session._thinking)
        transcriber.hear("Uh", is_partial=True)
        await asyncio.sleep(0.02)
        brain.gate.set()
        await settle(lambda: session.turns == 1 and len(speaker.said) == 2)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert session.superseded == 0 and session.turns == 1
    assert speaker.said == [GREETING, "Hi, I got an invite."]


def test_a_filler_final_makes_no_turn_and_is_traced_as_dropped(caplog) -> None:
    caplog.set_level("INFO", logger="candidate_line.media")
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), NoHooks(), "sys", "CA1", SID, grace_ms=(50, 60), store=store
    )

    async def script():
        transcriber.hear("Um,", is_partial=False)
        await asyncio.sleep(0.2)  # well past the grace: a turn would have fired by now
        assert session._pending == [] and session._grace is None
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert session.turns == 0 and speaker.said == []
    assert "filler dropped CA1 'Um,'" in caplog.text
    [span] = store.spans("CA1")
    assert (span.kind, span.name, span.text, span.meta) == (
        "transcribe",
        "final",
        "Um,",
        {"dropped": "filler"},
    )


def test_a_final_with_words_after_a_filler_still_makes_a_turn() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        transcriber.hear("Um, can I book Thursday?", is_partial=False)
        await settle(lambda: session.turns == 1 and len(speaker.said) == 2)
        yield {"event": "stop", "streamSid": SID}

    _sent, session = run_session(transcriber, speaker, script)
    assert session.turns == 1 and speaker.said[1:] == ["Um, can I book Thursday?"]


def test_a_call_writes_a_transcribe_span_per_final_and_a_speech_span_per_line() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []
    heard = "My code is ACME-3233. PIN 4417."

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), NoHooks(), "sys", "CA1", SID, greeting="Hi.", store=store
    )

    async def script():
        await quiet(session, sent, transcriber)
        transcriber._put(Heard(heard, is_partial=False, confidence=0.91, final_lag_ms=420))
        await settle(lambda: session.turns == 1 and len(speaker.said) == 3)
        await settle(lambda: len(media_spans(store)) == 3)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    # The turn loop writes its own spans (model, guard, tier) between these; this file owns these two kinds.
    greeting, final, reply = media_spans(store)
    assert [(s.kind, s.name) for s in (greeting, final, reply)] == [
        ("speech", "polly"),
        ("transcribe", "final"),
        ("speech", "polly"),
    ]
    assert final.text == "My code is ACME-****. PIN ****." and "4417" not in (reply.text or "")
    assert (final.ms, final.seconds, final.meta) == (420, None, {"confidence": 0.91})
    assert greeting.chars == len("Hi.") and greeting.meta == {}  # no turn clock runs for the greeting
    assert reply.chars == len(heard) and isinstance(reply.ms, int) and reply.ms >= 0
    assert reply.meta["first_audio_gap_ms"] >= 0


def media_spans(store: TraceStore) -> list:
    return [s for s in store.spans("CA1") if s.kind in ("transcribe", "speech")]


def test_a_span_write_that_fails_never_breaks_the_call(caplog) -> None:
    class BrokenStore(TraceStore):
        def span(self, *args, **kwargs):
            raise RuntimeError("disk full")

    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    store = BrokenStore(":memory:")
    store.start_call("CA1", "voice")
    session = stopped_session_on(transcriber, speaker, store)
    assert session.turns == 1 and speaker.said == ["hello there"]
    assert "transcribe span failed for CA1" in caplog.text and "speech span failed for CA1" in caplog.text


def stopped_session_on(
    transcriber: ScriptedTranscriber, speaker: FakeSpeaker, store: TraceStore
) -> MediaSession:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), NoHooks(), "sys", "CA1", SID, greeting=None, store=store
    )

    async def script():
        transcriber.hear("hello there", is_partial=False)
        # The speech span is written in the same step as the line's mark, so the mark means the write was tried.
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    return session


def test_a_superseded_turn_undoes_its_tools_newest_first_and_a_kept_turn_does_not(
    monkeypatch, caplog
) -> None:
    from candidate_line.brain import Reply
    from candidate_line.telephony import media as media_module
    from candidate_line.turn import TurnResult

    gate = threading.Event()
    undone: list[str] = []
    calls = {"n": 0}

    def broken() -> None:
        raise RuntimeError("ledger busy")

    def turn(brain, hooks, ctx, text, max_tokens=None):
        calls["n"] += 1
        if calls["n"] == 1:  # the half question books a slot, then the caller goes on
            ctx.data.setdefault("undo", []).extend(
                [lambda: undone.append("first"), broken, lambda: undone.append("second")]
            )
            gate.wait(2)
        else:
            ctx.data["undo"] = [lambda: undone.append("kept")]
        return TurnResult(text, text, Reply("", 0, 0, 0, "echo", "none"))

    monkeypatch.setattr(media_module, "run_turn", turn)
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    session = MediaSession(
        send,
        transcriber,
        speaker,
        EchoBrain(),
        NoHooks(),
        "sys",
        "CA1",
        SID,
        greeting=None,
        grace_ms=(50, 60),
        store=store,
    )

    async def script():
        transcriber.hear("Book Thursday.", is_partial=False)
        await settle(lambda: session._thinking)
        transcriber.hear("at nine", is_partial=True)
        await asyncio.sleep(0.02)
        transcriber.hear("at nine thirty.", is_partial=False)
        gate.set()
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert session.superseded == 1 and calls["n"] == 2
    assert undone == ["second", "first"]  # the broken reversal in between was logged and passed over
    assert "undo failed for CA1" in caplog.text and "ledger busy" in caplog.text
    assert len(session.ctx.data["undo"]) == 1  # the spoken turn's reversal waits for the loop to clear it
    # The dropped turn's spans stay, so a span says it was never heard and its effects were taken back.
    [dropped] = [span for span in store.spans("CA1") if (span.kind, span.name) == ("hook", "superseded")]
    assert dropped.meta == {"undone": 3} and "not spoken" in (dropped.text or "")


def test_the_length_line_names_five_minutes_only_when_the_cap_is_five_minutes() -> None:
    from candidate_line.persona import LENGTH_LINE, length_line

    assert LENGTH_LINE == "We're at the five-minute mark, so I'll let you go. Call back any time. Goodbye."
    assert length_line(300) == LENGTH_LINE
    assert length_line(120) == "We're at the time limit, so I'll let you go. Call back any time. Goodbye."
    assert length_line(0.3) == length_line(120)


def test_the_call_length_cap_comes_from_settings_and_refuses_nonsense() -> None:
    assert Settings.from_env({}).max_call_seconds == 300
    assert Settings.from_env({"MAX_CALL_SECONDS": ""}).max_call_seconds == 300
    assert Settings.from_env({"MAX_CALL_SECONDS": "120"}).max_call_seconds == 120
    for bad in ("0", "-5", "five", "2.5"):
        with pytest.raises(ValueError, match="MAX_CALL_SECONDS"):
            Settings.from_env({"MAX_CALL_SECONDS": bad})


def test_the_phone_hands_the_call_length_cap_to_each_session(monkeypatch) -> None:
    from candidate_line.telephony import app as app_module

    seen: list[float] = []

    class Recorder:
        def __init__(self, *args, max_call_seconds: float, **kwargs) -> None:
            seen.append(max_call_seconds)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    deps = Deps(transcriber=lambda: None, speaker=lambda: None, brain=EchoBrain, hooks=NoHooks)
    settings = Settings.from_env(
        {"MAX_CALL_SECONDS": "90", "TRACE_STORE_PATH": ":memory:", "ALLOW_UNSIGNED_WEBHOOKS": "1"}
    )
    with TestClient(create_app(settings, deps)).websocket_connect("/media") as ws:
        ws.send_json({"event": "start", "streamSid": SID, "start": {"callSid": "CA5"}})
    assert seen == [90]


TIME_LIMIT_SAID = ["We're at the time limit, so I'll let you go.", "Call back any time.", "Goodbye."]


def capped_session(
    transcriber: ScriptedTranscriber,
    speaker: FakeSpeaker,
    brain,
    sent: list[dict],
    store: TraceStore,
    greeting: str | None = GREETING,
) -> MediaSession:
    async def send(message: dict) -> None:
        sent.append(message)

    return MediaSession(
        send,
        transcriber,
        speaker,
        brain,
        NoHooks(),
        "sys",
        "CA1",
        SID,
        greeting=greeting,
        grace_ms=(50, 60),
        store=store,
        silence_after_s=30.0,  # no holding line inside these tests
        max_call_seconds=0.3,
    )


async def marks_then_frames(session: MediaSession, sent: list[dict], counted: dict[str, int]):
    """Hands back every mark once the hang-up is asked for, then sends frames as the stream would. The session
    must stop reading them once the closing line has played."""
    await settle(lambda: session._hang_up.is_set())
    for m in [m for m in sent if m["event"] == "mark"]:
        yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
    for _ in range(50):
        yield frame()
        counted["n"] += 1
        await asyncio.sleep(0.01)


def length_cap_spans(store: TraceStore) -> list:
    return [s for s in store.spans("CA1") if (s.kind, s.name) == ("hook", "length-cap")]


def test_the_length_cap_waits_for_a_turn_in_progress_and_follows_its_reply() -> None:
    transcriber, speaker, brain = ScriptedTranscriber(), FakeSpeaker(), GatedEcho()
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []
    counted = {"n": 0}
    session = capped_session(transcriber, speaker, brain, sent, store)

    async def script():
        await quiet(session, sent, transcriber)
        transcriber.hear("Book me Thursday.", is_partial=False)
        await settle(lambda: session._thinking)
        # The cap passes while the reply is being made; nothing may be said over it.
        await settle(lambda: time.monotonic() - session.ctx.started_at > 0.45)
        assert speaker.said == [GREETING] and not length_cap_spans(store)
        brain.gate.set()
        async for message in marks_then_frames(session, sent, counted):
            yield message

    asyncio.run(session.run(script()))
    assert speaker.said == [GREETING, "Book me Thursday.", *TIME_LIMIT_SAID]
    assert "clear" not in [m["event"] for m in sent] and counted["n"] < 50
    [span] = length_cap_spans(store)
    assert span.seconds is not None and span.seconds >= 0.3 and span.meta == {"max_call_seconds": 0.3}
    assert not [s for s in store.spans("CA1") if s.kind == "kill"]  # the line is open; only this call ended
    # The call-end hook reads this to write up a screen the cap left unfinished (spec section 7).
    assert session.ctx.data["length_capped"] is True


def test_the_silence_watcher_ends_a_quiet_call_at_the_cap_once_gus_has_finished() -> None:
    gate = threading.Event()
    calls = {"n": 0}

    def delay() -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # the greeting's second sentence is still being made when the cap passes
            gate.wait(0.5)

    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker(delay=delay)
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []
    counted = {"n": 0}
    session = capped_session(
        transcriber, speaker, EchoBrain(), sent, store, greeting="First sentence. Second sentence."
    )

    async def script():
        await settle(lambda: sum(m["event"] == "mark" for m in sent) == 2, seconds=3.0)
        assert speaker.said == ["First sentence.", "Second sentence."]  # the greeting was never cut
        assert not length_cap_spans(store)  # Twilio is still playing it
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        async for message in marks_then_frames(session, sent, counted):
            yield message

    asyncio.run(session.run(script()))
    assert speaker.said == ["First sentence.", "Second sentence.", *TIME_LIMIT_SAID]
    assert "clear" not in [m["event"] for m in sent] and counted["n"] < 50
    assert len(length_cap_spans(store)) == 1 and session.turns == 0


def test_the_length_cap_never_cuts_in_while_the_caller_is_mid_sentence() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []
    counted = {"n": 0}
    session = capped_session(transcriber, speaker, EchoBrain(), sent, store)

    async def script():
        await quiet(session, sent, transcriber)
        # Partials with no final yet, on past the cap and over two of the watcher's ticks.
        while time.monotonic() - session.ctx.started_at < 0.8:
            transcriber.hear("I wanted to ask", is_partial=True)
            await asyncio.sleep(0.08)
        assert speaker.said == [GREETING]
        transcriber.hear("I wanted to ask about Thursday.", is_partial=False)
        async for message in marks_then_frames(session, sent, counted):
            yield message

    asyncio.run(session.run(script()))
    assert speaker.said == [GREETING, "I wanted to ask about Thursday.", *TIME_LIMIT_SAID]
    assert len(length_cap_spans(store)) == 1 and session.barge_ins == 0


def test_a_caller_who_talks_over_the_reply_at_the_cap_still_hears_the_goodbye_whole() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    sent: list[dict] = []
    counted = {"n": 0}
    session = capped_session(transcriber, speaker, EchoBrain(), sent, store)

    async def script():
        await quiet(session, sent, transcriber)
        await settle(lambda: time.monotonic() - session.ctx.started_at > 0.35)
        transcriber.hear("Which day is open?", is_partial=False)
        await settle(lambda: session._hang_up.is_set())
        transcriber.hear("Wait, one more", is_partial=True)
        transcriber.hear("Wait, one more thing.", is_partial=False)
        await asyncio.sleep(0.3)  # past the grace: the words must not become a turn
        # Twilio is still playing: the frames are read and the call goes on until the marks come back.
        for _ in range(5):
            yield frame()
            counted["n"] += 1
            await asyncio.sleep(0.01)
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        for _ in range(50):
            yield frame()
            counted["n"] += 1
            await asyncio.sleep(0.01)

    asyncio.run(session.run(script()))
    assert "clear" not in [m["event"] for m in sent] and session.barge_ins == 0
    assert speaker.said[-3:] == TIME_LIMIT_SAID
    assert session.turns == 1 and 5 <= counted["n"] < 50
    assert len(length_cap_spans(store)) == 1


# The outbound media session (spec 9.6 and 9.7, DR-025 sections 12 and 14; fixes 1, 2 and 5).

# The fake speaker hears one sentence at a time, so the PIN ask is counted by its sentences.
PIN_ASK_SAID = split_sentences(PIN_ASK)
SEED = {"code": "ACME-1234", "first_name": "Lerato", "dial_id": "D-0123456789ab", "attempt": 1}


class CountingBrain(EchoBrain):
    """Echoes, and counts every model call, so a test can say none was made."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def reply(self, system, messages, max_tokens=200, tools=()):
        self.calls.append(next((m.text for m in reversed(messages) if m.role == "user"), ""))
        return super().reply(system, messages, max_tokens, tools)


async def all_said(session, sent) -> None:
    """Hands back every mark until the PIN ask, two sentences, has played whole."""
    await settle(lambda: sum(m["event"] == "mark" for m in sent) >= len(PIN_ASK_SAID))
    for m in [m for m in sent if m["event"] == "mark"]:
        session._on_mark(m["mark"]["name"])
    await settle(lambda: not session.speaking)


def outbound_session(transcriber, speaker, brain, sent, store=None, on_end=None, tools=(), hooks=None):
    async def send(message: dict) -> None:
        sent.append(message)

    return MediaSession(
        send,
        transcriber,
        speaker,
        brain,
        hooks if hooks is not None else NoHooks(),
        "sys",
        "CA1",
        SID,
        greeting=PIN_ASK,
        grace_ms=(50, 60),
        store=store,
        silence_after_s=30.0,
        max_call_seconds=480,
        tools=tools,
        outbound=SEED,
        on_end=on_end,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Hello?",
        "hi",
        "Hey.",
        "Yes.",
        "Yeah, speaking.",
        "This is she.",
        "this is he",
        "Lerato?",
        "Hello, this is Lerato.",
        "um, hello",
    ],
)
def test_hello_words_and_the_first_name_are_hello(text: str) -> None:
    assert is_hello(text, "Lerato")


@pytest.mark.parametrize(
    "text",
    ["four three nine eight", "Hello, my PIN is 4398", "stop", "wrong number", "um", "", "Who is this?"],
)
def test_anything_else_is_not_hello(text: str) -> None:
    assert not is_hello(text, "Lerato")


def test_an_outbound_session_opens_with_the_pin_ask_and_seeds_the_call_from_its_record() -> None:
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    session = outbound_session(transcriber, speaker, CountingBrain(), sent)

    async def script():
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert speaker.said[: len(PIN_ASK_SAID)] == PIN_ASK_SAID
    assert session.ctx.data["outbound"] == SEED


def test_hello_words_before_the_pin_never_barge_in_or_reach_the_model() -> None:
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    brain = CountingBrain()
    store = TraceStore(":memory:")
    store.start_call("CA1", "outbound")
    session = outbound_session(transcriber, speaker, brain, sent, store=store)

    async def script():
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        assert session.speaking
        transcriber.hear("Hello?", is_partial=True)  # over the PIN ask
        await asyncio.sleep(0.05)
        assert "clear" not in [m["event"] for m in sent] and session.barge_ins == 0
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        for n in range(1, 4):
            transcriber.hear("Hello?", is_partial=False)
            await asyncio.sleep(0.2)
        await settle(lambda: speaker.said.count(PIN_ASK_SAID[0]) == 3)
        await asyncio.sleep(0.2)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert brain.calls == []  # not one hello reached the model
    assert session.turns == 0 and session.ctx.history == []
    assert speaker.said == PIN_ASK_SAID * 3  # the greeting, then twice by code, and no more
    assert session.ctx.data["hello_asks"] == 2
    hellos = [s for s in store.spans("CA1") if (s.kind, s.name) == ("hook", "hello")]
    assert [h.meta["hello_asks"] for h in hellos] == [1, 2, 2]


def test_words_that_are_not_hello_barge_in_and_reach_the_model() -> None:
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    brain = CountingBrain()
    session = outbound_session(transcriber, speaker, brain, sent)

    async def script():
        await settle(lambda: any(m["event"] == "mark" for m in sent))
        transcriber.hear("four three", is_partial=True)
        await settle(lambda: "clear" in [m["event"] for m in sent])
        transcriber.hear("four three nine eight", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert session.barge_ins == 1 and brain.calls == ["four three nine eight"]


def test_after_the_pin_matches_hello_is_a_word_like_any_other() -> None:
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    brain = CountingBrain()
    session = outbound_session(transcriber, speaker, brain, sent)
    session.ctx.data["candidate"] = "ACME-1234"  # confirm_applicant matched

    async def script():
        await all_said(session, sent)
        transcriber.hear("Yes.", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert brain.calls == ["Yes."]


def test_after_the_second_pin_miss_yes_reaches_the_model_as_the_answer_to_the_callback_offer() -> None:
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    brain = CountingBrain()
    session = outbound_session(transcriber, speaker, brain, sent)
    session.ctx.data["verify_failures"] = 2  # PIN_SECOND_MISS_LINE asked "Would you like that?"

    async def script():
        await all_said(session, sent)
        transcriber.hear("Yes.", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert brain.calls == ["Yes."]


def test_with_the_kill_switch_set_a_hello_before_the_pin_hears_the_kill_line_and_the_call_ends() -> None:
    """F5 and F10: a hello before the PIN went straight to the PIN ask and never reached on_turn, where the kill
    switch is read, so a killed line asked for a PIN instead of closing (spec 7)."""
    from candidate_line import hooks
    from candidate_line.hooks import default_hooks
    from candidate_line.persona import KILL_LINE

    hooks.KILL_SWITCH.touch()
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    brain = CountingBrain()
    session = outbound_session(transcriber, speaker, brain, sent, hooks=default_hooks())
    kill_said = split_sentences(KILL_LINE)

    async def script():
        await all_said(session, sent)
        transcriber.hear("Hello?", is_partial=False)
        await settle(lambda: speaker.said[-len(kill_said) :] == kill_said)
        for m in [m for m in sent if m["event"] == "mark"]:
            yield {"event": "mark", "streamSid": SID, "mark": {"name": m["mark"]["name"]}}
        await settle(lambda: not session.speaking)
        yield frame()  # the loop ends at the next message once the kill line has played

    asyncio.run(session.run(script()))
    assert brain.calls == []  # the kill line is said by code
    assert speaker.said == PIN_ASK_SAID + kill_said  # the greeting once, never the PIN ask again
    assert session._hang_up.is_set()


def test_an_inbound_session_hears_hello_as_a_turn() -> None:
    transcriber, speaker = ScriptedTranscriber(), FakeSpeaker()

    async def script(session, sent):
        await quiet(session, sent, transcriber)
        transcriber.hear("Hello?", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    run_session(transcriber, speaker, script)
    assert speaker.said == [GREETING, "Hello?"]


def test_the_outbound_tools_reach_the_turn(monkeypatch) -> None:
    from candidate_line.brain import Reply, ToolSpec
    from candidate_line.telephony import media as media_module
    from candidate_line.turn import TurnResult

    seen: list[object] = []

    def turn(brain, hooks, ctx, text, max_tokens=None, tools=None):
        seen.append(tools)
        return TurnResult(text, "", Reply("", 0, 0, 0, "echo", "none"))

    monkeypatch.setattr(media_module, "run_turn", turn)
    spec = ToolSpec("confirm_applicant", "x", {"type": "object"})
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []
    session = outbound_session(transcriber, speaker, CountingBrain(), sent, tools=(spec,))

    async def script():
        await all_said(session, sent)
        transcriber.hear("four three nine eight", is_partial=False)
        await settle(lambda: session.turns == 1)
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert seen == [(spec,)]


def test_on_call_end_and_the_dials_outcome_run_off_the_event_loop() -> None:
    loop_thread: list[int] = []
    ran: list[tuple[str, int]] = []

    class Hooks(NoHooks):
        def on_call_end(self, ctx, outcome):
            ran.append(("on_call_end", threading.get_ident()))

    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []

    async def send(message: dict) -> None:
        sent.append(message)

    def on_end(ctx) -> None:
        ran.append(("outcome", threading.get_ident()))
        assert ctx.data["outbound"]["dial_id"] == SEED["dial_id"]

    session = MediaSession(
        send,
        transcriber,
        speaker,
        CountingBrain(),
        Hooks(),
        "sys",
        "CA1",
        SID,
        greeting=None,
        outbound=SEED,
        on_end=on_end,
    )

    async def script():
        loop_thread.append(threading.get_ident())
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert [name for name, _ in ran] == ["on_call_end", "outcome"]
    assert all(ident != loop_thread[0] for _, ident in ran)


def test_an_outcome_write_that_fails_never_breaks_the_hang_up(caplog) -> None:
    store = TraceStore(":memory:")
    store.start_call("CA1", "outbound")
    transcriber, speaker, sent = ScriptedTranscriber(), FakeSpeaker(), []

    def broken(ctx) -> None:
        raise OSError("state file locked")

    session = outbound_session(transcriber, speaker, CountingBrain(), sent, store=store, on_end=broken)

    async def script():
        yield {"event": "stop", "streamSid": SID}

    asyncio.run(session.run(script()))
    assert store.call("CA1").ended_at is not None
    assert "the dial's outcome write failed for CA1" in caplog.text


def test_an_outbound_call_ends_at_its_own_cap_with_the_time_limit_line() -> None:
    from candidate_line.persona import length_line

    assert length_line(480) == "We're at the time limit, so I'll let you go. Call back any time. Goodbye."


def test_the_phone_gives_an_outbound_stream_the_pin_ask_its_tools_its_cap_and_its_record(
    monkeypatch, tmp_path
) -> None:
    import re

    from candidate_line.brain import ToolSpec
    from candidate_line.outbound import number_hmac, number_key
    from candidate_line.outbound.contacts import Contacts
    from candidate_line.telephony import app as app_module
    from candidate_line.telephony.app import twilio_signature
    from tests.outbound_support import fictional, scratch_ledger

    built: list[dict] = []

    class Recorder:
        def __init__(self, *args, **kwargs) -> None:
            built.append(kwargs)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    ledger = scratch_ledger(tmp_path / "state.json", "test-signing-key")
    hashed = number_hmac(number_key("test-signing-key"), fictional(142))
    applicant = ledger.add_application(
        first_name="Ada",
        role="care-aide",
        zone="America/Chicago",
        pin="4721",
        consent={"version": "consent-2026-11-05", "accepted": True},
        number_hmac=hashed,
        number_masked="***-***-0142",
        nonce="n" * 22,
    )
    dial = ledger.schedule_dial(applicant.code, 1, datetime.now(UTC))
    ledger.update_dial(dial["dial_id"], status="placed")
    spec = ToolSpec("confirm_applicant", "x", {"type": "object"})
    deps = Deps(
        transcriber=lambda: None,
        speaker=lambda: None,
        brain=EchoBrain,
        hooks=NoHooks,
        ledger=lambda: ledger,
        contacts=Contacts(tmp_path / "c.json"),
        outbound_tools=(spec,),
    )  # type: ignore[arg-type]
    settings = Settings.from_env(
        {
            "TWILIO_AUTH_TOKEN": "12345",
            "PUBLIC_BASE_URL": "https://h.example",
            "TRACE_STORE_PATH": ":memory:",
            "OUTBOUND_ALLOWED_NUMBERS": fictional(142),
        }
    )
    client = TestClient(create_app(settings, deps))
    form = {"CallSid": "CA42", "Direction": "outbound-api", "To": fictional(142)}
    path = f"/voice?dial={dial['dial_id']}"
    twiml = client.post(
        path,
        data=form,
        headers={"X-Twilio-Signature": twilio_signature("12345", "https://h.example" + path, form)},
    ).text
    [token] = re.findall(r'<Parameter name="token" value="([^"]+)" />', twiml)

    def open_stream(call_sid: str, params: dict) -> None:
        with client.websocket_connect("/media") as ws:
            ws.send_json(
                {
                    "event": "start",
                    "streamSid": "MZ1",
                    "start": {"callSid": call_sid, "customParameters": params},
                }
            )
            if call_sid == "CA42":
                deadline = time.monotonic() + 2
                while not built and time.monotonic() < deadline:
                    time.sleep(0.01)

    # The client's own parameters never seed the call: only the dial record does.
    open_stream("CA42", {"token": token, "channel": "outbound", "code": "ACME-9999", "first_name": "Mallory"})
    [kwargs] = built
    assert kwargs["greeting"] == PIN_ASK
    assert kwargs["max_call_seconds"] == 480
    assert kwargs["tools"] == (spec,)
    assert kwargs["outbound"] == {
        "code": applicant.code,
        "first_name": "Ada",
        "dial_id": dial["dial_id"],
        "attempt": 1,
        "number_hmac": hashed,  # the HMAC, never the number, so a wrong person's stop holds for the number
    }
    assert callable(kwargs["on_end"])


def test_a_stream_that_says_outbound_with_no_dial_record_is_refused(monkeypatch) -> None:
    from candidate_line.telephony import app as app_module

    built: list[dict] = []

    class Recorder:
        def __init__(self, *args, **kwargs) -> None:
            built.append(kwargs)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    ledger = Ledger()
    deps = Deps(
        transcriber=lambda: None, speaker=lambda: None, brain=EchoBrain, hooks=NoHooks, ledger=lambda: ledger
    )  # type: ignore[arg-type]
    client = TestClient(
        create_app(Settings.from_env({"TRACE_STORE_PATH": ":memory:", "ALLOW_UNSIGNED_WEBHOOKS": "1"}), deps)
    )
    with client.websocket_connect("/media") as ws:
        ws.send_json(
            {
                "event": "start",
                "streamSid": "MZ1",
                "start": {"callSid": "CA1", "customParameters": {"channel": "outbound"}},
            }
        )
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1008 and built == []
