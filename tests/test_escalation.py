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
