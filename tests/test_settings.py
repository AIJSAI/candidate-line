import pytest

from candidate_line.settings import Settings


def test_defaults_match_dr003() -> None:
    s = Settings.from_env({})
    assert s.brain_provider == "bedrock"
    assert s.bedrock_model_id == "us.anthropic.claude-haiku-5-5"
    assert s.anthropic_model_id == "claude-haiku-5-5"
    assert s.aws_region == "us-east-1"
    assert s.twilio_auth_token is None
    assert s.allow_unsigned_webhooks is False


def test_unknown_provider_is_refused_at_startup() -> None:
    with pytest.raises(ValueError, match="BRAIN_PROVIDER"):
        Settings.from_env({"BRAIN_PROVIDER": "openai"})


def test_empty_secret_reads_as_absent() -> None:
    assert Settings.from_env({"TWILIO_AUTH_TOKEN": ""}).twilio_auth_token is None
