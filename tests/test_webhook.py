import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from candidate_line.hooks import default_hooks
from candidate_line.settings import Settings
from candidate_line.telephony.app import (
    HELLO_LINE,
    STREAM_TOKEN_TTL_S,
    Deps,
    create_app,
    stream_token,
    stream_token_ok,
    twilio_signature,
    twiml_closed,
)
from candidate_line.tools.ledger import Ledger
from candidate_line.traces.store import TraceStore

# Twilio's documented example (security page, read 2026-11-01): auth token 12345, this URL and these fields.
DOC_URL = "https://example.com/myapp.php?foo=1&bar=2"
DOC_FORM = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675310",
    "Digits": "1234",
    "From": "+14158675310",
    "To": "+18005551212",
}
DOC_SIGNATURE = "L/OH5YylLD5NRKLltdqwSvS0BnU="


def client(**env: str) -> TestClient:
    # An in-memory store, so make test never writes a call into the room's var/traces.sqlite (the dry run of card 07).
    return TestClient(create_app(Settings.from_env({"TRACE_STORE_PATH": ":memory:", **env})))


def test_signature_matches_twilios_documented_example() -> None:
    assert twilio_signature("12345", DOC_URL, DOC_FORM) == DOC_SIGNATURE


def test_health_names_the_brain() -> None:
    assert client(BRAIN_PROVIDER="echo").get("/health").json() == {"status": "ok", "brain": "echo"}


def test_voice_fails_closed_without_a_token() -> None:
    assert client().post("/voice", data={"CallSid": "CA1"}).status_code == 503


def test_voice_answers_twiml_when_unsigned_is_allowed_locally() -> None:
    response = client(ALLOW_UNSIGNED_WEBHOOKS="1", VOICE_MODE="say").post("/voice", data={"CallSid": "CA1"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert "<Say" in response.text and "This is Gus." in response.text


def test_voice_accepts_a_correct_signature_on_the_public_url() -> None:
    c = client(TWILIO_AUTH_TOKEN="12345", PUBLIC_BASE_URL="https://example.com")
    response = c.post("/myapp.php?foo=1&bar=2", data=DOC_FORM, headers={"X-Twilio-Signature": DOC_SIGNATURE})
    assert response.status_code == 404  # the path is not ours, but the signature check runs on /voice only
    good = twilio_signature("12345", "https://example.com/voice", DOC_FORM)
    assert c.post("/voice", data=DOC_FORM, headers={"X-Twilio-Signature": good}).status_code == 200


def test_voice_refuses_a_wrong_signature() -> None:
    c = client(TWILIO_AUTH_TOKEN="12345", PUBLIC_BASE_URL="https://example.com")
    assert c.post("/voice", data=DOC_FORM, headers={"X-Twilio-Signature": DOC_SIGNATURE}).status_code == 403
    assert c.post("/voice", data=DOC_FORM).status_code == 403
    assert HELLO_LINE not in c.post("/voice", data=DOC_FORM).text


def test_the_phone_drains_its_hand_off_queue_when_it_stops() -> None:
    class Drained:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def drain(self, timeout: float = 5.0) -> None:
            self.timeouts.append(timeout)

    queue = Drained()
    deps = Deps(
        transcriber=lambda: None,  # type: ignore[return-value]
        speaker=lambda: None,  # type: ignore[return-value]
        brain=lambda: None,  # type: ignore[return-value]
        hooks=default_hooks,
        escalations=queue,  # type: ignore[arg-type]
    )
    with TestClient(create_app(Settings.from_env({"TRACE_STORE_PATH": ":memory:"}), deps)):
        pass
    assert queue.timeouts == [5.0]


CLOSED_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Matthew-Neural">This is the ACME candidate '
    "line. The line is closed for the moment. Please try again later.</Say></Response>"
)
# 03:00 UTC on 5 November is 21:00 the evening before in Central time, so the day counted is 4 November.
LATE_EVENING = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


def capped_client(ledger: Ledger, store: TraceStore, **env: str) -> TestClient:
    """The phone app over a ledger and a store the test can read, with no ears, mouth or brain: /voice opens none."""
    deps = Deps(
        transcriber=lambda: None,  # type: ignore[return-value]
        speaker=lambda: None,  # type: ignore[return-value]
        brain=lambda: None,  # type: ignore[return-value]
        hooks=default_hooks,
        store=store,
        ledger=lambda: ledger,
    )
    settings = Settings.from_env(
        {
            "ALLOW_UNSIGNED_WEBHOOKS": "1",
            "PUBLIC_BASE_URL": "https://h.example",
            "TRACE_STORE_PATH": ":memory:",
        }
        | env
    )
    return TestClient(create_app(settings, deps))


def test_the_closed_line_twiml_is_the_fixed_line() -> None:
    assert twiml_closed() == CLOSED_TWIML


def test_the_daily_cap_answers_the_closed_line_past_the_cap_and_closes_the_row() -> None:
    ledger, store = Ledger(now=lambda: LATE_EVENING), TraceStore(":memory:")
    c = capped_client(ledger, store, MAX_CALLS_PER_DAY="2")
    answers = [
        c.post("/voice", data={"CallSid": f"CA{n}", "From": "+15555550100"}).text for n in (1, 2, 3, 4)
    ]
    assert all("<Connect><Stream" in a for a in answers[:2])
    assert answers[2:] == [CLOSED_TWIML, CLOSED_TWIML]
    assert ledger.calls_today() == 4 and ledger.today() == "2026-11-04"
    for sid in ("CA3", "CA4"):  # the row is started as any call's is, then closed with the cap as its outcome
        row = store.call(sid)
        assert row is not None and row.outcome == "closed: daily cap" and row.ended_at is not None
        assert row.caller_masked == "***-***-0100"
    assert store.call("CA2").outcome is None and store.call("CA2").ended_at is None  # still streaming


def test_a_forged_request_is_refused_before_it_is_counted() -> None:
    ledger, store = Ledger(now=lambda: LATE_EVENING), TraceStore(":memory:")
    c = capped_client(ledger, store, TWILIO_AUTH_TOKEN="12345", MAX_CALLS_PER_DAY="1")
    for _ in range(3):
        assert c.post("/voice", data=DOC_FORM, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    assert ledger.calls_today() == 0  # a flood of forgeries cannot close the line to a candidate
    good = twilio_signature("12345", "https://h.example/voice", DOC_FORM)
    assert "<Connect><Stream" in c.post("/voice", data=DOC_FORM, headers={"X-Twilio-Signature": good}).text


def test_say_mode_keeps_the_hello_line_and_counts_nothing() -> None:
    ledger, store = Ledger(now=lambda: LATE_EVENING), TraceStore(":memory:")
    c = capped_client(ledger, store, VOICE_MODE="say", MAX_CALLS_PER_DAY="1")
    for n in (1, 2):
        assert HELLO_LINE in c.post("/voice", data={"CallSid": f"CA{n}"}).text
    assert ledger.calls_today() == 0


def test_a_count_that_fails_lets_the_call_through(caplog: pytest.LogCaptureFixture) -> None:
    class Unsaved(Ledger):
        def count_call(self, day: str) -> int:
            raise OSError("disk full")

    c = capped_client(Unsaved(now=lambda: LATE_EVENING), TraceStore(":memory:"), MAX_CALLS_PER_DAY="1")
    assert "<Connect><Stream" in c.post("/voice", data={"CallSid": "CA1"}).text
    assert "the daily call count failed" in caplog.text


def test_the_daily_count_is_kept_per_central_day_in_the_state_file(tmp_path) -> None:
    path = tmp_path / "state.json"
    ledger = Ledger(state_path=path, now=lambda: LATE_EVENING)
    assert ledger.today() == "2026-11-04" and ledger.calls_today() == 0
    assert [ledger.count_call(ledger.today()) for _ in range(3)] == [1, 2, 3]
    assert ledger.count_call("2026-11-05") == 1
    # A restart reads the count back, so the cap holds across one.
    restarted = Ledger(state_path=path, now=lambda: LATE_EVENING)
    assert restarted.calls_today() == 3
    assert Ledger(state_path=path, now=lambda: datetime(2026, 11, 5, 15, 0, tzinfo=UTC)).calls_today() == 1
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["calls"] == {"2026-11-04": 3, "2026-11-05": 1}
    assert saved["bookings"] == {} and saved["callbacks"] == [] and saved["moves"] == []


def test_a_count_that_is_not_a_whole_number_reads_as_none(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"calls": {"2026-11-04": "lots", "2026-11-03": True, "2026-11-02": 4}}))
    ledger = Ledger(state_path=path, now=lambda: LATE_EVENING)
    assert ledger.calls_today() == 0 and ledger.count_call("2026-11-02") == 5


def test_the_daily_cap_comes_from_settings_and_refuses_nonsense() -> None:
    assert Settings.from_env({}).max_calls_per_day == 30
    assert Settings.from_env({"MAX_CALLS_PER_DAY": "5"}).max_calls_per_day == 5
    for bad in ("0", "-1", "thirty"):
        with pytest.raises(ValueError, match="MAX_CALLS_PER_DAY"):
            Settings.from_env({"MAX_CALLS_PER_DAY": bad})


def test_a_media_stream_opens_only_with_the_token_voice_minted_for_that_call(monkeypatch) -> None:
    import re

    from candidate_line.telephony import app as app_module

    opened: list[str] = []

    class Recorder:
        def __init__(self, *args, call_id: str, **kwargs) -> None:
            opened.append(call_id)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    ledger, store = Ledger(now=lambda: LATE_EVENING), TraceStore(":memory:")
    c = capped_client(ledger, store, TWILIO_AUTH_TOKEN="12345")
    form = {"CallSid": "CA9", "From": "+15555550100"}
    sig = twilio_signature("12345", "https://h.example/voice", form)
    twiml = c.post("/voice", data=form, headers={"X-Twilio-Signature": sig}).text
    [token] = re.findall(r'<Parameter name="token" value="([^"]+)" />', twiml)

    def open_stream(call_sid: str, params: object = None) -> None:
        meta: dict[str, object] = {"callSid": call_sid}
        if params is not None:
            meta["customParameters"] = params
        with c.websocket_connect("/media") as ws:
            ws.send_json({"event": "start", "streamSid": "MZ1", "start": meta})

    open_stream("CA9")  # no token: refused before any ears, mouth or brain is built
    open_stream("CA9", ["not", "a", "mapping"])
    open_stream("CA8", {"token": token})  # minted for another call
    assert opened == []
    open_stream("CA9", {"token": token})
    assert opened == ["CA9"]
    open_stream("CA9", {"token": token})  # one stream per token
    assert opened == ["CA9"]


def test_a_stream_token_is_bound_to_its_call_its_key_and_its_minute() -> None:
    token = stream_token("12345", "CA9", now=1000.0)
    assert stream_token_ok("12345", "CA9", token, now=1000.0 + STREAM_TOKEN_TTL_S)
    assert not stream_token_ok("12345", "CA9", token, now=1001.0 + STREAM_TOKEN_TTL_S)  # expired
    assert not stream_token_ok("12345", "CA8", token, now=1000.0)  # another call
    assert not stream_token_ok("54321", "CA9", token, now=1000.0)  # another key
    expires, _, mac = token.partition(".")
    assert not stream_token_ok(
        "12345", "CA9", f"{int(expires) + 600}.{mac}", now=1000.0
    )  # a longer life forged
    for junk in ("", ".", "abc.def", f"{expires}."):
        assert not stream_token_ok("12345", "CA9", junk, now=1000.0)


def test_a_line_with_no_auth_token_opens_no_stream_unless_unsigned_is_allowed(monkeypatch) -> None:
    from candidate_line.telephony import app as app_module

    opened: list[str] = []

    class Recorder:
        def __init__(self, *args, call_id: str, **kwargs) -> None:
            opened.append(call_id)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    deps = Deps(transcriber=lambda: None, speaker=lambda: None, brain=lambda: None, hooks=default_hooks)  # type: ignore[arg-type,return-value]
    start = {"event": "start", "streamSid": "MZ1", "start": {"callSid": "CA9"}}
    closed = TestClient(create_app(Settings.from_env({"TRACE_STORE_PATH": ":memory:"}), deps))
    with closed.websocket_connect("/media") as ws:  # as /voice answers 503, the stream fails closed
        ws.send_json(start)
    assert opened == []
    local = TestClient(
        create_app(Settings.from_env({"TRACE_STORE_PATH": ":memory:", "ALLOW_UNSIGNED_WEBHOOKS": "1"}), deps)
    )
    with local.websocket_connect("/media") as ws:
        ws.send_json(start)
    assert opened == ["CA9"]


def test_the_warm_up_opens_the_speech_clients_before_the_first_call() -> None:
    from fastapi.testclient import TestClient

    from candidate_line.brain import EchoBrain
    from candidate_line.hooks import NoHooks
    from candidate_line.settings import Settings
    from candidate_line.telephony.app import Deps, create_app
    from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber

    speaker, transcriber = FakeSpeaker(), ScriptedTranscriber()
    deps = Deps(
        transcriber=lambda: transcriber,
        speaker=lambda: speaker,
        brain=EchoBrain,
        hooks=NoHooks,
        warm_up=True,
    )
    app = create_app(Settings.from_env({"BRAIN_PROVIDER": "echo", "ALLOW_UNSIGNED_WEBHOOKS": "1"}), deps)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert speaker.said == ["Warming up."]
    assert transcriber.started and transcriber.stopped
