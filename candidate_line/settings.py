"""Typed settings, read once from the environment.

Why a module: AGENTS.md rule 7 puts every secret in the environment or 1Password, never in a file, and the
working agreements forbid raw os.environ reads outside the settings module. Nothing here holds a value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Provider = Literal["bedrock", "anthropic", "echo"]
PROVIDERS: tuple[Provider, ...] = ("bedrock", "anthropic", "echo")
VoiceMode = Literal["say", "stream"]
LOG_LEVELS = ("DEBUG", "INFO", "WARNING")
# `make cockpit` serves on loopback at this address (Makefile), so a hand-off's trace link works on this Mac with
# nothing set; COCKPIT_BASE_URL names another address when the recruiter reads the cockpit elsewhere.
DEFAULT_COCKPIT_BASE_URL = "http://127.0.0.1:8001"


@dataclass(frozen=True)
class Settings:
    brain_provider: Provider
    bedrock_model_id: str
    anthropic_model_id: str
    aws_region: str
    public_base_url: str | None
    twilio_auth_token: str | None
    allow_unsigned_webhooks: bool
    voice_mode: VoiceMode
    polly_voice: str
    system_prompt_file: str | None
    log_level: str
    trace_store_path: str | None
    eval_trace_store_path: str | None
    slack_webhook_url: str | None
    cockpit_base_url: str
    # The probe caller's Twilio identifiers (DR-011); the line itself needs only the auth token above.
    twilio_account_sid: str | None
    twilio_line_number: str | None
    twilio_probe_number: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e: Mapping[str, str] = os.environ if env is None else env
        provider = e.get("BRAIN_PROVIDER", "anthropic")
        if provider not in PROVIDERS:
            raise ValueError(f"BRAIN_PROVIDER must be one of {PROVIDERS}, not {provider!r}")
        voice_mode = e.get("VOICE_MODE", "stream")
        if voice_mode not in ("say", "stream"):
            raise ValueError(f"VOICE_MODE must be say or stream, not {voice_mode!r}")
        log_level = e.get("LOG_LEVEL", "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {LOG_LEVELS}, not {log_level!r}")
        return cls(
            brain_provider=provider,  # type: ignore[arg-type]
            # DR-003 (decided 2026-11-02): the live brain is Haiku 5.5 on the Anthropic API, so that is the default
            # provider; Bedrock carries Haiku 4.5, the drill and the on-stage fallback, because this account's
            # Bedrock quota for Haiku 5.5 is zero. A bare `make eval` or `make text` therefore speaks with the
            # brain the room hears (found by the dry run of card 02).
            bedrock_model_id=e.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5"),
            anthropic_model_id=e.get("ANTHROPIC_MODEL_ID", "claude-haiku-5-5"),
            aws_region=e.get("AWS_REGION", "us-east-1"),
            public_base_url=e.get("PUBLIC_BASE_URL") or None,
            twilio_auth_token=e.get("TWILIO_AUTH_TOKEN") or None,
            twilio_account_sid=e.get("TWILIO_ACCOUNT_SID") or None,
            twilio_line_number=e.get("TWILIO_LINE_NUMBER") or None,
            twilio_probe_number=e.get("TWILIO_PROBE_NUMBER") or None,
            # Local curl tests only. Twilio's signature is checked whenever this is off (the default).
            allow_unsigned_webhooks=e.get("ALLOW_UNSIGNED_WEBHOOKS", "") == "1",
            # "stream" answers a call with the media stream (arm A); "say" is item 5's one spoken line.
            voice_mode=voice_mode,  # type: ignore[arg-type]
            polly_voice=e.get("POLLY_VOICE", "Matthew"),
            # The bake-off runs both arms on one prompt file (DR-001, DR-007); unset means the placeholder persona.
            system_prompt_file=e.get("SYSTEM_PROMPT_FILE") or None,
            # DEBUG prints every partial transcript with its time, for reading a turn's end-pointing (DR-006).
            log_level=log_level,
            # The room's store (the phone, text mode, make trace last, the cockpit) and the eval runner's own, so
            # make eval never fills the store the room reads (found by the dry run of card 03). None = the
            # store module's default beside var/traces.sqlite; TRACE_STORE_PATH is the name the store already used.
            trace_store_path=e.get("TRACE_STORE_PATH") or None,
            eval_trace_store_path=e.get("EVAL_TRACE_STORE_PATH") or None,
            # The escalation channel (DR-013): Slack when set, the log poster otherwise. A secret, from the keychain.
            slack_webhook_url=e.get("SLACK_WEBHOOK_URL") or None,
            # Where a hand-off's trace link points (escalation.trace_link). An empty value reads as unset.
            cockpit_base_url=e.get("COCKPIT_BASE_URL") or DEFAULT_COCKPIT_BASE_URL,
        )

    def system_prompt(self) -> str:
        """The system prompt the line speaks with: the named file's text, or the persona module's SYSTEM_PROMPT
        (the placeholder until card 04 writes Gus)."""
        from candidate_line.persona import SYSTEM_PROMPT

        if self.system_prompt_file:
            return Path(self.system_prompt_file).read_text(encoding="utf-8").strip()
        return SYSTEM_PROMPT
