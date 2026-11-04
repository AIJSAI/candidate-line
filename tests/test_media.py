import asyncio
import base64
import threading
import time

from fastapi.testclient import TestClient

from candidate_line.brain import EchoBrain
from candidate_line.hooks import NoHooks
from candidate_line.persona import GREETING
from candidate_line.settings import Settings
from candidate_line.telephony.app import Deps, create_app, twiml_stream
from candidate_line.telephony.audio import MULAW_FRAME_BYTES, mulaw_to_pcm16, pcm16_to_mulaw, split_sentences
from candidate_line.telephony.media import RECOVERY_LINE, MediaSession
from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber
from candidate_line.traces.store import TraceStore

SID = "MZ123"


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
        create_app(Settings.from_env({"BRAIN_PROVIDER": "echo", "TRACE_STORE_PATH": ":memory:"}), deps)
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
        send, transcriber, speaker, RaisingBrain(), NoHooks(), "sys", "CA1", SID, greeting=GREETING, grace_ms=(50, 150)
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
