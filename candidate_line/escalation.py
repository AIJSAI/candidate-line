"""One line to a channel the recruiter already uses, posted from a queue so a slow channel never slows a turn.

Why a queue and a thread: the turn loop calls `submit` and returns in microseconds; the worker records the
escalation in the trace store, posts it, and records the outcome. Why the reply comes back through the cockpit:
an SNS email and a Slack incoming webhook are both one-way, and the loop closes when a person logs what they did
against the call (DR-012's reply box), which is the same place the recruiter reads the trace. Why SNS in the
deployment: the coordinator reads email already, and the container's own role can publish with no secret to store
(DR-021). The rule for which tier posts is written live with the tiers; this module only knows how to post.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from candidate_line.traces import TraceStore

log = logging.getLogger("candidate_line.escalation")

SNS_SUBJECT = "Candidate Line hand-off"

TEMPLATE = (
    "Candidate Line: {tier} on call {call_id}\n"
    "Caller: {caller}\n"
    "Why: {reason}\n"
    "Suggested next action: {suggested_action}\n"
    "Trace: {trace_url}\n"
    "Log what you did on the trace page; that closes the loop."
)


@dataclass(frozen=True)
class Escalation:
    call_id: str
    tier: str
    reason: str
    suggested_action: str
    trace_url: str
    # The masked number from the store's call row (TraceStore.call), so the recruiter knows who to ring back
    # without opening the trace; "-" in text mode, where there is no number. Never a raw number (AGENTS.md rule 7).
    caller: str = "-"


def format_message(e: Escalation) -> str:
    return TEMPLATE.format(
        tier=e.tier,
        call_id=e.call_id,
        caller=e.caller,
        reason=e.reason,
        suggested_action=e.suggested_action,
        trace_url=e.trace_url,
    )


def trace_link(base_url: str, call_id: str) -> str:
    """The cockpit page for one call. The base comes from Settings.cockpit_base_url, so a hand-off posted from a
    tunnel or another host can point at a cockpit the recruiter can reach; a trailing slash is not doubled."""
    return f"{base_url.rstrip('/')}/calls/{urllib.parse.quote(call_id, safe='')}"


class Poster(Protocol):
    channel: str

    def post(self, text: str) -> None: ...


class SlackWebhookPoster:
    """Slack's incoming webhook: a JSON post with one field. The URL is a secret and comes from the environment."""

    channel = "slack"

    def __init__(self, url: str | None = None, timeout: float = 5.0) -> None:
        self._url = url  # from Settings.slack_webhook_url through default_queue; no os.environ here (DR-004)
        if not self._url:
            raise ValueError("SLACK_WEBHOOK_URL is not set (make secret NAME=SLACK_WEBHOOK_URL)")
        self._timeout = timeout

    def post(self, text: str) -> None:
        body = json.dumps({"text": text}).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            if response.status // 100 != 2:
                raise RuntimeError(f"webhook answered {response.status}")


class SnsPoster:
    """One SNS Publish per hand-off to a topic whose subscribers are the coordinator's email addresses.

    The container's task role holds sns:Publish on this one topic and nothing else, so no key or webhook is
    stored for it, and the role cannot send to anyone the topic does not already list. The client is built for
    the topic's own region, read from its ARN, since a publish to another region's endpoint is refused. The ARN
    holds the account id, so it is never logged, and a failed publish is reported by its error code alone.
    """

    channel = "sns"

    def __init__(self, topic_arn: str | None, client: Any | None = None) -> None:
        if not topic_arn:
            raise ValueError("SNS_TOPIC_ARN is not set")
        parts = topic_arn.split(":")
        if len(parts) != 6 or parts[0] != "arn" or parts[2] != "sns" or not parts[3] or not parts[5]:
            raise ValueError("SNS_TOPIC_ARN is not an SNS topic ARN")
        self._topic_arn = topic_arn
        if client is None:
            import boto3  # here, so text mode and the evals, which never publish, do not pay for the import

            client = boto3.client("sns", region_name=parts[3])
        self._client = client

    def post(self, text: str) -> None:
        try:
            self._client.publish(TopicArn=self._topic_arn, Subject=SNS_SUBJECT, Message=text)
        except Exception as error:  # noqa: BLE001  (raised again below, as a code with no account id in it)
            # botocore's message names the role and the topic, both with the account id, and the queue writes
            # what it is given into the trace store; the code alone says what went wrong.
            response = getattr(error, "response", None) or {}
            code = response.get("Error", {}).get("Code") or type(error).__name__
            raise RuntimeError(f"SNS publish failed: {code}") from None


class LogPoster:
    """No channel: the message is kept in memory and shown. Text mode, the eval runner and the tests use it."""

    channel = "log"

    def __init__(self) -> None:
        self.posted: list[str] = []

    def post(self, text: str) -> None:
        self.posted.append(text)
        # A hand-off nobody can see is no hand-off: with no Slack webhook the room still watches the post land, on
        # stderr so it never mixes into text mode's answers on stdout, and in the log beside the turn lines.
        print(f"[hand-off] {text}", file=sys.stderr, flush=True)
        log.info("[hand-off] %s", text)


class EscalationQueue:
    def __init__(self, store: TraceStore, poster: Poster, maxsize: int = 100) -> None:
        self._store = store
        self._poster = poster
        self._queue: queue.Queue[Escalation | None] = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self._thread = threading.Thread(target=self._work, name="escalations", daemon=True)
        self._thread.start()

    def submit(self, e: Escalation) -> bool:
        """Never blocks the turn. False means the queue was full and the escalation was dropped, counted."""
        try:
            self._queue.put_nowait(e)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def _work(self) -> None:
        while True:
            e = self._queue.get()
            if e is None:
                return
            escalation_id = self._store.add_escalation(
                e.call_id, e.tier, e.reason, e.suggested_action, self._poster.channel
            )
            try:
                self._poster.post(format_message(e))
                self._store.mark_posted(escalation_id)
            except Exception as error:  # noqa: BLE001  (any failure is recorded against the call, never raised into a turn)
                self._store.mark_posted(escalation_id, error=f"{type(error).__name__}: {error}")
            finally:
                self._queue.task_done()

    def drain(self, timeout: float = 5.0) -> None:
        """Waits, with a bound, until every submitted escalation has been posted or recorded as failed. Text mode
        and the eval runner call it before they exit, because the worker is a daemon thread and a post still in
        the queue would otherwise die with the process (the dry run of card 06)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout)


def default_poster(webhook_url: str | None, sns_topic_arn: str | None = None) -> Poster:
    """SNS when the topic is set, Slack when the webhook is, the log poster otherwise; the same interface either
    way. Both set means SNS, the deployment's channel, so a Slack webhook left in the environment never splits
    the hand-offs over two places."""
    if sns_topic_arn:
        return SnsPoster(sns_topic_arn)
    return SlackWebhookPoster(webhook_url) if webhook_url else LogPoster()


def default_queue(
    store: TraceStore, webhook_url: str | None, sns_topic_arn: str | None = None
) -> EscalationQueue:
    """What the phone and text mode run: one queue per process over the room's store. The eval runner passes no
    channel, so an eval never posts to a real one (card 06 submits through `ctx.escalations`)."""
    return EscalationQueue(store, default_poster(webhook_url, sns_topic_arn))
