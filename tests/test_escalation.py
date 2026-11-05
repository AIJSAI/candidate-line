import logging
import time

import pytest

from candidate_line.escalation import (
    SNS_SUBJECT,
    Escalation,
    EscalationQueue,
    LogPoster,
    SlackWebhookPoster,
    SnsPoster,
    default_poster,
    default_queue,
    format_message,
    trace_link,
)
from candidate_line.settings import DEFAULT_COCKPIT_BASE_URL, Settings
from candidate_line.traces import TraceStore

E = Escalation(
    "c1",
    "notify",
    "asked to move a second time",
    "call back within the hour",
    "http://127.0.0.1:8001/calls/c1",
)


def test_the_message_carries_tier_reason_action_and_trace_link() -> None:
    text = format_message(E)
    for piece in ("notify", "c1", "second time", "within the hour", "/calls/c1", "closes the loop"):
        assert piece in text


def test_the_message_names_the_caller_from_the_stores_call_row() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA7", "voice", caller="+15555550100")
    row = store.call("CA7")
    assert row is not None and row.caller_masked is not None
    e = Escalation(
        "CA7",
        "2",
        "a second move",
        "call the candidate",
        trace_link(DEFAULT_COCKPIT_BASE_URL, "CA7"),
        caller=row.caller_masked,
    )
    text = format_message(e)
    assert "Caller: ***-***-0100" in text and "5555550100" not in text
    assert "Caller: -" in format_message(E)  # text mode has no number, and the field still reads


def test_the_trace_link_is_the_cockpit_page_for_the_call() -> None:
    assert trace_link("http://127.0.0.1:8001", "CA1") == "http://127.0.0.1:8001/calls/CA1"
    assert (
        trace_link("https://cockpit.example/", "text-1a2b3c4d")
        == "https://cockpit.example/calls/text-1a2b3c4d"
    )


def test_the_log_poster_shows_the_hand_off_on_stderr_and_in_the_log(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    poster = LogPoster()
    with caplog.at_level(logging.INFO, logger="candidate_line.escalation"):
        poster.post(format_message(E))
    out, err = capsys.readouterr()
    assert err.startswith("[hand-off] Candidate Line: notify on call c1") and out == ""
    assert poster.posted == [format_message(E)]  # the in-memory list the tests read is kept
    assert [r.getMessage() for r in caplog.records] == [f"[hand-off] {format_message(E)}"]


def wait_for(predicate, seconds: float = 2.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_submit_returns_at_once_and_the_worker_posts_and_records() -> None:
    store = TraceStore(":memory:")
    store.start_call("c1", "text")
    poster = LogPoster()
    q = EscalationQueue(store, poster)
    started = time.perf_counter()
    assert q.submit(E) is True
    assert time.perf_counter() - started < 0.05
    wait_for(lambda: poster.posted)
    wait_for(lambda: store.escalations("c1") and store.escalations("c1")[0].posted_at)
    row = store.escalations("c1")[0]
    assert row.channel == "log" and row.post_error is None and row.reply is None
    q.close()


class FailingPoster(LogPoster):
    channel = "slack"

    def post(self, text: str) -> None:
        raise RuntimeError("webhook answered 500")


def test_a_failed_post_is_recorded_against_the_call_and_never_raised() -> None:
    store = TraceStore(":memory:")
    q = EscalationQueue(store, FailingPoster())
    assert q.submit(E) is True
    wait_for(lambda: store.escalations("c1") and store.escalations("c1")[0].post_error)
    assert "webhook answered 500" in store.escalations("c1")[0].post_error
    assert store.escalations("c1")[0].posted_at is None
    q.close()


def test_a_full_queue_drops_and_counts_instead_of_blocking() -> None:
    class Slow(LogPoster):
        def post(self, text: str) -> None:
            time.sleep(0.2)
            super().post(text)

    q = EscalationQueue(TraceStore(":memory:"), Slow(), maxsize=1)
    results = [q.submit(E) for _ in range(4)]
    assert results[0] is True and False in results and q.dropped >= 1
    q.close()


def test_slack_poster_needs_its_url(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    try:
        SlackWebhookPoster()
    except ValueError as error:
        assert "SLACK_WEBHOOK_URL" in str(error)
    else:
        raise AssertionError("a missing webhook URL must be refused at construction")


def test_default_queue_posts_to_the_log_without_a_webhook_and_drains_before_exit() -> None:
    from candidate_line.escalation import LogPoster, default_poster, default_queue

    assert isinstance(default_poster(None), LogPoster)
    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    q = default_queue(store, None)
    q.submit(Escalation("CA1", "2", "a second move", "call the candidate", "http://127.0.0.1:8001/calls/CA1"))
    q.drain()
    [row] = store.escalations("CA1")
    assert row.posted_at is not None and q._poster.posted  # type: ignore[attr-defined]


# A synthetic topic: the zero account id belongs to nobody, and us-west-2 is not the line's region, so a client
# built for it shows the region came from the ARN.
TOPIC = "arn:aws:sns:us-west-2:000000000000:candidate-line-hand-offs"


class FakeSns:
    """Stands in for boto3's SNS client: records each publish, or raises what it is given. No network."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.published: list[dict[str, str]] = []
        self._raises = raises

    def publish(self, **kwargs: str) -> dict[str, str]:
        if self._raises is not None:
            raise self._raises
        self.published.append(kwargs)
        return {"MessageId": "m-1"}


def test_the_sns_poster_publishes_the_hand_off_to_the_topic_with_its_subject() -> None:
    client = FakeSns()
    poster = SnsPoster(TOPIC, client=client)
    poster.post(format_message(E))
    assert poster.channel == "sns"
    assert client.published == [
        {"TopicArn": TOPIC, "Subject": "Candidate Line hand-off", "Message": format_message(E)}
    ]
    assert SNS_SUBJECT == "Candidate Line hand-off"


def test_the_sns_poster_refuses_a_missing_or_wrong_topic_without_echoing_it() -> None:
    for bad in (None, "", "not-an-arn", "arn:aws:s3:::a-bucket", "arn:aws:sns::000000000000:t"):
        with pytest.raises(ValueError, match="SNS_TOPIC_ARN") as caught:
            SnsPoster(bad, client=FakeSns())
        assert "000000000000" not in str(caught.value)


class ClientError(Exception):
    """Shaped as botocore's: a message that names the account, and the error code in `response`."""

    def __init__(self) -> None:
        super().__init__(
            "User: arn:aws:sts::000000000000:assumed-role/line/task is not authorized to perform: SNS:Publish "
            f"on resource: {TOPIC}"
        )
        self.response = {"Error": {"Code": "AuthorizationError", "Message": str(self)}}


def test_a_failed_publish_is_recorded_by_its_code_and_never_with_the_account_id() -> None:
    store = TraceStore(":memory:")
    q = EscalationQueue(store, SnsPoster(TOPIC, client=FakeSns(raises=ClientError())))
    assert q.submit(E) is True
    q.drain()
    [row] = store.escalations("c1")
    assert row.channel == "sns" and row.posted_at is None
    assert row.post_error == "RuntimeError: SNS publish failed: AuthorizationError"
    q.close()
    with pytest.raises(RuntimeError, match="SNS publish failed: TimeoutError"):
        SnsPoster(TOPIC, client=FakeSns(raises=TimeoutError("connect to sns.us-west-2"))).post("x")


def test_the_sns_client_is_built_for_the_topics_own_region(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    built: list[tuple[str, str | None]] = []

    def client(service: str, region_name: str | None = None) -> FakeSns:
        built.append((service, region_name))
        return FakeSns()

    monkeypatch.setattr(boto3, "client", client)
    SnsPoster(TOPIC)
    assert built == [("sns", "us-west-2")]


def test_default_poster_picks_sns_then_slack_then_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    monkeypatch.setattr(boto3, "client", lambda service, region_name=None: FakeSns())
    hook = "https://hooks.example/T0/B0/x"
    assert isinstance(default_poster(None, TOPIC), SnsPoster)
    assert isinstance(default_poster(hook, TOPIC), SnsPoster)  # both set: SNS, the deployment's channel
    assert isinstance(default_poster(hook, None), SlackWebhookPoster)
    assert isinstance(default_poster(hook), SlackWebhookPoster)  # text mode's call, unchanged
    assert isinstance(default_poster(None, None), LogPoster)
    q = default_queue(TraceStore(":memory:"), hook, TOPIC)
    assert q._poster.channel == "sns"  # type: ignore[attr-defined]
    q.close()


def test_the_sns_topic_comes_from_settings() -> None:
    assert Settings.from_env({}).sns_topic_arn is None
    assert Settings.from_env({"SNS_TOPIC_ARN": ""}).sns_topic_arn is None
    assert Settings.from_env({"SNS_TOPIC_ARN": TOPIC}).sns_topic_arn == TOPIC


def test_the_queue_sends_the_email_form_to_a_poster_that_has_one() -> None:
    from candidate_line.escalation import SnsPoster, format_email, format_subject

    client = FakeSns()
    store = TraceStore(":memory:")
    e = Escalation(
        call_id="CA1",
        tier="2",
        reason="callback request from ACME-3233 (Hannah Haddad): relocation; best time tomorrow afternoon",
        suggested_action="call the candidate back",
        trace_url="http://127.0.0.1:8001/calls/CA1",
        caller="***-***-0657",
        raised_at="2026-11-04 20:15",
    )
    queue = EscalationQueue(store, SnsPoster(TOPIC, client=client))
    queue.submit(e)
    queue.drain()
    [published] = client.published
    assert published["Subject"] == "Callback request: Hannah Haddad (ACME-3233)"
    assert published["Message"] == format_email(e)
    body = published["Message"]
    assert "relocation; best time tomorrow afternoon" in body
    assert (
        "***-***-0657" in body
        and "call the candidate back" in body
        and "8:15 PM Central on Wednesday 4 November 2026" in body
    )
    assert "9683" not in body
    assert format_subject(e) == published["Subject"]


def test_the_subject_is_one_short_ascii_line() -> None:
    from candidate_line.escalation import SNS_SUBJECT_MAX, format_subject

    long = Escalation(
        "CA2", "2", "move request from ACME-6792 (Priya Marchetti)" + ": " + "x" * 300, "a", "u"
    )
    assert format_subject(long) == "Move request: Priya Marchetti (ACME-6792)"
    odd = Escalation("CA3", "3", "guard\u00a0hit\nagain" + ": " + "y" * 300, "a", "u")
    subject = format_subject(odd)
    assert (
        "\n" not in subject and len(subject) <= SNS_SUBJECT_MAX and all(32 <= ord(c) < 127 for c in subject)
    )
    bare = Escalation("CA4", "3", "", "a", "u")
    assert format_subject(bare) == "Tier 3 hand-off"


class FakeSes:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    def send_email(self, **kwargs: object) -> dict[str, str]:
        if self.fail is not None:
            raise self.fail
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}


def test_the_ses_poster_sends_the_note_from_the_lines_name_to_the_operator() -> None:
    from candidate_line.escalation import SesPoster, format_email

    ses = FakeSes()
    e = Escalation(
        call_id="CA9",
        tier="2",
        reason="callback request from ACME-1022 (Mei Petrov): relocation; best time tomorrow afternoon",
        suggested_action="call the candidate back",
        trace_url="u",
        caller="***-***-0657",
        raised_at="2026-11-04 20:52",
    )
    SesPoster("ops@example.test", ["ops@example.test"], client=ses).post_escalation(e)
    [sent] = ses.sent
    assert sent["Source"] == "ACME Candidate Line <ops@example.test>"
    assert sent["Destination"] == {"ToAddresses": ["ops@example.test"]}
    assert sent["Message"]["Subject"]["Data"] == "Callback request: Mei Petrov (ACME-1022)"
    body = sent["Message"]["Body"]["Text"]["Data"]
    assert body == format_email(e)
    assert body.startswith(
        "Mei Petrov (ACME-1022) asked the ACME candidate line for a callback: relocation; best time tomorrow afternoon."
    )
    assert "The call came from ***-***-0657 at 8:52 PM Central on Wednesday 4 November 2026." in body
    assert "What to do: call the candidate back within one business day, as the FAQ promises (F8.2)." in body
    assert "Call record CA9" in body and "port-forward" not in body and "unsubscribe" not in body


def test_a_failed_ses_send_goes_through_the_sns_fallback() -> None:
    from candidate_line.escalation import SesPoster, SnsPoster

    sns = FakeSns()
    poster = SesPoster(
        "ops@example.test",
        ["ops@example.test"],
        client=FakeSes(fail=RuntimeError("down")),
        fallback=SnsPoster(TOPIC, client=sns),
    )
    e = Escalation(
        "CA10",
        "2",
        "move request from ACME-6792 (Priya Marchetti): booked Monday, prefers Tuesday; moves used 0",
        "a",
        "u",
        caller="***-***-0001",
    )
    poster.post_escalation(e)
    [published] = sns.published
    assert published["Subject"] == "Move request: Priya Marchetti (ACME-6792)"
    assert (
        "asked the ACME candidate line to move a first-round slot: booked Monday, prefers Tuesday; moves used 0."
        in published["Message"]
    )
    assert "the slot stays as booked until a person moves it (F3.2)" in published["Message"]


def test_a_hand_off_with_no_number_says_so_and_an_unverified_caller_is_a_caller() -> None:
    from candidate_line.escalation import format_email, format_subject

    e = Escalation(
        "probe-1",
        "2",
        "callback request from the caller: no reason given; best time not given",
        "a",
        "u",
        raised_at="2026-11-04 20:40",
    )
    assert format_subject(e) == "Callback request: a caller"
    body = format_email(e)
    assert body.startswith(
        "a caller asked the ACME candidate line for a callback: no reason given; best time not given."
    )
    assert "no number is on record for it" in body


# The screening hand-off (DR-025 section 15, fix 9): the record link and the promised time, never an answer.

SCREENING = Escalation(
    call_id="CA-out",
    tier="2",
    reason=(
        "screening hand-off from ACME-3108 (Lerato): Home Care Aide; recruiter call promised by "
        "4:05 PM Central on Friday 6 November 2026"
    ),
    suggested_action="read the answers on the applicant's record and call them by the promised time",
    trace_url="http://127.0.0.1:8001/calls/CA-out",
    caller="***-***-0142",
    raised_at="2026-11-05 16:05",
    record_url="http://127.0.0.1:8001/applicants/ACME-3108",
)


def test_the_screening_email_names_who_the_role_the_promised_time_and_the_record_link() -> None:
    from candidate_line.escalation import format_email, format_subject

    assert format_subject(SCREENING) == "Screening hand-off: Lerato (ACME-3108)"
    assert format_email(SCREENING) == (
        "Lerato (ACME-3108) answered the screening questions for the Home Care Aide role on the ACME line, and the "
        "line promised that a recruiter will call by 4:05 PM Central on Friday 6 November 2026.\n"
        "\n"
        "Read the answers on the applicant's record: http://127.0.0.1:8001/applicants/ACME-3108\n"
        "\n"
        "What to do: read the answers on the record and call the applicant by the promised time; a person decides "
        "every application.\n"
        "\n"
        "Call record CA-out, on the line's cockpit. This note was sent by the line itself; nobody reads replies to it."
    )


def test_the_screening_email_drops_anything_but_the_reasons_fixed_parts() -> None:
    from dataclasses import replace

    from candidate_line.escalation import format_email

    # A reason in any other shape is never mailed as it stands: its free words could hold an answer.
    odd = replace(
        SCREENING, reason="screening hand-off from ACME-3108 (Lerato): said no to weekends", record_url=None
    )
    body = format_email(odd)
    assert "weekends" not in body and "said no" not in body and "***-***-0142" not in body
    assert body.startswith("Lerato (ACME-3108) answered the screening questions on the ACME line")
    assert "by the time on the record" in body and "the applicant's page on the line's cockpit" in body


def test_the_slack_form_of_a_screening_hand_off_carries_the_record_link() -> None:
    assert format_message(SCREENING).endswith("\nRecord: http://127.0.0.1:8001/applicants/ACME-3108")
    assert "Record:" not in format_message(E)


def test_the_record_link_is_the_cockpit_page_for_the_application() -> None:
    from candidate_line.escalation import record_link, spoken_central

    assert (
        record_link("https://cockpit.example/", "ACME-3108") == "https://cockpit.example/applicants/ACME-3108"
    )
    from datetime import UTC, datetime

    assert (
        spoken_central(datetime(2026, 11, 6, 22, 5, tzinfo=UTC))
        == "4:05 PM Central on Friday 6 November 2026"
    )
