"""Typed settings, read once from the environment.

Why a module: AGENTS.md rule 7 puts every secret in the environment or 1Password, never in a file, and the
working agreements forbid raw os.environ reads outside the settings module. Nothing here holds a value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Provider = Literal["bedrock", "anthropic", "echo"]
PROVIDERS: tuple[Provider, ...] = ("bedrock", "anthropic", "echo")


@dataclass(frozen=True)
class Settings:
    brain_provider: Provider
    bedrock_model_id: str
    anthropic_model_id: str
    aws_region: str
    public_base_url: str | None
    twilio_auth_token: str | None
    allow_unsigned_webhooks: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e: Mapping[str, str] = os.environ if env is None else env
        provider = e.get("BRAIN_PROVIDER", "bedrock")
        if provider not in PROVIDERS:
            raise ValueError(f"BRAIN_PROVIDER must be one of {PROVIDERS}, not {provider!r}")
        return cls(
            brain_provider=provider,  # type: ignore[arg-type]
            # DR-003: Haiku 5.5 through the US geo profile; the global profile is the throttle spare.
            bedrock_model_id=e.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-5-5"),
            anthropic_model_id=e.get("ANTHROPIC_MODEL_ID", "claude-haiku-5-5"),
            aws_region=e.get("AWS_REGION", "us-east-1"),
            public_base_url=e.get("PUBLIC_BASE_URL") or None,
            twilio_auth_token=e.get("TWILIO_AUTH_TOKEN") or None,
            # Local curl tests only. Twilio's signature is checked whenever this is off (the default).
            allow_unsigned_webhooks=e.get("ALLOW_UNSIGNED_WEBHOOKS", "") == "1",
        )
