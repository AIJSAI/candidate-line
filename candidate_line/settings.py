"""Typed settings, read once from the environment.

Why a module: AGENTS.md rule 7 puts every secret in the environment or 1Password, never in a file, and the
working agreements forbid raw os.environ reads outside the settings module. Nothing here holds a value.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
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
# The outbound call (spec section 9, DR-025 section 11). Twenty dials a day bound the bill with nobody calling, one
# call at a time fits the one 0.25 vCPU task, and 480 s fits five posted questions and a booking where the inbound
# 300 does not. Thirty days for a raw number and four years for the answers are the retention defaults James took
# on 2026-11-05 (four years is the California automated-decision minimum).
DEFAULT_MAX_OUTBOUND_PER_DAY = 20
DEFAULT_MAX_DIAL_ATTEMPTS = 3
DEFAULT_CONTACTS_RETENTION_DAYS = 30
DEFAULT_ANSWERS_RETENTION_DAYS = 1460
DEFAULT_MAX_OUTBOUND_CALL_SECONDS = 480
DEFAULT_CALL_WINDOW = "09:00-20:00 Mon-Sat"
# The upper bounds a typo must not pass (spec 9.3: a cap that reads as nonsense stops the process). 4800 for 480
# seconds would let one stuck call run 81 minutes, and 200 for 20 dials multiplies the bill with nobody calling.
# The numbers are James's money call (card 08, open decision 3); a larger one is his to set here.
MAX_OUTBOUND_PER_DAY_LIMIT = 100
MAX_OUTBOUND_CALL_SECONDS_LIMIT = 900
# The federal limit for a telephone solicitation, at the called party's location (47 CFR 64.1200(c)(1), spec 9.2).
# The window's end is the first minute it does not call, so a window may end at 21:00 itself.
EARLIEST_CALL = time(8, 0)
LATEST_CALL = time(21, 0)
DEFAULT_CONTACTS_PATH = Path(__file__).resolve().parent.parent / "var" / "contacts.json"
# A US number in E.164 form with a real area code and exchange: the intake schema's form and the allow-list's.
US_E164 = re.compile(r"^\+1[2-9]\d{2}[2-9]\d{6}$")
SUNDAY = 6
_DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": SUNDAY}
_WINDOW = re.compile(r"^\s*(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\s+([A-Za-z,\- ]+?)\s*$")


@dataclass(frozen=True)
class CallWindow:
    """When the dialler may call, in the applicant's own zone: from `start` up to but not including `end`, on
    `days` (Monday is 0). Sunday is never among them; `from_env` refuses a window that names it."""

    start: time
    end: time
    days: frozenset[int]

    @property
    def middle(self) -> time:
        """The window's midpoint, where a third attempt lands (14:30 for the default window, spec 9.4)."""
        minutes = (self.start.hour * 60 + self.start.minute + self.end.hour * 60 + self.end.minute) // 2
        return time(minutes // 60, minutes % 60)


def parse_call_window(raw: str) -> CallWindow:
    """`HH:MM-HH:MM` and a day range (`Mon-Sat`) or list (`Mon,Wed,Fri`). An empty or reversed window, or one that
    names Sunday or wraps through it, stops the process: a window that reads wrong would call at the wrong hour."""
    m = _WINDOW.match(raw or "")
    if not m:
        raise ValueError(f"CALL_WINDOW must read like {DEFAULT_CALL_WINDOW!r}, not {raw!r}")
    h1, m1, h2, m2 = (int(m.group(i)) for i in range(1, 5))
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError(f"CALL_WINDOW has a time that is not on a clock: {raw!r}")
    start, end = time(h1, m1), time(h2, m2)
    if start >= end:
        raise ValueError(f"CALL_WINDOW must end after it starts: {raw!r}")
    if start < EARLIEST_CALL or end > LATEST_CALL:
        raise ValueError("CALL_WINDOW must sit inside 08:00-21:00 (47 CFR 64.1200(c)(1), spec 9.2)")
    days: set[int] = set()
    for part in (p.strip().lower() for p in m.group(5).split(",")):
        first, _, last = (x.strip()[:3] for x in part.partition("-"))
        if first not in _DAY_NAMES or (last and last not in _DAY_NAMES):
            raise ValueError(f"CALL_WINDOW names a day it cannot read: {raw!r}")
        a, b = _DAY_NAMES[first], _DAY_NAMES[last or first]
        span = range(a, b + 1) if a <= b else [*range(a, 7), *range(b + 1)]
        days.update(span)
    if SUNDAY in days:
        raise ValueError("CALL_WINDOW may never include Sunday (spec 9.2)")
    return CallWindow(start, end, frozenset(days))


def parse_allowed_numbers(raw: str) -> frozenset[str]:
    """The comma-separated allow-list. An entry that is empty or not a US E.164 number stops the process; the
    message names the entry by its place, never by its digits, because the list is a secret (DR-025 section 11)."""
    if not raw.strip():
        return frozenset()
    numbers: set[str] = set()
    for i, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        if not entry:
            raise ValueError(f"OUTBOUND_ALLOWED_NUMBERS entry {i} is empty")
        if not US_E164.match(entry):
            raise ValueError(f"OUTBOUND_ALLOWED_NUMBERS entry {i} is not a US number in E.164 form")
        numbers.add(entry)
    return frozenset(numbers)


@dataclass(frozen=True)
class Settings:
    """The secrets and the numbers are kept out of the dataclass's repr, which str uses too, so a logged Settings
    or a traceback that reprs one never shows a token, a key, a phone number, an address, an account id or a
    webhook URL (F8). `field(repr=False)` with no default keeps each one positional."""

    brain_provider: Provider
    bedrock_model_id: str
    anthropic_model_id: str
    aws_region: str
    # The host every webhook URL Twilio calls is built on: no secret, but never written down (AGENTS.md rule 7).
    public_base_url: str | None = field(repr=False)
    twilio_auth_token: str | None = field(repr=False)
    allow_unsigned_webhooks: bool
    voice_mode: VoiceMode
    polly_voice: str
    system_prompt_file: str | None
    log_level: str
    trace_store_path: str | None
    eval_trace_store_path: str | None
    state_path: str | None  # None means in memory
    slack_webhook_url: str | None = field(repr=False)
    # The topic's ARN holds the account id.
    sns_topic_arn: str | None = field(repr=False)
    # The hand-off email's verified sender and its recipients (SES_SENDER, SES_RECIPIENTS comma-separated).
    ses_sender: str | None = field(repr=False)
    ses_recipients: tuple[str, ...] = field(repr=False)
    cockpit_base_url: str
    max_call_seconds: int
    max_calls_per_day: int
    # The probe caller's Twilio identifiers (DR-011); the line itself needs only the auth token above. The probe's
    # number is on the allow-list, which DR-025 says is never logged.
    twilio_account_sid: str | None = field(repr=False)
    twilio_line_number: str | None = field(repr=False)
    twilio_probe_number: str | None = field(repr=False)
    # The outbound call (DR-025 section 11). Defaults keep the dialling off and every cap at its contract value.
    outbound_enabled: bool = False
    max_outbound_per_day: int = DEFAULT_MAX_OUTBOUND_PER_DAY
    max_concurrent_outbound: int = 1
    call_window: CallWindow = field(default_factory=lambda: parse_call_window(DEFAULT_CALL_WINDOW))
    max_dial_attempts: int = DEFAULT_MAX_DIAL_ATTEMPTS
    contacts_path: str = str(DEFAULT_CONTACTS_PATH)
    contacts_retention_days: int = DEFAULT_CONTACTS_RETENTION_DAYS
    answers_retention_days: int = DEFAULT_ANSWERS_RETENTION_DAYS
    max_outbound_call_seconds: int = DEFAULT_MAX_OUTBOUND_CALL_SECONDS
    intake_signing_key: str | None = field(default=None, repr=False)
    outbound_allowed_numbers: frozenset[str] = field(default_factory=frozenset, repr=False)

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
            **_outbound(e),
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


def _at_most(name: str, value: int, most: int) -> int:
    if value > most:
        raise ValueError(f"{name} must be at most {most}, not {value}")
    return value


def _outbound(e: Mapping[str, str]) -> dict[str, object]:
    """The outbound settings, each refused at start when it reads as zero or nonsense, so a mistyped cap never
    switches a control off without a word. With dialling on, every value the dial needs must be there."""
    enabled_raw = (e.get("OUTBOUND_ENABLED") or "0").strip()
    if enabled_raw not in ("0", "1"):
        raise ValueError(f"OUTBOUND_ENABLED must be 0 or 1, not {enabled_raw!r}")
    concurrent = _positive_int(e, "MAX_CONCURRENT_OUTBOUND", 1)
    if concurrent != 1:
        # One 0.25 vCPU task and one claim under the ledger's file lock: a second call at once is not built.
        raise ValueError(f"MAX_CONCURRENT_OUTBOUND must be 1 this week, not {concurrent}")
    attempts = _positive_int(e, "MAX_DIAL_ATTEMPTS", DEFAULT_MAX_DIAL_ATTEMPTS)
    if attempts > 3:
        raise ValueError(f"MAX_DIAL_ATTEMPTS must be from 1 to 3, not {attempts}")
    values: dict[str, object] = {
        "outbound_enabled": enabled_raw == "1",
        "max_outbound_per_day": _at_most(
            "MAX_OUTBOUND_PER_DAY",
            _positive_int(e, "MAX_OUTBOUND_PER_DAY", DEFAULT_MAX_OUTBOUND_PER_DAY),
            MAX_OUTBOUND_PER_DAY_LIMIT,
        ),
        "max_concurrent_outbound": concurrent,
        "call_window": parse_call_window(e.get("CALL_WINDOW") or DEFAULT_CALL_WINDOW),
        "max_dial_attempts": attempts,
        "contacts_path": e.get("CONTACTS_PATH") or str(DEFAULT_CONTACTS_PATH),
        "contacts_retention_days": _positive_int(
            e, "CONTACTS_RETENTION_DAYS", DEFAULT_CONTACTS_RETENTION_DAYS
        ),
        "answers_retention_days": _positive_int(e, "ANSWERS_RETENTION_DAYS", DEFAULT_ANSWERS_RETENTION_DAYS),
        "max_outbound_call_seconds": _at_most(
            "MAX_OUTBOUND_CALL_SECONDS",
            _positive_int(e, "MAX_OUTBOUND_CALL_SECONDS", DEFAULT_MAX_OUTBOUND_CALL_SECONDS),
            MAX_OUTBOUND_CALL_SECONDS_LIMIT,
        ),
        "intake_signing_key": e.get("INTAKE_SIGNING_KEY") or None,
        "outbound_allowed_numbers": parse_allowed_numbers(e.get("OUTBOUND_ALLOWED_NUMBERS") or ""),
    }
    if values["outbound_enabled"]:
        # The dial's From, its signed callbacks and the voicemail's number all come from these; a dialler that
        # started without one would dial and then fail every callback, or dial from nowhere.
        needed = {
            "INTAKE_SIGNING_KEY": values["intake_signing_key"],
            "OUTBOUND_ALLOWED_NUMBERS": values["outbound_allowed_numbers"],
            "TWILIO_LINE_NUMBER": e.get("TWILIO_LINE_NUMBER"),
            "TWILIO_ACCOUNT_SID": e.get("TWILIO_ACCOUNT_SID"),
            "TWILIO_AUTH_TOKEN": e.get("TWILIO_AUTH_TOKEN"),
            "PUBLIC_BASE_URL": e.get("PUBLIC_BASE_URL"),
        }
        missing = [name for name, value in needed.items() if not value]
        if missing:
            raise ValueError(f"OUTBOUND_ENABLED=1 needs {', '.join(missing)}")
        if not US_E164.match(str(e.get("TWILIO_LINE_NUMBER"))):
            raise ValueError("TWILIO_LINE_NUMBER must be a US number in E.164 form with OUTBOUND_ENABLED=1")
    return values


def _state_path(raw: str | None) -> str | None:
    """An empty value reads as unset, like every other path here."""
    if raw == ":memory:":
        return None
    return raw or str(DEFAULT_STATE_PATH)
