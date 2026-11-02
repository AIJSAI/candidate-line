from fastapi.testclient import TestClient

from candidate_line.settings import Settings
from candidate_line.telephony.app import HELLO_LINE, create_app, twilio_signature

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
    return TestClient(create_app(Settings.from_env(env)))


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
