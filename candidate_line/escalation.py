"""One line to a channel the recruiter already uses, posted from a queue so a slow channel never slows a turn.

Why a queue and a thread: the turn loop calls `submit` and returns in microseconds; the worker records the
escalation in the trace store, posts it, and records the outcome. Why the reply comes back through the cockpit:
a Slack incoming webhook is one-way, and the loop closes when a person logs what they did against the call
(DR-012's reply box), which is the same place the recruiter reads the trace. The rule for which tier posts is
written live with the tiers; this module only knows how to post.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from candidate_line.traces import TraceStore

TEMPLATE = (
    "Candidate Line: {tier} on call {call_id}\n"
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


def format_message(e: Escalation) -> str:
    return TEMPLATE.format(
        tier=e.tier,
        call_id=e.call_id,
        reason=e.reason,
        suggested_action=e.suggested_action,
        trace_url=e.trace_url,
    )


class Poster(Protocol):
    channel: str

    def post(self, text: str) -> None: ...


class SlackWebhookPoster:
    """Slack's incoming webhook: a JSON post with one field. The URL is a secret and comes from the environment."""

    channel = "slack"

    def __init__(self, url: str | None = None, timeout: float = 5.0) -> None:
        self._url = url or os.environ.get("SLACK_WEBHOOK_URL")
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


class LogPoster:
    """No channel: the message is kept in memory. Text mode and the tests use it."""

    channel = "log"

    def __init__(self) -> None:
        self.posted: list[str] = []

    def post(self, text: str) -> None:
        self.posted.append(text)


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

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout)
