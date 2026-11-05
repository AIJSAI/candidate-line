import pytest

from candidate_line.settings import Settings


def test_defaults_match_dr003() -> None:
    s = Settings.from_env({})
    assert s.brain_provider == "anthropic"  # decided 2026-11-02: the live brain is on the Anthropic API
    assert (
        s.bedrock_model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    )  # the Bedrock fallback with a quota; the dated profile id is the one Bedrock accepts (DR-003, 2026-11-03)
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


def test_the_cockpit_base_url_defaults_to_the_loopback_cockpit_and_can_be_named() -> None:
    assert Settings.from_env({}).cockpit_base_url == "http://127.0.0.1:8001"  # make cockpit's address
    assert Settings.from_env({"COCKPIT_BASE_URL": ""}).cockpit_base_url == "http://127.0.0.1:8001"
    named = Settings.from_env({"COCKPIT_BASE_URL": "https://cockpit.example"})
    assert named.cockpit_base_url == "https://cockpit.example"


# The outbound settings (DR-025 section 11; fixes 1, 13, 16 and 17). Numbers are fictional 555-01xx ones, made at
# run time, so no file holds a phone number (AGENTS.md rule 7).
def fictional(n: int) -> str:
    return f"+1312555{n:04d}"


OUTBOUND_ON = {
    "OUTBOUND_ENABLED": "1",
    "INTAKE_SIGNING_KEY": "test-signing-key",
    "TWILIO_ACCOUNT_SID": "ACtest",
    "TWILIO_AUTH_TOKEN": "test-token",
    "PUBLIC_BASE_URL": "https://line.example",
}


def outbound_on(**extra: str) -> dict[str, str]:
    return (
        OUTBOUND_ON
        | {"TWILIO_LINE_NUMBER": fictional(100), "OUTBOUND_ALLOWED_NUMBERS": fictional(142)}
        | extra
    )


def test_the_outbound_defaults_are_the_contracts() -> None:
    s = Settings.from_env({})
    assert s.outbound_enabled is False
    assert s.max_outbound_per_day == 20
    assert s.max_dial_attempts == 3
    assert s.contacts_retention_days == 30
    assert s.answers_retention_days == 1460
    assert s.max_outbound_call_seconds == 480
    assert s.max_call_seconds == 300  # inbound keeps its own cap (fix 1)
    assert s.max_concurrent_outbound == 1
    assert s.contacts_path.endswith("var/contacts.json")
    assert Settings.from_env({"CONTACTS_PATH": ""}).contacts_path == s.contacts_path
    assert s.intake_signing_key is None and s.outbound_allowed_numbers == frozenset()


def test_the_default_window_is_nine_to_eight_monday_to_saturday() -> None:
    from datetime import time

    w = Settings.from_env({}).call_window
    assert (w.start, w.end, w.days) == (time(9, 0), time(20, 0), frozenset(range(6)))


@pytest.mark.parametrize(
    "name",
    [
        "MAX_OUTBOUND_PER_DAY",
        "MAX_DIAL_ATTEMPTS",
        "CONTACTS_RETENTION_DAYS",
        "ANSWERS_RETENTION_DAYS",
        "MAX_OUTBOUND_CALL_SECONDS",
        "MAX_CONCURRENT_OUTBOUND",
    ],
)
@pytest.mark.parametrize("bad", ["0", "-1", "twenty", "2.5"])
def test_each_new_cap_is_refused_at_start_when_zero_or_nonsense(name: str, bad: str) -> None:
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: bad})


def test_more_than_three_attempts_and_more_than_one_call_at_once_are_refused() -> None:
    with pytest.raises(ValueError, match="MAX_DIAL_ATTEMPTS"):
        Settings.from_env({"MAX_DIAL_ATTEMPTS": "4"})
    for value in ("2", "3"):
        with pytest.raises(ValueError, match="MAX_CONCURRENT_OUTBOUND"):
            Settings.from_env({"MAX_CONCURRENT_OUTBOUND": value})
    assert Settings.from_env({"MAX_DIAL_ATTEMPTS": "1"}).max_dial_attempts == 1


@pytest.mark.parametrize(
    ("name", "most"), [("MAX_OUTBOUND_PER_DAY", 100), ("MAX_OUTBOUND_CALL_SECONDS", 900)]
)
def test_a_cap_past_its_upper_bound_stops_the_process_and_the_bound_itself_is_taken(
    name: str, most: int
) -> None:
    """F2: a typo such as 4800 for 480 seconds, or 200 dials a day, multiplies the bill with nobody calling, so it
    reads as nonsense and stops the process (spec 9.3). The bounds are James's money call, open decision 3."""
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: str(most + 1)})
    field = name.lower()
    assert getattr(Settings.from_env({name: str(most)}), field) == most


@pytest.mark.parametrize("raw", ["07:59-20:00 Mon-Sat", "09:00-21:01 Mon-Sat", "06:00-23:00 Mon-Sat"])
def test_a_call_window_outside_eight_to_nine_stops_the_process(raw: str) -> None:
    """F2: the federal limit is 08:00 to 21:00 at the called party's location (47 CFR 64.1200(c)(1), spec 9.2);
    the window's end is the first minute it does not call, so 21:00 itself is inside."""
    from candidate_line.settings import parse_call_window

    with pytest.raises(ValueError, match="08:00-21:00"):
        parse_call_window(raw)
    with pytest.raises(ValueError, match="CALL_WINDOW"):
        Settings.from_env({"CALL_WINDOW": raw})
    widest = parse_call_window("08:00-21:00 Mon-Sat")
    assert (widest.start.hour, widest.end.hour) == (8, 21)


def test_outbound_enabled_reads_only_zero_or_one() -> None:
    assert Settings.from_env({"OUTBOUND_ENABLED": "0"}).outbound_enabled is False
    assert Settings.from_env(outbound_on()).outbound_enabled is True
    for bad in ("yes", "true", "2"):
        with pytest.raises(ValueError, match="OUTBOUND_ENABLED"):
            Settings.from_env({"OUTBOUND_ENABLED": bad})


@pytest.mark.parametrize(
    "missing",
    [
        "INTAKE_SIGNING_KEY",
        "OUTBOUND_ALLOWED_NUMBERS",
        "TWILIO_LINE_NUMBER",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "PUBLIC_BASE_URL",
    ],
)
def test_outbound_on_with_a_value_missing_stops_the_process(missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        Settings.from_env(outbound_on(**{missing: ""}))


def test_outbound_on_needs_the_line_number_in_e164_form() -> None:
    with pytest.raises(ValueError, match="TWILIO_LINE_NUMBER"):
        Settings.from_env(outbound_on(TWILIO_LINE_NUMBER="5550001"))


def test_the_allow_list_is_a_frozenset_of_us_e164_numbers() -> None:
    s = Settings.from_env(outbound_on(OUTBOUND_ALLOWED_NUMBERS=f" {fictional(142)} ,{fictional(143)}"))
    assert s.outbound_allowed_numbers == frozenset({fictional(142), fictional(143)})


@pytest.mark.parametrize(
    "raw",
    [
        lambda: f"{fictional(142)},",
        lambda: f"{fictional(142)},,{fictional(143)}",
        lambda: fictional(142)[2:],  # the national digits alone
        lambda: fictional(142)[:-1],  # a digit short
        lambda: "+11" + fictional(142)[3:],  # an area code cannot start with 1
        lambda: fictional(142)[:5] + "1" + fictional(142)[6:],  # nor an exchange
        lambda: "+44" + fictional(142)[2:],
    ],
)
def test_an_allow_list_with_an_empty_or_non_e164_entry_is_refused_without_its_digits(raw) -> None:
    value = raw()
    with pytest.raises(ValueError, match="OUTBOUND_ALLOWED_NUMBERS") as refused:
        Settings.from_env(outbound_on(OUTBOUND_ALLOWED_NUMBERS=value))
    digits = "".join(ch for ch in value if ch.isdigit())
    assert digits[-4:] not in str(refused.value)  # the list is a secret; the message names the entry by place


def test_the_secrets_are_never_in_the_settings_repr() -> None:
    s = Settings.from_env(outbound_on())
    assert "test-signing-key" not in repr(s)
    assert fictional(142) not in repr(s) and "0142" not in repr(s)


def test_no_token_key_number_address_or_webhook_url_is_in_the_settings_repr_or_str() -> None:
    """F8: the token, the account SID, the line's and the probe's numbers (the probe's is on the allow-list,
    which DR-025 says is never logged), the Slack webhook, the SNS topic's account id, the SES addresses and the
    public base the webhooks are built on were all printed by repr(settings), so a future log line or a
    traceback that reprs a dataclass would leak them. Every value here is built at run time and fictional."""
    account = "0" * 11 + "7"
    values = {
        "TWILIO_AUTH_TOKEN": "tok-" + "f8" * 8,
        "TWILIO_ACCOUNT_SID": "AC" + "f8" * 16,
        "TWILIO_LINE_NUMBER": fictional(100),
        "TWILIO_PROBE_NUMBER": fictional(142),
        "SLACK_WEBHOOK_URL": "https://hooks.example/services/" + "f8" * 6,
        "SNS_TOPIC_ARN": f"arn:aws:sns:us-east-1:{account}:candidate-line",
        "SES_SENDER": "line@mail.example",
        "SES_RECIPIENTS": "recruiter@mail.example,operator@mail.example",
        "PUBLIC_BASE_URL": "https://f8-tunnel.example",
        "INTAKE_SIGNING_KEY": "key-" + "f8" * 8,
        "OUTBOUND_ALLOWED_NUMBERS": f"{fictional(142)},{fictional(143)}",
    }
    s = Settings.from_env(outbound_on(**values))
    assert s.twilio_auth_token == values["TWILIO_AUTH_TOKEN"]  # still held, only never printed
    shown = repr(s) + str(s)
    for name, value in values.items():
        for part in value.split(","):
            assert part not in shown, name
    assert account not in shown and "0100" not in shown and "0143" not in shown
    assert "brain_provider='anthropic'" in shown  # the settings that are no secret still read


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "09:00-20:00",
        "20:00-09:00 Mon-Sat",
        "09:00-09:00 Mon-Sat",
        "09:00-20:00 Mon-Sun",
        "09:00-20:00 Sun",
        "09:00-20:00 Sat-Mon",
        "09:00-20:00 Mon,Sun",
        "09:00-25:00 Mon-Sat",
        "09:00-20:00 Funday",
        "9-20 Mon-Sat",
    ],
)
def test_a_call_window_that_is_empty_reversed_or_names_sunday_is_refused(raw: str) -> None:
    from candidate_line.settings import parse_call_window

    with pytest.raises(ValueError, match="CALL_WINDOW"):
        parse_call_window(raw)
    if raw:
        with pytest.raises(ValueError, match="CALL_WINDOW"):
            Settings.from_env({"CALL_WINDOW": raw})


def test_a_call_window_reads_ranges_and_lists() -> None:
    from datetime import time

    from candidate_line.settings import parse_call_window

    w = parse_call_window("10:30-18:00 Mon,Wed-Fri")
    assert (w.start, w.end, w.days) == (time(10, 30), time(18, 0), frozenset({0, 2, 3, 4}))
    assert w.middle == time(14, 15)
    assert parse_call_window("09:00-20:00 Sat").days == frozenset({5})


def test_a_probe_answer_case_never_prints_its_pin() -> None:
    """F8's sibling: the probe's answer case is a dataclass holding the PIN it applied with."""
    from candidate_line.probe.dial import AnswerCase

    case = AnswerCase("met", "4" + "7" * 3, ["yes"], "Which suits you?")
    assert case.pin == "4777" and "4777" not in repr(case) and "4777" not in str(case)
