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


def test_system_prompt_comes_from_the_named_file_or_the_placeholder(tmp_path) -> None:
    from candidate_line.persona import PLACEHOLDER_SYSTEM

    persona = tmp_path / "persona.md"
    persona.write_text("You are Gus. One sentence.\n", encoding="utf-8")
    with_file = Settings.from_env({"SYSTEM_PROMPT_FILE": str(persona)})
    assert with_file.system_prompt() == "You are Gus. One sentence."
    assert Settings.from_env({}).system_prompt() == PLACEHOLDER_SYSTEM


def test_log_level_defaults_to_info_and_refuses_nonsense() -> None:
    assert Settings.from_env({}).log_level == "INFO"
    assert Settings.from_env({"LOG_LEVEL": "debug"}).log_level == "DEBUG"
    with pytest.raises(ValueError):
        Settings.from_env({"LOG_LEVEL": "LOUD"})
