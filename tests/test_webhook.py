import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from candidate_line.hooks import default_hooks
from candidate_line.outbound import number_hmac, number_key
from candidate_line.outbound.contacts import Contacts
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
from candidate_line.tools.ledger import Ledger, LedgerError
from candidate_line.traces.store import TraceStore
from tests.outbound_support import application, everything, fictional, scratch_ledger

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


# The outbound /voice and its callbacks (DR-025 section 12; fixes 7, 8 and 13), on the real ledger over a scratch
# state file; numbers are fictional 555-01xx ones made at run time.
KEY = "test-signing-key"
TOKEN = "12345"
BASE = "https://line.example"
NOW = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)


class FakeTwilio:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str]] = []

    def update_call(self, call_sid: str, twiml: str) -> None:
        self.updates.append((call_sid, twiml))


class Outbound:
    """The phone app over the real ledger, holding the dials a test places, with Twilio's signature checked."""

    def __init__(self, tmp_path, **env: str) -> None:
        self.ledger = scratch_ledger(tmp_path / "state.json", KEY, lambda: NOW)
        self.store = TraceStore(":memory:")
        self.twilio = FakeTwilio()
        self.contacts = Contacts(tmp_path / "contacts.json")
        deps = Deps(
            transcriber=lambda: None,  # type: ignore[arg-type,return-value]
            speaker=lambda: None,  # type: ignore[arg-type,return-value]
            brain=lambda: None,  # type: ignore[arg-type,return-value]
            hooks=default_hooks,
            store=self.store,
            ledger=lambda: self.ledger,  # type: ignore[arg-type,return-value]
            contacts=self.contacts,
            twilio=self.twilio,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        settings = {
            "TWILIO_AUTH_TOKEN": TOKEN,
            "PUBLIC_BASE_URL": BASE,
            "TRACE_STORE_PATH": ":memory:",
            "INTAKE_SIGNING_KEY": KEY,
            "OUTBOUND_ALLOWED_NUMBERS": fictional(142),
            "TWILIO_LINE_NUMBER": fictional(100),
        } | env
        self.client = TestClient(create_app(Settings.from_env(settings), deps))

    def dial(self, first_name: str = "Ada", number: str = "", attempt: int = 1) -> tuple[str, str]:
        number = number or fictional(142)
        applicant = self.ledger.add_application(
            first_name=first_name,
            role="care-aide",
            zone="America/Chicago",
            pin="4721",
            consent={"version": "consent-2026-11-05", "accepted": True},
            number_hmac=number_hmac(number_key(KEY), number),
            number_masked="***-***-" + number[-4:],
            nonce="n" * 22,
        )
        dial = self.ledger.schedule_dial(applicant.code, attempt, NOW)
        self.ledger.update_dial(dial["dial_id"], status="placed", placed_at=NOW.isoformat())
        return applicant.code, dial["dial_id"]

    def post(self, path: str, form: dict[str, str], token: str = TOKEN):
        signature = twilio_signature(token, BASE + path, form)
        return self.client.post(path, data=form, headers={"X-Twilio-Signature": signature})


def outbound_form(sid: str = "CA77", to: str = "") -> dict[str, str]:
    return {"CallSid": sid, "Direction": "outbound-api", "From": fictional(100), "To": to or fictional(142)}


def test_an_outbound_call_with_no_dial_record_is_hung_up(tmp_path) -> None:
    line = Outbound(tmp_path)
    for path in ("/voice", "/voice?dial=D-000000000000", "/voice?dial=nonsense"):
        answer = line.post(path, outbound_form())
        assert answer.status_code == 200
        assert answer.text == '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    assert line.store.call("CA77") is None and line.ledger.calls_today() == 0


def test_an_outbound_call_found_by_the_signed_dial_id_is_bound_and_answered_with_the_opening(
    tmp_path,
) -> None:
    line = Outbound(tmp_path)
    _, dial_id = line.dial()
    answer = line.post(f"/voice?dial={dial_id}", outbound_form())
    assert answer.status_code == 200
    twiml = answer.text
    say = re.search(
        r'<Response><Say voice="Polly.Matthew-Neural">(.+?)</Say><Connect><Stream url="wss://line.example/media">',
        twiml,
    )
    assert say is not None, twiml  # the opening plays before the stream opens
    assert say.group(1).startswith(
        "Hello, this is ACME&apos;s automated hiring line, calling for Ada"
    ) or say.group(1).startswith("Hello, this is ACME's automated hiring line, calling for Ada")
    [token] = re.findall(r'<Parameter name="token" value="([^"]+)" />', twiml)
    assert stream_token_ok(TOKEN, "CA77", token)
    assert '<Parameter name="channel" value="outbound" />' in twiml
    assert line.ledger.dial(dial_id)["call_sid"] == "CA77"
    # Skips the inbound count, and the call row is the outbound channel with the applicant's masked number (fix 7).
    assert line.ledger.calls_today() == 0
    row = line.store.call("CA77")
    assert row is not None and row.channel == "outbound" and row.caller_masked == "***-***-0142"


def test_an_outbound_call_found_by_its_callsid_is_answered(tmp_path) -> None:
    line = Outbound(tmp_path)
    _, dial_id = line.dial()
    line.ledger.bind_call(dial_id, "CA77")
    assert "<Connect><Stream" in line.post("/voice", outbound_form()).text
    # Another call presenting the same dial id is refused: the dial is bound to CA77.
    other = line.post(f"/voice?dial={dial_id}", outbound_form(sid="CA78"))
    assert "<Hangup/>" in other.text


def test_an_outbound_voice_with_a_bad_signature_is_refused(tmp_path) -> None:
    line = Outbound(tmp_path)
    _, dial_id = line.dial()
    path = f"/voice?dial={dial_id}"
    # Signed over the URL without its query: the dial id is part of what Twilio signs.
    forged = twilio_signature(TOKEN, BASE + "/voice", outbound_form())
    assert (
        line.client.post(path, data=outbound_form(), headers={"X-Twilio-Signature": forged}).status_code
        == 403
    )
    assert line.post(path, outbound_form(), token="54321").status_code == 403
    assert line.ledger.dial(dial_id)["call_sid"] is None


def test_an_outbound_call_whose_to_is_not_on_the_allow_list_is_hung_up(tmp_path, caplog) -> None:
    line = Outbound(tmp_path, OUTBOUND_ALLOWED_NUMBERS=fictional(143))
    code, dial_id = line.dial()
    answer = line.post(f"/voice?dial={dial_id}", outbound_form())
    assert "<Hangup/>" in answer.text and "<Say" not in answer.text
    dial = line.ledger.dial(dial_id)
    assert (dial["status"], dial["outcome"]) == ("cancelled", "not_allowed")
    assert application(line.ledger, code)["not_dialled"] == "not_allowed"
    assert line.store.call("CA77").outcome == "hung up: not_allowed"
    assert all(fictional(142)[-7:] not in r.getMessage() for r in caplog.records)


def test_an_outbound_call_is_hung_up_by_the_kill_switch_or_an_opt_out_since_the_claim(tmp_path) -> None:
    from candidate_line import hooks

    line = Outbound(tmp_path)
    code, dial_id = line.dial()
    hooks.KILL_SWITCH.touch()
    try:
        assert "<Hangup/>" in line.post(f"/voice?dial={dial_id}", outbound_form()).text
    finally:
        hooks.KILL_SWITCH.unlink()
    assert line.ledger.dial(dial_id)["outcome"] == "kill"
    code, dial_id = line.dial()
    line.ledger.opt_out(code, how="said stop")
    assert "<Hangup/>" in line.post(f"/voice?dial={dial_id}", outbound_form(sid="CA79")).text
    assert line.ledger.dial(dial_id)["outcome"] == "opted_out"


def test_an_inbound_call_never_reads_the_dial_records(tmp_path) -> None:
    line = Outbound(tmp_path)
    form = {"CallSid": "CA80", "Direction": "inbound", "From": fictional(150), "To": fictional(100)}
    answer = line.post("/voice", form)
    assert "<Connect><Stream" in answer.text and "<Say" not in answer.text
    assert '<Parameter name="channel"' not in answer.text
    assert line.ledger.calls_today() == 1 and line.store.call("CA80").channel == "voice"


def test_a_call_in_gives_its_stream_only_the_from_numbers_hmac(tmp_path, monkeypatch) -> None:
    """Spec 9.12: the voicemail tells a person to call the line and say stop, so the stream of a call in carries the
    From number's HMAC, which the hooks look the applications up by; the number itself is kept nowhere."""
    from types import SimpleNamespace

    from candidate_line.telephony import app as app_module

    sessions: list[SimpleNamespace] = []

    class Recorder:
        def __init__(self, *args, call_id: str, **kwargs) -> None:
            self.ctx = SimpleNamespace(data={})
            sessions.append(self.ctx)

        async def run(self, incoming) -> None:
            return None

    monkeypatch.setattr(app_module, "MediaSession", Recorder)
    line = Outbound(tmp_path)

    def call_in(sid: str, caller: str) -> None:
        twiml = line.post(
            "/voice", {"CallSid": sid, "Direction": "inbound", "From": caller, "To": fictional(100)}
        )
        [token] = re.findall(r'<Parameter name="token" value="([^"]+)" />', twiml.text)
        with line.client.websocket_connect("/media") as ws:
            ws.send_json(
                {
                    "event": "start",
                    "streamSid": "MZ1",
                    "start": {"callSid": sid, "customParameters": {"token": token}},
                }
            )

    call_in("CA81", fictional(142))
    call_in("CA82", "anonymous")  # a withheld number has no HMAC to keep
    assert sessions[0].data == {"caller_number_hmac": number_hmac(number_key(KEY), fictional(142))}
    assert sessions[1].data == {}
    assert fictional(142) not in repr(sessions) and fictional(142)[2:] not in repr(sessions)


@pytest.mark.parametrize("path", ["/voice/status", "/voice/amd"])
def test_the_callbacks_refuse_a_bad_signature(tmp_path, path: str) -> None:
    line = Outbound(tmp_path)
    _, dial_id = line.dial()
    line.ledger.bind_call(dial_id, "CA77")
    form = {"CallSid": "CA77", "CallStatus": "no-answer", "AnsweredBy": "machine_end_beep"}
    assert line.client.post(path, data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    assert line.client.post(path, data=form).status_code == 403
    assert line.post(path, form, token="54321").status_code == 403
    assert line.ledger.dial(dial_id)["outcome"] is None and line.twilio.updates == []


def test_the_status_callback_schedules_the_next_attempt_on_no_answer(tmp_path) -> None:
    line = Outbound(tmp_path)
    code, dial_id = line.dial()
    line.ledger.bind_call(dial_id, "CA77")
    assert line.post("/voice/status", {"CallSid": "CA77", "CallStatus": "no-answer"}).status_code == 204
    assert line.ledger.dial(dial_id)["outcome"] == "no_answer"
    assert [d["attempt"] for d in line.ledger.dials(code)] == [1, 2]


def test_the_detection_callback_leaves_the_voicemail_on_the_first_attempts_machine_only(tmp_path) -> None:
    line = Outbound(tmp_path)
    _, first = line.dial()
    line.ledger.bind_call(first, "CA77")
    assert line.post("/voice/amd", {"CallSid": "CA77", "AnsweredBy": "machine_end_beep"}).status_code == 204
    [(sid, twiml)] = line.twilio.updates
    assert sid == "CA77" and "message for Ada" in twiml and twiml.endswith("<Hangup/></Response>")
    _, later = line.dial(attempt=2)
    line.ledger.bind_call(later, "CA78")
    line.post("/voice/amd", {"CallSid": "CA78", "AnsweredBy": "machine_end_other"})
    assert line.twilio.updates[-1] == ("CA78", "<Response><Hangup/></Response>")
    _, person = line.dial()
    line.ledger.bind_call(person, "CA79")
    line.post("/voice/amd", {"CallSid": "CA79", "AnsweredBy": "human"})
    assert len(line.twilio.updates) == 2 and line.ledger.dial(person)["answered_by"] == "human"


def _roles() -> dict[str, dict]:
    doc = yaml.safe_load((Path(__file__).resolve().parent.parent / "data" / "roles.yaml").read_text())
    return {r["id"]: r for r in doc["roles"]}


def test_the_opening_names_each_fixture_applicant_and_nothing_else_from_the_record(tmp_path) -> None:
    roles = _roles()
    fixtures = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "data" / "applications.yaml").read_text()
    )
    line = Outbound(tmp_path)
    for n, row in enumerate(fixtures["applications"]):
        code = row["code"]
        applicant = line.ledger.applicant(code)
        assert applicant is not None
        if not applicant.consented:
            # No consent: the ledger never holds a dial for it, so no opening is ever said.
            with pytest.raises(LedgerError) as refused:
                line.ledger.schedule_dial(code, 1, NOW)
            assert refused.value.kind == "not_dialable"
            continue
        dial = line.ledger.schedule_dial(code, 1, NOW)
        line.ledger.update_dial(dial["dial_id"], status="placed")
        twiml = line.post(f"/voice?dial={dial['dial_id']}", outbound_form(sid=f"CA9{n}")).text
        [opening] = re.findall(r"<Say[^>]*>(.+?)</Say>", twiml)
        assert f"calling for {applicant.first_name} about a job application" in opening
        role = roles[applicant.role]
        for never in (role["title"], role["site"], role["recruiter"], code, code[-4:]):
            assert never not in opening, (code, never)
        for question in role["questions"]:
            assert question["asks"] not in opening and question["say"] not in opening
            for option in question.get("options") or ():
                assert option["say"] not in opening
        assert str(row["pin"]) not in opening


def test_a_full_scripted_outbound_call_leaves_the_raw_number_in_no_span_log_post_or_cockpit_page(
    tmp_path, caplog
) -> None:
    """Intake, the dial, /voice, the callbacks, the media session with the applicant saying their own number
    twice, a hand-off and the cockpit: the number reaches Twilio's Calls.json and the contacts store, and nothing
    else (spec 9.13; DR-025 section 9)."""
    import logging
    import time as clock_time
    from datetime import timedelta

    from candidate_line.brain import Reply, ToolCall
    from candidate_line.escalation import EscalationQueue
    from candidate_line.outbound.intake import signed_headers
    from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber
    from candidate_line.traces.cockpit import create_cockpit

    number = fictional(142)
    area, exchange, last = number[2:5], number[5:8], number[8:]
    names = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    spelled = " ".join(names[int(d)] for d in number[2:])
    caplog.set_level(logging.DEBUG)

    class Clock:
        at = NOW

        def __call__(self) -> datetime:
            return self.at

    class Brain:
        name = model = "scripted"

        def __init__(self) -> None:
            self.replies = [
                Reply("Thanks.", 50, 5, 10, "scripted", "scripted"),
                Reply(
                    "",
                    50,
                    5,
                    10,
                    "scripted",
                    "scripted",
                    tool_calls=(
                        ToolCall(
                            "tu-1",
                            "request_callback",
                            {
                                "best_time": "after five",
                                "reason": f"call me back at {area} {exchange} {last} instead",
                            },
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                Reply("I've asked a recruiter to call you back.", 50, 5, 10, "scripted", "scripted"),
            ]

        def reply(self, system, messages, max_tokens=200, tools=()):
            return self.replies.pop(0)

    class Posts:
        channel = "test"

        def __init__(self) -> None:
            self.texts: list[str] = []

        def post(self, text: str) -> None:
            self.texts.append(text)

    class Twilio:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def place_call(self, to: str, from_: str, **kwargs) -> str:
            self.calls.append({"To": to, **kwargs})
            return "CA" + "7" * 32

        def update_call(self, call_sid: str, twiml: str) -> None:
            raise AssertionError("a person answered; nothing is updated")

    clock, store, posts, twilio = Clock(), TraceStore(":memory:"), Posts(), Twilio()
    ledger = scratch_ledger(tmp_path / "state.json", KEY, clock)
    transcriber, speaker, brain = ScriptedTranscriber(), FakeSpeaker(), Brain()
    escalations = EscalationQueue(store, posts)
    deps = Deps(
        transcriber=lambda: transcriber,
        speaker=lambda: speaker,
        brain=lambda: brain,  # type: ignore[arg-type,return-value]
        hooks=default_hooks,
        store=store,
        escalations=escalations,
        ledger=lambda: ledger,  # type: ignore[arg-type,return-value]
        contacts=Contacts(tmp_path / "contacts.json"),
        twilio=twilio,  # type: ignore[arg-type]
        clock=clock,
    )
    settings = Settings.from_env(
        {
            "OUTBOUND_ENABLED": "1",
            "INTAKE_SIGNING_KEY": KEY,
            "OUTBOUND_ALLOWED_NUMBERS": number,
            "TWILIO_LINE_NUMBER": fictional(100),
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": TOKEN,
            "PUBLIC_BASE_URL": BASE,
            "TRACE_STORE_PATH": ":memory:",
            "LOG_LEVEL": "DEBUG",
        }
    )
    app = create_app(settings, deps)
    client = TestClient(app)
    seen: list[str] = []

    def signed(path: str, form: dict[str, str]):
        answer = client.post(
            path, data=form, headers={"X-Twilio-Signature": twilio_signature(TOKEN, BASE + path, form)}
        )
        seen.append(answer.text)
        return answer

    # Intake, then the dial two minutes later.
    raw = json.dumps(
        {
            "first_name": "Ada",
            "role": "care-aide",
            "phone": number,
            "zone": "America/Chicago",
            "pin": "4721",
            "consent": {
                "version": "consent-2026-11-05",
                "accepted": True,
                "at": "2026-11-05T09:58:00-06:00",
                "source": "careers-form",
            },
        }
    ).encode()
    intake = client.post("/applications", content=raw, headers=signed_headers(KEY, raw, NOW.timestamp()))
    seen.append(intake.text)
    assert intake.status_code == 202 and intake.json()["status"] == "scheduled"
    clock.at = NOW + timedelta(seconds=125)
    assert app.state.dialler.tick() == "placed"
    [placed] = twilio.calls
    assert placed["To"] == number  # the one place the number goes: Twilio's Calls.json
    dial_id = placed["url"].rsplit("=", 1)[1]
    sid = "CA" + "7" * 32

    # Twilio answers: /voice, the progress callback and detection's verdict, each carrying the number in To.
    form = {
        "CallSid": sid,
        "Direction": "outbound-api",
        "From": fictional(100),
        "To": number,
        "Called": number,
    }
    twiml = signed(f"/voice?dial={dial_id}", form).text
    [token] = re.findall(r'<Parameter name="token" value="([^"]+)" />', twiml)
    signed("/voice/status", form | {"CallStatus": "in-progress"})
    signed("/voice/amd", form | {"AnsweredBy": "human", "MachineDetectionDuration": "900"})

    def wait_for(predicate) -> None:
        deadline = clock_time.monotonic() + 5
        while not predicate():
            assert clock_time.monotonic() < deadline, "timed out waiting"
            clock_time.sleep(0.02)

    with client.websocket_connect("/media") as ws:
        ws.send_json(
            {
                "event": "start",
                "streamSid": "MZ1",
                "start": {"callSid": sid, "customParameters": {"token": token, "channel": "outbound"}},
            }
        )
        wait_for(lambda: len(speaker.said) >= 3)  # the preflight word and the PIN ask's two sentences
        transcriber.hear("Hello?", is_partial=False)
        wait_for(lambda: len(speaker.said) >= 5)  # the PIN ask again, by code
        transcriber.hear("four seven two one", is_partial=False)
        wait_for(lambda: "Thanks." in speaker.said)
        transcriber.hear(f"Is this {spelled}?", is_partial=True)
        transcriber.hear(f"Call me back at {area} {exchange} {last} instead, that's {spelled}.")
        wait_for(lambda: "I've asked a recruiter to call you back." in speaker.said)
        transcriber.hear("stop", is_partial=False)
        wait_for(lambda: "Understood." in speaker.said)
        ws.send_json({"event": "stop", "streamSid": "MZ1"})
    wait_for(lambda: (store.call(sid) and store.call(sid).ended_at) is not None)
    signed("/voice/status", form | {"CallStatus": "completed", "CallDuration": "42"})
    escalations.drain(5.0)

    # The cockpit's pages, rendered from the store.
    cockpit = TestClient(create_cockpit(store))
    pages = [cockpit.get("/").text, cockpit.get(f"/calls/{sid}").text]

    spans = [f"{s.kind} {s.name} {s.text} {json.dumps(s.meta)}" for s in store.spans(sid)]
    rows = [repr(store.call(sid))] + [repr(e) for e in store.escalations()]
    logs = [r.getMessage() for r in caplog.records] + [caplog.text]
    written = spans + rows + posts.texts + logs + pages + seen + [everything(ledger)]
    # The call really ran: the PIN turn, the hand-off and the masked number are all there.
    assert any("request_callback" in s for s in spans) and posts.texts, (spans, posts.texts)
    assert store.call(sid).channel == "outbound" and store.call(sid).caller_masked == "***-***-0142"
    # No PIN matched (the scripted brain never calls confirm_applicant), and "stop" on an outbound call is an
    # opt-out: the outbound stop line, every dial cancelled and the number deleted at once (spec 9.12).
    assert ledger.dial(dial_id)["outcome"] == "opted_out" and ledger.opted_out(code=ledger.dials()[0]["code"])
    assert "Understood. This line won't call this number again. Goodbye." in " ".join(speaker.said)
    assert deps.contacts is not None and deps.contacts.codes() == ()
    assert any("partial" in r.getMessage() for r in caplog.records)  # the DEBUG lines were read too

    # The exchange and line digits with any separators between them, and the same seven digits spelled out.
    digits = re.compile(r"\D{0,3}".join(number[-7:]))
    words = re.compile("(?i)" + r"\W+".join(names[int(d)] for d in number[-7:]))
    for text in written:
        assert number not in text
        assert not digits.search(text), text
        assert not words.search(text), text
