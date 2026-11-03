import pytest

from candidate_line.settings import Settings


def test_defaults_match_dr003() -> None:
    s = Settings.from_env({})
    assert s.brain_provider == "anthropic"  # decided 2026-11-02: the live brain is on the Anthropic API
    assert s.bedrock_model_id == "us.anthropic.claude-haiku-4-5"  # the Bedrock fallback with a quota
    assert s.anthropic_model_id == "claude-haiku-5-5"
    assert s.aws_region == "us-east-1"
    assert s.twilio_auth_token is None
    assert s.allow_unsigned_webhooks is False


def test_unknown_provider_is_refused_at_startup() -> None:
    with pytest.raises(ValueError, match="BRAIN_PROVIDER"):
        Settings.from_env({"BRAIN_PROVIDER": "openai"})


def test_empty_secret_reads_as_absent() -> None:
    assert Settings.from_env({"TWILIO_AUTH_TOKEN": ""}).twilio_auth_token is None


def test_system_prompt_comes_from_the_named_file_or_the_persona(tmp_path) -> None:
    from candidate_line import persona

    f = tmp_path / "p.md"
    f.write_text("You are a test persona.\n")
    assert Settings.from_env({"SYSTEM_PROMPT_FILE": str(f)}).system_prompt() == "You are a test persona."
    # The fallback is whatever persona.py holds (the placeholder until card 04 writes Gus), never a fixed text.
    assert Settings.from_env({}).system_prompt() == persona.SYSTEM_PROMPT


def test_log_level_defaults_to_info_and_refuses_nonsense() -> None:
    assert Settings.from_env({}).log_level == "INFO"
    assert Settings.from_env({"LOG_LEVEL": "debug"}).log_level == "DEBUG"
    with pytest.raises(ValueError):
        Settings.from_env({"LOG_LEVEL": "LOUD"})


def test_the_probe_callers_twilio_identifiers_come_through_settings() -> None:
    s = Settings.from_env(
        {"TWILIO_ACCOUNT_SID": "ACx", "TWILIO_LINE_NUMBER": "+15550001", "TWILIO_PROBE_NUMBER": ""}
    )
    assert (s.twilio_account_sid, s.twilio_line_number, s.twilio_probe_number) == ("ACx", "+15550001", None)
