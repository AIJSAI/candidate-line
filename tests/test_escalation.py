import time

from candidate_line.escalation import (
    Escalation,
    EscalationQueue,
    LogPoster,
    SlackWebhookPoster,
    format_message,
)
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
