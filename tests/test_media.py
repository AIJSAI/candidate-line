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
from candidate_line.telephony.media import MediaSession
from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber

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
    transcriber: ScriptedTranscriber, speaker: FakeSpeaker, script, greeting=GREETING
) -> tuple[list[dict], MediaSession]:
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    session = MediaSession(
        send, transcriber, speaker, EchoBrain(), NoHooks(), "sys", "CA1", SID, greeting=greeting
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
            Settings.from_env({"ALLOW_UNSIGNED_WEBHOOKS": "1", "PUBLIC_BASE_URL": "https://h.example"})
        )
    )
    assert "<Connect><Stream" in streaming.post("/voice", data={"CallSid": "CA1"}).text
    no_host = TestClient(create_app(Settings.from_env({"ALLOW_UNSIGNED_WEBHOOKS": "1"})))
    assert no_host.post("/voice", data={"CallSid": "CA1"}).status_code == 503
    saying = TestClient(create_app(Settings.from_env({"ALLOW_UNSIGNED_WEBHOOKS": "1", "VOICE_MODE": "say"})))
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
    client = TestClient(create_app(Settings.from_env({"BRAIN_PROVIDER": "echo"}), deps))
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
