import logging
import time

import pytest

from candidate_line.escalation import (
    Escalation,
    EscalationQueue,
    LogPoster,
    SlackWebhookPoster,
    format_message,
    trace_link,
)
from candidate_line.settings import DEFAULT_COCKPIT_BASE_URL
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
