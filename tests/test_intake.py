"""POST /applications: each refusal in its own test, and what a good application stores (spec 9.1, DR-025
section 10, fixes 13 and 14). The ledger is `tests/outbound_fakes.FakeLedger` until lane C's lands."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from candidate_line.hooks import default_hooks
from candidate_line.outbound import number_hmac, number_key
from candidate_line.outbound.contacts import Contacts
from candidate_line.outbound.intake import intake_signature, signed_headers
from candidate_line.settings import Settings
from candidate_line.telephony.app import Deps, create_app
from tests.outbound_fakes import FakeLedger, fictional

KEY = "test-signing-key"
NOW = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)  # Thursday 10:00 Central


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class Line:
    def __init__(self, tmp_path, ledger: FakeLedger | None = None, **env: str) -> None:
        self.clock = Clock(NOW)
        self.ledger = ledger or FakeLedger(now=self.clock)
        self.contacts = Contacts(tmp_path / "contacts.json")
        settings = {
            "INTAKE_SIGNING_KEY": KEY,
            "OUTBOUND_ALLOWED_NUMBERS": fictional(142),
            "TRACE_STORE_PATH": ":memory:",
        } | env
        deps = Deps(
            transcriber=lambda: None,  # type: ignore[arg-type,return-value]
            speaker=lambda: None,  # type: ignore[arg-type,return-value]
            brain=lambda: None,  # type: ignore[arg-type,return-value]
            hooks=default_hooks,
            ledger=lambda: self.ledger,  # type: ignore[arg-type,return-value]
            contacts=self.contacts,
            clock=self.clock,
        )
        self.client = TestClient(create_app(Settings.from_env(settings), deps))

    def post(self, body: bytes, headers: dict[str, str] | None = None):
        return self.client.post(
            "/applications",
            content=body,
            headers=headers or signed_headers(KEY, body, self.clock().timestamp()),
        )


def application(**changes) -> dict:
    doc = {
        "first_name": "Ada",
        "role": "care-aide",
        "phone": fictional(142),
        "zone": "America/Chicago",
        "pin": "4721",
        "consent": {
            "version": "consent-2026-11-05",
            "accepted": True,
            "at": "2026-11-05T09:58:00-06:00",
            "source": "careers-form",
        },
    }
    for key, value in changes.items():
        if key.startswith("consent_"):
            doc["consent"][key.removeprefix("consent_")] = value
        else:
            doc[key] = value
    return doc


def body(**changes) -> bytes:
    return json.dumps(application(**changes)).encode()


def nothing_stored(line: Line) -> bool:
    return line.ledger.applications == {} and line.ledger.dial_rows == [] and not line.contacts.path.exists()


def test_a_good_application_answers_202_with_the_code_and_never_the_number_or_the_pin(
    tmp_path, caplog
) -> None:
    line = Line(tmp_path)
    with caplog.at_level(logging.INFO):
        response = line.post(body())
    assert response.status_code == 202
    answer = response.json()
    assert set(answer) == {"code", "status"} and answer["status"] == "scheduled"
    assert answer["code"].startswith("ACME-") and len(answer["code"]) == 9
    assert "4721" not in response.text and "0142" not in response.text
    code = answer["code"]
    stored = line.ledger.applications[code]
    assert stored["number_hmac"] == number_hmac(number_key(KEY), fictional(142))
    assert stored["number_masked"] == "***-***-0142"
    assert stored["not_dialled"] is None and len(stored["nonce"]) >= 22
    assert stored["consent"]["text_sha256"] and stored["consent"]["accepted"] is True
    assert "4721" not in line.ledger.everything() and fictional(142) not in line.ledger.everything()
    assert line.contacts.number(code) == fictional(142)
    [dial] = line.ledger.dials(code)
    assert (dial["attempt"], dial["status"], dial["due_at"]) == (1, "due", "2026-11-05T16:02:00+00:00")
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert f"application {code} from ***-***-0142: scheduled" in messages
    assert fictional(142) not in messages and "4721" not in messages


def test_an_application_outside_the_window_waits_for_its_next_opening(tmp_path) -> None:
    line = Line(tmp_path)
    line.clock.at = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)  # Saturday 21:00 Central
    code = line.post(body()).json()["code"]
    assert line.ledger.dials(code)[0]["due_at"] == "2026-11-09T15:00:00+00:00"  # Monday 09:00 Central


def test_no_key_answers_503_and_stores_nothing(tmp_path) -> None:
    line = Line(tmp_path, INTAKE_SIGNING_KEY="")
    assert line.post(body(), signed_headers("any", body(), NOW.timestamp())).status_code == 503
    assert nothing_stored(line)


def test_a_bad_signature_is_refused(tmp_path) -> None:
    line = Line(tmp_path)
    headers = signed_headers("another-key", body(), NOW.timestamp())
    assert line.post(body(), headers).status_code == 401
    headers = signed_headers(KEY, body(), NOW.timestamp())
    tampered = body(first_name="Eve")  # the signature was over another body
    assert line.post(tampered, headers).status_code == 401
    assert nothing_stored(line)


def test_a_missing_signature_is_refused(tmp_path) -> None:
    line = Line(tmp_path)
    headers = signed_headers(KEY, body(), NOW.timestamp())
    del headers["X-Intake-Signature"]
    assert line.post(body(), headers).status_code == 401
    assert nothing_stored(line)


def test_a_signature_over_the_timestamp_and_body_but_not_the_nonce_is_refused(tmp_path) -> None:
    import hashlib
    import hmac

    line = Line(tmp_path)
    raw = body()
    timestamp = str(int(NOW.timestamp()))
    headers = signed_headers(KEY, raw, NOW.timestamp())
    headers["X-Intake-Signature"] = hmac.new(
        KEY.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    assert line.post(raw, headers).status_code == 401
    assert nothing_stored(line)


@pytest.mark.parametrize(
    "nonce", [None, "", "short", "has spaces in it at all!!", "x" * 65, "ab/cd+efghijklmnopqrstuv"]
)
def test_a_missing_or_malformed_nonce_is_refused(tmp_path, nonce) -> None:
    line = Line(tmp_path)
    raw = body()
    headers = signed_headers(KEY, raw, NOW.timestamp())
    if nonce is None:
        del headers["X-Intake-Nonce"]
    else:
        headers["X-Intake-Nonce"] = nonce
        headers["X-Intake-Signature"] = intake_signature(KEY, headers["X-Intake-Timestamp"], nonce, raw)
    assert line.post(raw, headers).status_code == 401
    assert nothing_stored(line)


@pytest.mark.parametrize("skew", [-301, 301, -3600])
def test_a_stale_or_future_timestamp_is_refused(tmp_path, skew: int) -> None:
    line = Line(tmp_path)
    raw = body()
    assert line.post(raw, signed_headers(KEY, raw, NOW.timestamp() + skew)).status_code == 401
    assert nothing_stored(line)


def test_a_timestamp_inside_300_seconds_is_taken(tmp_path) -> None:
    line = Line(tmp_path)
    raw = body()
    assert line.post(raw, signed_headers(KEY, raw, NOW.timestamp() - 299)).status_code == 202


def test_a_nonce_seen_in_the_last_ten_minutes_is_refused_409(tmp_path) -> None:
    line = Line(tmp_path)
    raw = body()
    headers = signed_headers(KEY, raw, NOW.timestamp())
    assert line.post(raw, headers).status_code == 202
    assert line.post(raw, headers).status_code == 409  # the same signed request, replayed at once
    line.clock.at = NOW + timedelta(seconds=290)
    again = signed_headers(KEY, raw, line.clock().timestamp(), nonce=headers["X-Intake-Nonce"])
    assert line.post(raw, again).status_code == 409  # re-signed with a fresh timestamp, same nonce
    assert len(line.ledger.applications) == 1


def test_a_nonce_seen_before_a_restart_is_found_on_the_stored_application(tmp_path) -> None:
    first = Line(tmp_path)
    raw = body()
    headers = signed_headers(KEY, raw, NOW.timestamp())
    assert first.post(raw, headers).status_code == 202
    restarted = Line(tmp_path, ledger=first.ledger)  # a new process: its own memory is empty
    restarted.clock.at = NOW + timedelta(seconds=200)
    replay = signed_headers(KEY, raw, restarted.clock().timestamp(), nonce=headers["X-Intake-Nonce"])
    assert restarted.post(raw, replay).status_code == 409
    assert len(first.ledger.applications) == 1


def test_a_nonce_older_than_ten_minutes_is_no_longer_remembered(tmp_path) -> None:
    line = Line(tmp_path)
    raw = body()
    headers = signed_headers(KEY, raw, NOW.timestamp())
    assert line.post(raw, headers).status_code == 202
    line.clock.at = NOW + timedelta(seconds=601)
    later = signed_headers(KEY, raw, line.clock().timestamp(), nonce=headers["X-Intake-Nonce"])
    assert line.post(raw, later).status_code == 202


def test_an_extra_key_is_refused(tmp_path) -> None:
    line = Line(tmp_path)
    assert line.post(body(score=9)).status_code == 422
    assert line.post(body(consent_note="x")).status_code == 422
    assert nothing_stored(line)


# Each built from the fictional number at run time, so no file holds a phone number (DR-025 section 6).
BAD_NUMBERS = {
    "national digits": lambda n: n[2:],
    "spaced": lambda n: f"{n[:2]} {n[2:5]} {n[5:8]} {n[8:]}",
    "area code starting with 1": lambda n: "+11" + n[3:],
    "exchange starting with 1": lambda n: n[:5] + "1" + n[6:],
    "another country": lambda n: "+44" + n[2:],
    "a digit short": lambda n: n[:-1],
    "a JSON number": lambda n: int(n[1:]),
}


@pytest.mark.parametrize("form", sorted(BAD_NUMBERS))
def test_a_bad_number_is_refused_and_never_echoed(tmp_path, form: str) -> None:
    line = Line(tmp_path)
    response = line.post(body(phone=BAD_NUMBERS[form](fictional(142))))
    assert response.status_code == 422
    assert "555" not in response.text and "0142" not in response.text
    assert response.json()["fields"] == ["phone"]
    assert nothing_stored(line)


@pytest.mark.parametrize("zone", ["Europe/London", "America/Nowhere", "UTC", "", "Pacific/Guam"])
def test_a_bad_zone_is_refused(tmp_path, zone: str) -> None:
    line = Line(tmp_path)
    assert line.post(body(zone=zone)).status_code == 422
    assert nothing_stored(line)


@pytest.mark.parametrize("pin", ["123", "12345", "12a4", 4721, ""])
def test_a_bad_pin_is_refused_and_never_echoed(tmp_path, pin) -> None:
    line = Line(tmp_path)
    response = line.post(body(pin=pin))
    assert response.status_code == 422 and "4721" not in response.text and "1234" not in response.text
    assert nothing_stored(line)


def test_a_bad_role_is_refused(tmp_path) -> None:
    line = Line(tmp_path)
    response = line.post(body(role="astronaut"))
    assert response.status_code == 422 and response.json()["fields"] == ["role"]
    assert nothing_stored(line)


@pytest.mark.parametrize("name", ["", "A" * 41, "R2D2", "Ada!", " Ada", "-Ada"])
def test_a_bad_first_name_is_refused(tmp_path, name: str) -> None:
    line = Line(tmp_path)
    assert line.post(body(first_name=name)).status_code == 422
    assert nothing_stored(line)


def test_a_first_name_with_letters_spaces_hyphens_and_apostrophes_is_taken(tmp_path) -> None:
    line = Line(tmp_path)
    assert line.post(body(first_name="Mary-Jane O'Neil")).status_code == 202
    assert line.post(body(first_name="Zoë")).status_code == 202


def test_an_unknown_consent_version_is_refused(tmp_path) -> None:
    line = Line(tmp_path)
    response = line.post(body(consent_version="consent-1999-01-01"))
    assert response.status_code == 422 and response.json()["fields"] == ["consent.version"]
    assert nothing_stored(line)


@pytest.mark.parametrize(
    "changes",
    [
        {"consent_accepted": "yes"},
        {"consent_at": "yesterday"},
        {"consent_at": "2026-11-05T09:58:00"},
        {"consent_source": "web"},
    ],
)
def test_a_consent_record_outside_the_schema_is_refused(tmp_path, changes) -> None:
    line = Line(tmp_path)
    assert line.post(body(**changes)).status_code == 422
    assert nothing_stored(line)


def test_a_body_over_4_kb_is_refused_413(tmp_path) -> None:
    line = Line(tmp_path)
    raw = body(first_name="Ada") + b" " * 4097
    assert line.post(raw).status_code == 413
    assert nothing_stored(line)


def test_a_body_that_is_not_json_is_refused_422(tmp_path) -> None:
    line = Line(tmp_path)
    assert line.post(b"first_name=Ada").status_code == 422
    assert nothing_stored(line)


def test_no_consent_is_stored_with_its_reason_and_no_number_or_dial(tmp_path) -> None:
    line = Line(tmp_path)
    response = line.post(body(consent_accepted=False))
    assert response.status_code == 202 and response.json()["status"] == "no_consent"
    code = response.json()["code"]
    assert line.ledger.applications[code]["not_dialled"] == "no_consent"
    assert line.contacts.number(code) is None and line.ledger.dials(code) == []


def test_an_opted_out_number_is_stored_with_its_reason_and_no_number_or_dial(tmp_path) -> None:
    line = Line(tmp_path)
    hashed = number_hmac(number_key(KEY), fictional(142))
    line.ledger.opt_outs.append({"code": "ACME-1000", "number_hmac": hashed, "how": "said stop"})
    response = line.post(body())
    assert response.status_code == 202 and response.json()["status"] == "opted_out"
    code = response.json()["code"]
    assert line.ledger.applications[code]["not_dialled"] == "opted_out"
    assert line.contacts.number(code) is None and line.ledger.dials(code) == []


def test_a_number_off_the_allow_list_is_stored_as_not_allowed_with_no_number_or_dial(tmp_path) -> None:
    line = Line(tmp_path)
    response = line.post(body(phone=fictional(143)))
    assert response.status_code == 202 and response.json()["status"] == "not_allowed"
    code = response.json()["code"]
    assert line.ledger.applications[code]["not_dialled"] == "not_allowed"
    assert line.ledger.applications[code]["number_masked"] == "***-***-0143"
    assert line.contacts.number(code) is None and line.ledger.dials(code) == []
    assert not line.contacts.path.exists()  # no raw number was ever written


def test_an_empty_allow_list_dials_nobody(tmp_path) -> None:
    line = Line(tmp_path, OUTBOUND_ALLOWED_NUMBERS="")
    assert line.post(body()).json()["status"] == "not_allowed"


def test_a_failed_dial_write_takes_the_number_back_out(tmp_path) -> None:
    class Unscheduled(FakeLedger):
        def schedule_dial(self, code, attempt, due_at):
            raise OSError("disk full")

    line = Line(tmp_path, ledger=Unscheduled())
    with pytest.raises(OSError):
        line.post(body())
    [code] = line.ledger.applications
    assert line.contacts.number(code) is None
