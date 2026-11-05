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


# The answer mode (card 08, lane B): the probe applies for its own number and answers the line's call. The live
# run needs James watching; these tests hold its parts with fakes.
import json

import pytest
import yaml
from fastapi.testclient import TestClient

from candidate_line.outbound.intake import ROLES_PATH, ApplicationIn, intake_signature
from candidate_line.probe.dial import (
    MET_PHRASE,
    NOT_MET_PHRASE,
    AnswerCall,
    answer_cases,
    application_body,
    finish_recording,
    post_application,
    probe_app,
    voice_url_pointed_at,
)
from candidate_line.telephony.app import twilio_signature
from candidate_line.telephony.twilio_rest import TwilioError

ROLES = {r["id"]: r for r in yaml.safe_load(ROLES_PATH.read_text())["roles"]}


def fictional(n: int) -> str:
    return f"+1312555{n:04d}"


def meets(question: dict, answer: str) -> bool:
    """The closed rules, read again here so the probe's answers are checked by something other than the probe."""
    said = answer.rstrip(".").lower()
    rule = question["rule"]
    if question["kind"] == "yes_no":
        return said == rule["equals"]
    if question["kind"] == "choice":
        chosen = next(o["id"] for o in question["options"] if o["say"].lower() == said)
        return chosen in rule["one_of"]
    n = int(said)
    if "at_least" in rule:
        return n >= rule["at_least"]
    if "at_most" in rule:
        return n <= rule["at_most"]
    low, high = rule["between"]
    return low <= n <= high


@pytest.mark.parametrize("role_id", sorted(ROLES))
def test_the_probe_plays_a_met_case_and_a_not_met_case_for_every_role(role_id: str) -> None:
    role = ROLES[role_id]
    met, not_met = answer_cases(role, pins=("4721", "0963"))
    for case in (met, not_met):
        assert case.lines[0] == "Hello?"  # one short hello first
        assert len(case.lines) == len(role["questions"]) + 3
    assert met.lines[1] == "four seven two one." and not_met.lines[1] == "zero nine six three."
    answers_met, answers_not = met.lines[2:-1], not_met.lines[2:-1]
    assert all(meets(q, a) for q, a in zip(role["questions"], answers_met, strict=True))
    verdicts = [meets(q, a) for q, a in zip(role["questions"], answers_not, strict=True)]
    assert verdicts == [False] + [True] * (len(verdicts) - 1)  # exactly one posted requirement not met
    assert (met.expect, not_met.expect) == (MET_PHRASE, NOT_MET_PHRASE)


def test_the_pins_are_random_four_digit_strings() -> None:
    cases = answer_cases(ROLES["care-aide"])
    assert all(len(c.pin) == 4 and c.pin.isdigit() for c in cases)


def test_the_application_fits_intakes_schema_and_names_no_person() -> None:
    raw = application_body("care-aide", fictional(150), "America/Chicago", "4721")
    parsed = ApplicationIn.model_validate_json(raw)
    assert parsed.phone == fictional(150) and parsed.pin == "4721" and parsed.first_name == "Probe"
    assert parsed.consent.accepted is True and parsed.consent.source == "operator"


def test_the_application_is_posted_signed_with_a_fresh_nonce() -> None:
    sent: list = []

    def opener(request, timeout):
        sent.append(request)
        return json.dumps({"code": "ACME-1234", "status": "scheduled"}).encode()

    raw = application_body("care-aide", fictional(150), "America/Chicago", "4721")
    answer = post_application("https://line.example/", "test-key", raw, opener=opener)
    assert answer == {"code": "ACME-1234", "status": "scheduled"}
    [request] = sent
    assert request.full_url == "https://line.example/applications" and request.data == raw
    headers = {k.lower(): v for k, v in request.header_items()}
    expected = intake_signature("test-key", headers["x-intake-timestamp"], headers["x-intake-nonce"], raw)
    assert headers["x-intake-signature"] == expected and len(headers["x-intake-nonce"]) >= 22


class FakeTwilio:
    def __init__(self, ready: bool = True, download_fails: bool = False) -> None:
        self.events: list[tuple] = []
        self.ready, self.download_fails = ready, download_fails

    def incoming_number(self, number):
        self.events.append(("read", number))
        return {"sid": "PN1", "voice_url": "https://old.example/voice", "voice_method": "GET"}

    def set_voice_url(self, sid, url, method="POST"):
        self.events.append(("set", sid, url, method))

    def recording_ready(self, sid):
        return self.ready

    def download_recording(self, sid, to):
        if self.download_fails:
            raise TwilioError(500, None, "download failed")
        to.write_bytes(b"")

    def delete_recording(self, sid):
        self.events.append(("delete", sid))


def test_the_probes_number_is_pointed_at_the_probe_and_put_back_even_when_the_run_fails() -> None:
    twilio = FakeTwilio()
    with (
        pytest.raises(RuntimeError),
        voice_url_pointed_at(twilio, fictional(150), "https://probe.example/probe-voice"),
    ):  # type: ignore[arg-type]
        raise RuntimeError("the call never came")
    assert twilio.events == [
        ("read", fictional(150)),
        ("set", "PN1", "https://probe.example/probe-voice", "POST"),
        ("set", "PN1", "https://old.example/voice", "GET"),
    ]


@pytest.mark.parametrize("twilio", [FakeTwilio(), FakeTwilio(download_fails=True)], ids=["read", "failed"])
def test_the_recording_is_deleted_from_twilio_whether_or_not_it_was_read(
    tmp_path, twilio, monkeypatch
) -> None:
    from candidate_line.probe import dial

    monkeypatch.setattr(dial, "gaps_from_recording", lambda wav: ([], "read"))
    if twilio.download_fails:
        with pytest.raises(TwilioError):
            finish_recording(twilio, "RE1", tmp_path / "r.wav")  # type: ignore[arg-type]
    else:
        assert finish_recording(twilio, "RE1", tmp_path / "r.wav") == ([], "read")  # type: ignore[arg-type]
    assert ("delete", "RE1") in twilio.events


def test_the_probes_voice_webhook_answers_only_the_lines_call_with_its_stream() -> None:
    call = AnswerCall()
    app = probe_app("12345", "https://probe.example", fictional(100), lambda send: None, call)  # type: ignore[arg-type,return-value]
    client = TestClient(app)

    def post(form):
        sig = twilio_signature("12345", "https://probe.example/probe-voice", form)
        return client.post("/probe-voice", data=form, headers={"X-Twilio-Signature": sig})

    assert client.post("/probe-voice", data={"CallSid": "CA1"}).status_code == 403
    stranger = post({"CallSid": "CA0", "From": fictional(199), "To": fictional(150)})
    assert stranger.text == "<Response><Hangup/></Response>" and call.call_sid is None
    answer = post({"CallSid": "CA1", "From": fictional(100), "To": fictional(150)})
    assert (
        answer.text
        == '<Response><Connect><Stream url="wss://probe.example/probe-media" /></Connect></Response>'
    )
    assert call.call_sid == "CA1"
    again = post({"CallSid": "CA2", "From": fictional(100), "To": fictional(150)})
    assert "<Hangup/>" in again.text  # one call per case


def test_the_answer_mode_refuses_to_run_unwatched(capsys) -> None:
    from candidate_line.probe.dial import main

    assert main(["--answer", "--public-url", "https://probe.example"]) == 2
    assert "--watched" in capsys.readouterr().out
