"""The probe on Twilio's far end (dial mode, DR-011) and the recording method (DR-001)."""

import asyncio
import audioop
import math
import struct
import wave

from candidate_line.probe.recording import gaps_from_recording, speech_segments, turn_gaps
from candidate_line.probe.session import ProbeSession, has_speech
from candidate_line.telephony.audio import MULAW_FRAME_BYTES, encode_twilio_payload, pcm16_to_mulaw
from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber


def tone(ms: int, rate: int = 8000, amplitude: int = 8000) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n)
    )


def quiet(ms: int, rate: int = 8000) -> bytes:
    return b"\x00\x00" * (rate * ms // 1000)


def test_energy_gate_separates_silence_from_speech() -> None:
    assert not has_speech(b"\xff" * MULAW_FRAME_BYTES)
    assert has_speech(pcm16_to_mulaw(tone(20)))


def test_twilio_side_probe_sends_no_start_or_stop_and_measures_a_gap_past_the_silence() -> None:
    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    ears, mouth = ScriptedTranscriber(), FakeSpeaker()
    probe = ProbeSession(
        send, ears, mouth, ["Hello Gus."], silence_ms=40, reply_timeout_s=3, real_time=False, twilio_side=True
    )

    async def twilio():
        yield {"event": "connected"}
        yield {"event": "start", "streamSid": "MZ123", "start": {"callSid": "CA1"}}
        # The greeting: speech frames, then silence frames like a real line between words.
        for _ in range(10):
            yield {"event": "media", "media": {"payload": encode_twilio_payload(pcm16_to_mulaw(tone(20)))}}
        ears.hear("Hello, this is Gus.", is_partial=False)
        for _ in range(8):
            await asyncio.sleep(0.01)
            yield {"event": "media", "media": {"payload": encode_twilio_payload(b"\xff" * MULAW_FRAME_BYTES)}}
        # Wait for the probe to speak its line, then silence frames (no gap yet), then Gus's answer.
        while not any(m["event"] == "mark" for m in sent):
            await asyncio.sleep(0.01)
            yield {"event": "media", "media": {"payload": encode_twilio_payload(b"\xff" * MULAW_FRAME_BYTES)}}
        yield {"event": "mark", "mark": {"name": "probe-1"}}
        await asyncio.sleep(0.05)
        for _ in range(10):
            yield {"event": "media", "media": {"payload": encode_twilio_payload(pcm16_to_mulaw(tone(20)))}}
        ears.hear("Hi there.", is_partial=False)
        for _ in range(10):
            await asyncio.sleep(0.01)
            yield {"event": "media", "media": {"payload": encode_twilio_payload(b"\xff" * MULAW_FRAME_BYTES)}}
        yield {"event": "stop"}

    transcript = asyncio.run(asyncio.wait_for(probe.run(twilio()), 5))
    events = [m["event"] for m in sent]
    assert "start" not in events and "stop" not in events and "connected" not in events
    assert probe.stream_sid == "MZ123"
    assert all(m.get("streamSid") == "MZ123" for m in sent if m["event"] in ("media", "mark"))
    gus = [e for e in transcript.exchanges if e.who == "gus"]
    assert [e.text for e in gus] == ["Hello, this is Gus.", "Hi there."]
    assert (
        gus[1].gap_ms is not None and gus[1].gap_ms >= 40
    )  # measured from the probe's last frame, past the silence


def test_recording_gaps_come_from_the_two_channels(tmp_path) -> None:
    rate = 8000
    # Line (channel 1): greeting at 0.0 to 0.5 s, answer at 2.3 to 2.8 s. Caller (channel 2): speaks 1.0 to 1.6 s.
    line = tone(500) + quiet(1800) + tone(500) + quiet(200)
    caller = quiet(1000) + tone(600) + quiet(1400)
    assert len(line) == len(caller)
    stereo = audioop.add(audioop.tostereo(line, 2, 1, 0), audioop.tostereo(caller, 2, 0, 1), 2)
    path = tmp_path / "call.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(stereo)
    gaps, note = gaps_from_recording(path)
    assert "channel 1 is the line" in note
    assert len(gaps) == 1 and gaps[0].turn == 1
    assert 650 <= gaps[0].gap_ms <= 750  # 1.6 s to 2.3 s, within one frame plus the hangover rounding


def test_turn_gaps_skip_an_unanswered_caller_segment() -> None:
    from candidate_line.probe.recording import Segment

    caller = [Segment(1.0, 1.5), Segment(2.0, 2.4), Segment(5.0, 5.5)]
    line = [Segment(0.0, 0.4), Segment(2.9, 3.4), Segment(6.1, 6.5)]
    gaps = turn_gaps(caller, line)
    assert [(g.turn, g.gap_ms) for g in gaps] == [(2, 500), (3, 600)]
    assert speech_segments(quiet(200), 8000) == []
