"""The standard-library Twilio client: the exact parameters each request carries, with a fake transport."""

import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from candidate_line.telephony.twilio_rest import TwilioError, TwilioRest, scrub_numbers


def fictional(n: int) -> str:
    return f"+1312555{n:04d}"


class Transport:
    """Records each request and answers with the next scripted body (or raises the next scripted error)."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else {}
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, bytes) else json.dumps(answer).encode()

    def form(self, i: int = -1) -> list[tuple[str, str]]:
        return urllib.parse.parse_qsl((self.requests[i].data or b"").decode(), keep_blank_values=True)


def client(transport: Transport) -> TwilioRest:
    return TwilioRest("ACtest", "token", opener=transport)


def test_the_dial_carries_exactly_the_parameters_of_dr025_section_12() -> None:
    t = Transport({"sid": "CA1"})
    sid = client(t).place_call(
        fictional(142),
        fictional(100),
        url="https://line.example/voice?dial=D-3f9a1c2b7e4d",
        status_callback="https://line.example/voice/status",
        amd_callback="https://line.example/voice/amd",
        timeout_s=30,
        time_limit_s=540,
    )
    assert sid == "CA1"
    request = t.requests[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Calls.json"
    assert request.headers["Authorization"].startswith("Basic ")
    assert t.form() == [
        ("To", fictional(142)),
        ("From", fictional(100)),
        ("Url", "https://line.example/voice?dial=D-3f9a1c2b7e4d"),
        ("StatusCallback", "https://line.example/voice/status"),
        ("StatusCallbackEvent", "answered"),
        ("StatusCallbackEvent", "completed"),
        ("MachineDetection", "DetectMessageEnd"),
        ("AsyncAmd", "true"),
        ("AsyncAmdStatusCallback", "https://line.example/voice/amd"),
        ("Timeout", "30"),
        ("TimeLimit", "540"),
    ]


def test_there_is_no_way_to_ask_for_synchronous_detection() -> None:
    import inspect

    params = inspect.signature(TwilioRest.place_call).parameters
    assert "machine_detection" not in params and "async_amd" not in params
    t = Transport({"sid": "CA2"})
    client(t).place_call(fictional(142), fictional(100), twiml="<Response/>")
    assert ("MachineDetection", "Enable") not in t.form()
    assert [k for k, _ in t.form()] == ["To", "From", "Twiml"]


def test_a_call_takes_a_url_or_twiml_but_not_both_or_neither() -> None:
    for kwargs in ({}, {"url": "https://x", "twiml": "<Response/>"}):
        with pytest.raises(ValueError):
            client(Transport()).place_call(fictional(142), fictional(100), **kwargs)


def test_update_hang_up_status_and_recordings_reach_their_resources() -> None:
    t = Transport({}, {}, {"status": "in-progress"}, {"sid": "RE1"}, {"status": "completed"}, b"RIFF", {})
    tw = client(t)
    tw.update_call("CA1", "<Response><Hangup/></Response>")
    tw.hang_up("CA1")
    assert tw.call_status("CA1") == "in-progress"
    assert tw.start_recording("CA1") == "RE1"
    assert tw.recording_ready("RE1") is True
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        tw.download_recording("RE1", Path(d) / "r.wav")
        assert (Path(d) / "r.wav").read_bytes() == b"RIFF"
    tw.delete_recording("RE1")
    base = "https://api.twilio.com/2010-04-01/Accounts/ACtest/"
    assert [(r.get_method(), r.full_url.removeprefix(base)) for r in t.requests] == [
        ("POST", "Calls/CA1.json"),
        ("POST", "Calls/CA1.json"),
        ("GET", "Calls/CA1.json"),
        ("POST", "Calls/CA1/Recordings.json"),
        ("GET", "Recordings/RE1.json"),
        ("GET", "Recordings/RE1.wav?RequestedChannels=2"),
        ("DELETE", "Recordings/RE1.json"),
    ]
    assert t.form(0) == [("Twiml", "<Response><Hangup/></Response>")]
    assert t.form(1) == [("Status", "completed")]
    assert t.form(3) == [("RecordingChannels", "dual")]


def test_the_probes_number_voice_url_is_read_and_set() -> None:
    row = {"sid": "PN1", "voice_url": "https://old.example/voice", "voice_method": "POST"}
    t = Transport({"incoming_phone_numbers": [row]}, {})
    tw = client(t)
    assert tw.incoming_number(fictional(150)) == {
        "sid": "PN1",
        "voice_url": "https://old.example/voice",
        "voice_method": "POST",
    }
    assert "PhoneNumber=" + urllib.parse.quote(fictional(150)) in t.requests[0].full_url
    tw.set_voice_url("PN1", "https://probe.example/probe-voice")
    assert t.form(1) == [("VoiceUrl", "https://probe.example/probe-voice"), ("VoiceMethod", "POST")]
    with pytest.raises(TwilioError):
        client(Transport({"incoming_phone_numbers": []})).incoming_number(fictional(150))


def test_a_refusal_is_a_twilio_error_with_every_number_masked() -> None:
    body = {"code": 21211, "message": f"The 'To' number {fictional(142)} is not a valid phone number."}
    refused = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(json.dumps(body).encode()))  # type: ignore[arg-type]
    with pytest.raises(TwilioError) as caught:
        client(Transport(refused)).place_call(fictional(142), fictional(100), url="https://x")
    assert caught.value.status == 400 and caught.value.code == 21211
    assert fictional(142) not in str(caught.value) and fictional(142)[-7:] not in str(caught.value)
    assert "***-***-0142" in str(caught.value)  # the masked form, as every log line carries a number


def test_a_network_failure_and_a_reply_without_a_sid_are_twilio_errors() -> None:
    with pytest.raises(TwilioError, match="could not be reached"):
        client(Transport(urllib.error.URLError("down"))).call_status("CA1")
    with pytest.raises(TwilioError, match="refused the call"):
        client(Transport({"message": "nope"})).place_call(fictional(142), fictional(100), url="https://x")


def test_scrub_numbers_masks_every_way_a_number_is_written_and_leaves_short_digits() -> None:
    n = fictional(142)
    area, exchange, line = n[2:5], n[5:8], n[8:]
    for written in (
        n,
        n[2:],
        f"({area}) {exchange}-{line}",
        f"{area}-{exchange}-{line}",
        f"{area} {exchange} {line}",
    ):
        assert scrub_numbers(f"call {written} now") == f"call ***-***-{line} now"
    assert scrub_numbers("error 21211 at 9:30") == "error 21211 at 9:30"


def test_the_client_repr_holds_no_account_id() -> None:
    assert "ACtest" not in repr(client(Transport()))
