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
# The tools' ledger keeps the line's bookings, move requests and callbacks here, beside the trace store under the
# ignored var/; STATE_PATH names another file, and ":memory:" keeps them for one call only (the tests, the evals and
# the walks, so the live ledger stays clean).
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "var" / "state.json"
# The caps a public number needs before it is on any page (DR-021). Five minutes is two more than the three spec
# section 8 gives a good call, so a candidate who books never meets it. Thirty calls a day is far above the real
# callers of a week and bounds what a dialler left running can spend.
DEFAULT_MAX_CALL_SECONDS = 300
DEFAULT_MAX_CALLS_PER_DAY = 30


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
    state_path: str | None  # None means in memory
    slack_webhook_url: str | None
    sns_topic_arn: str | None
    # The hand-off email's verified sender and its recipients (SES_SENDER, SES_RECIPIENTS comma-separated).
    ses_sender: str | None
    ses_recipients: tuple[str, ...]
    cockpit_base_url: str
    max_call_seconds: int
    max_calls_per_day: int
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
            bedrock_model_id=e.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
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
            state_path=_state_path(e.get("STATE_PATH")),
            # The escalation channel (DR-013): SNS when its topic is set, Slack when its webhook is, the log poster
            # otherwise (escalation.default_poster). The webhook is a secret, from the keychain. The topic ARN is
            # no secret but holds the account id, so it too comes from the environment and is never written down.
            slack_webhook_url=e.get("SLACK_WEBHOOK_URL") or None,
            sns_topic_arn=e.get("SNS_TOPIC_ARN") or None,
            ses_sender=e.get("SES_SENDER") or None,
            ses_recipients=tuple(a.strip() for a in (e.get("SES_RECIPIENTS") or "").split(",") if a.strip()),
            # Where a hand-off's trace link points (escalation.trace_link). An empty value reads as unset.
            cockpit_base_url=e.get("COCKPIT_BASE_URL") or DEFAULT_COCKPIT_BASE_URL,
            # A cap that reads as zero or as nonsense would switch the control off without a word, so it stops
            # the process at start instead.
            max_call_seconds=_positive_int(e, "MAX_CALL_SECONDS", DEFAULT_MAX_CALL_SECONDS),
            max_calls_per_day=_positive_int(e, "MAX_CALLS_PER_DAY", DEFAULT_MAX_CALLS_PER_DAY),
        )

    def system_prompt(self) -> str:
        """The system prompt the line speaks with: the named file's text, or the persona module's SYSTEM_PROMPT
        (the placeholder until card 04 writes Gus)."""
        from candidate_line.persona import SYSTEM_PROMPT

        if self.system_prompt_file:
            return Path(self.system_prompt_file).read_text(encoding="utf-8").strip()
        return SYSTEM_PROMPT


def _positive_int(e: Mapping[str, str], name: str, default: int) -> int:
    """A whole number of at least one; an empty value reads as unset, like every other setting here."""
    raw = e.get(name) or ""
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, not {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1, not {value}")
    return value


def _state_path(raw: str | None) -> str | None:
    """An empty value reads as unset, like every other path here."""
    if raw == ":memory:":
        return None
    return raw or str(DEFAULT_STATE_PATH)
