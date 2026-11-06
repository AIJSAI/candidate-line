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
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from candidate_line.traces import TraceStore

log = logging.getLogger("candidate_line.escalation")

SNS_SUBJECT = "Candidate Line hand-off"
SNS_SUBJECT_MAX = 100  # SNS refuses a longer subject, and it must be one line of printable ASCII
# The kind of hand-off a screen posts when a recruiter must call (DR-025 section 15). Its email is built from the
# reason's fixed parts and never from free text, so no answer, heard word or unmet requirement can reach it.
SCREENING_HAND_OFF = "screening hand-off"

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
    # When the hand-off was raised, in Central time, for the email: the operator reads it hours later.
    raised_at: str = field(default_factory=lambda: central_now())
    # The applicant's record on the cockpit, for a screening hand-off: the answers are read there, never in mail.
    record_url: str | None = None


def central_now() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M")


_WHO = re.compile(r"^(?P<kind>.+?) from (?P<who>[^:]+?)(?::\s*(?P<detail>.*))?$", re.DOTALL)
_CODE_NAME = re.compile(r"^(?P<code>ACME-\d{4}) \((?P<name>[^)]+)\)$")


def _parts(e: Escalation) -> tuple[str, str, str]:
    """The kind of hand-off, who it is from and the detail, from the reason the tools write ("callback request
    from ACME-1022 (Mei Petrov): relocation; best time tomorrow afternoon"). A reason in another shape is kept
    whole as the detail."""
    match = _WHO.match(e.reason.strip())
    if not match:
        return (f"tier {e.tier} hand-off", "", e.reason.strip())
    kind, who, detail = (
        match.group("kind").strip(),
        match.group("who").strip(),
        (match.group("detail") or "").strip(),
    )
    named = _CODE_NAME.match(who)
    if named:
        who = f"{named.group('name')} ({named.group('code')})"
    elif who == "the caller":
        who = "a caller"
    return (kind, who, detail)


def _when(raised_at: str) -> str:
    """ "8:52 PM Central on Wednesday 4 November 2026" from the stored "2026-11-04 20:52"."""
    try:
        stamp = datetime.strptime(raised_at, "%Y-%m-%d %H:%M")
    except ValueError:
        return f"{raised_at} Central"
    return stamp.strftime(_CENTRAL_WORDS)


_CENTRAL_WORDS = "%-I:%M %p Central on %A %-d %B %Y"


def spoken_central(when: datetime) -> str:
    """An instant in the words a recruiter reads it in Central time: "4:05 PM Central on Friday 6 November 2026"."""
    return when.astimezone(ZoneInfo("America/Chicago")).strftime(_CENTRAL_WORDS)


_SCREENING_DETAIL = re.compile(r"^(?P<role>.+?); recruiter call promised by (?P<when>.+)$")


def _screening_email(e: Escalation, who: str, detail: str) -> str:
    """The recruiter's note for a screening hand-off (DR-025 section 15): who, the role, the promised time and the
    record link, and nothing from the answers. Only the reason's two fixed parts are read; anything else in it is
    dropped rather than mailed."""
    parts = _SCREENING_DETAIL.match(detail)
    role = f" for the {parts.group('role')} role" if parts else ""
    when = f" by {parts.group('when')}" if parts else " by the time on the record"
    first = f"{who or 'An applicant'} answered the screening questions{role} on the ACME line, and the line promised that a recruiter will call{when}."
    record = e.record_url or "the applicant's page on the line's cockpit"
    return (
        f"{first}\n"
        "\n"
        f"Read the answers on the applicant's record: {record}\n"
        "\n"
        "What to do: read the answers on the record and call the applicant by the promised time; a person decides "
        "every application.\n"
        "\n"
        f"{_record_line(e)}"
    )


def format_subject(e: Escalation) -> str:
    """One line a coordinator can act on from the inbox list: "Callback request: Mei Petrov (ACME-1022)". Never the
    detail, which may hold free text. Cut to SES's and SNS's limit on one line of printable ASCII."""
    kind, who, detail = _parts(e)
    if who:
        subject = f"{kind[:1].upper()}{kind[1:]}: {who}"
    elif kind == SCREENING_HAND_OFF:
        subject = "Screening hand-off"
    else:
        # A write-up: what to look at, in the recruiter's words ("A call to look at: unanswered question").
        subject = f"A call to look at: {_write_up(detail)[0]}"
    subject = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in subject)
    return subject[:SNS_SUBJECT_MAX]


_NEXT = {
    "callback request": "call the candidate back within one business day, as the FAQ promises (F8.2)",
    "move request": "call the candidate back about the move; the slot stays as booked until a person moves it (F3.2)",
}


# A tier-3 write-up's reasons are the line's own words (tiers.write_ups and the hooks); the recruiter reads them
# in plain words, with what to do about each. The first hand-off emails read in Gmail on 2026-11-05 said "the
# guard replaced a sentence (p08)" and "read the trace", which a recruiter cannot act on.
_WRITE_UPS: tuple[tuple[str, str, str, str], ...] = (
    (
        "the guard replaced a sentence",
        "safety check",
        "the line's safety check replaced one sentence of a reply before it was spoken",
        "read the call; nothing the rules forbid reached the caller, and the replaced sentence is on the call page",
    ),
    (
        "the refusal line was said",
        "unanswered question",
        "a caller asked something the FAQ does not answer, so the line said it could not help with that",
        "listen to the question on the call page; if it deserves an answer, add it to the FAQ or call the caller back",
    ),
    (
        "verification failed",
        "code and PIN did not match",
        "the caller's application code and PIN did not match twice, so the line offered a callback",
        "check the call page for the callback request and call the caller back from the application's own number",
    ),
    (
        "the length cap ended the call",
        "call cut short",
        "the call reached its length cap before the last screening question",
        "read the answers on the applicant's record and call the applicant to finish the questions",
    ),
    (
        "a wrong person answered",
        "wrong person answered",
        "someone who is not the applicant answered the line's call, so this number will not be called again",
        "check the number on the application before anyone calls it",
    ),
    (
        "the pin did not match",
        "PIN did not match",
        "the person who answered the line's call did not give the applicant's PIN twice",
        "call the applicant from the application's own number and confirm the PIN before reading the record",
    ),
    (
        "an opt-out could not be saved",
        "opt-out not saved",
        "a caller asked for no more calls and the request could not be saved",
        "cancel this application's dials by hand on the cockpit",
    ),
)


def _write_up(reason: str) -> tuple[str, list[str], list[str]]:
    """The short name, the plain sentences and the to-dos of a write-up, part by part ("; " joins them). A part no
    table row names is kept in the line's own words, so nothing is lost."""
    shorts: list[str] = []
    sentences: list[str] = []
    todos: list[str] = []
    for part in [x.strip() for x in reason.split(";") if x.strip()]:
        low = part.lower()
        for prefix, short, sentence, todo in _WRITE_UPS:
            if low.startswith(prefix):
                shorts.append(short)
                sentences.append(sentence)
                todos.append(todo)
                break
        else:
            shorts.append(part[:40])
            sentences.append(part)
            todos.append("read the call page")
    return ", ".join(dict.fromkeys(shorts)) or "see the note", sentences, list(dict.fromkeys(todos))


def _record_line(e: Escalation) -> str:
    """The last lines of every note: the call's page on the cockpit, which the recruiter opens to act (through the
    port-forward when the line runs in its container, DR-023), and that nobody reads a reply."""
    return (
        f"Call record {e.call_id}: {e.trace_url} (the line's cockpit).\n"
        "This note was sent by the line itself; nobody reads replies to it."
    )


def format_email(e: Escalation) -> str:
    """The email body, written as a note: who asked for what, when and from which number, what to do, and the call
    record's id. No template lines, no internal words: the first hand-off email of 2026-11-04 arrived as the
    Slack template's bare lines and the operator called it messy."""
    kind, who, detail = _parts(e)
    if kind == SCREENING_HAND_OFF:
        return _screening_email(e, who, detail)
    if not who:
        # A write-up (tier 3) or any hand-off in no "kind from who: detail" shape: plain words, part by part.
        _short, sentences, todos = _write_up(detail)
        first = (
            "The ACME candidate line flagged a call for a person to look at: " + "; ".join(sentences) + "."
        )
        todo = "; ".join(todos)
    else:
        ask = {"callback request": "for a callback", "move request": "to move a first-round slot"}.get(
            kind, f"for {kind}"
        )
        first = f"{who} asked the ACME candidate line {ask}"
        if detail:
            first += f": {detail}"
        first = first.rstrip(".") + "."
        todo = ""
    where = (
        f"The call came from {e.caller} at {_when(e.raised_at)}."
        if e.caller and e.caller != "-"
        else f"The call came in at {_when(e.raised_at)}; no number is on record for it."
    )
    if e.record_url:
        # An applicant's hand-off: the answers are read on the record, never in mail, and the promise is the
        # recruiter's call, not F8.2's coordinator call to the number the caller rang from.
        todo = todo or e.suggested_action
        where += f"\n\nThe applicant's record: {e.record_url}"
    else:
        todo = todo or _NEXT.get(kind, e.suggested_action)
    return f"{first}\n\n{where}\n\nWhat to do: {todo}.\n\n{_record_line(e)}"


def format_message(e: Escalation) -> str:
    text = TEMPLATE.format(
        tier=e.tier,
        call_id=e.call_id,
        caller=e.caller,
        reason=e.reason,
        suggested_action=e.suggested_action,
        trace_url=e.trace_url,
    )
    return f"{text}\nRecord: {e.record_url}" if e.record_url else text


def trace_link(base_url: str, call_id: str) -> str:
    """The cockpit page for one call. The base comes from Settings.cockpit_base_url, so a hand-off posted from a
    tunnel or another host can point at a cockpit the recruiter can reach; a trailing slash is not doubled."""
    return f"{base_url.rstrip('/')}/calls/{urllib.parse.quote(call_id, safe='')}"


def record_link(base_url: str, code: str) -> str:
    """The cockpit page for one application, where the recruiter reads the answers (DR-025 section 16)."""
    return f"{base_url.rstrip('/')}/applicants/{urllib.parse.quote(code, safe='')}"


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

    def post_escalation(self, e: Escalation) -> None:
        """The email form: a subject that says what happened and a body that reads as a note (format_email)."""
        self._publish(format_subject(e), format_email(e))

    def post(self, text: str) -> None:
        self._publish(SNS_SUBJECT, text)

    def _publish(self, subject: str, text: str) -> None:
        try:
            self._client.publish(TopicArn=self._topic_arn, Subject=subject, Message=text)
        except Exception as error:  # noqa: BLE001  (raised again below, as a code with no account id in it)
            # botocore's message names the role and the topic, both with the account id, and the queue writes
            # what it is given into the trace store; the code alone says what went wrong.
            response = getattr(error, "response", None) or {}
            code = response.get("Error", {}).get("Code") or type(error).__name__
            raise RuntimeError(f"SNS publish failed: {code}") from None


class SesPoster:
    """One email per hand-off through Amazon SES from a verified sender, so the note arrives from the line's own
    name with no footer and no raw link (SNS's email channel appends an unsubscribe block with the topic's ARN).
    The task role holds ses:SendEmail on that one identity. In SES's sandbox the recipients must be verified too,
    which the operator's own address is. A failed send falls back to the SNS poster when one is given, so a
    hand-off is never lost to the mail service."""

    channel = "ses"

    def __init__(
        self,
        sender: str,
        recipients: Sequence[str],
        region: str = "us-east-1",
        client: Any | None = None,
        fallback: Poster | None = None,
    ) -> None:
        if not sender or not recipients:
            raise ValueError("SES_SENDER and SES_RECIPIENTS are not both set")
        self._sender = sender
        self._recipients = tuple(recipients)
        self._fallback = fallback
        if client is None:
            import boto3  # here, so text mode and the evals, which never send, do not pay for the import

            client = boto3.client("ses", region_name=region)
        self._client = client

    def post_escalation(self, e: Escalation) -> None:
        try:
            self._client.send_email(
                Source=f"ACME Candidate Line <{self._sender}>",
                Destination={"ToAddresses": list(self._recipients)},
                Message={
                    "Subject": {"Data": format_subject(e), "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": format_email(e), "Charset": "UTF-8"}},
                },
            )
        except Exception as error:  # noqa: BLE001  (reported by its code; the account id never reaches a trace)
            response = getattr(error, "response", None) or {}
            code = response.get("Error", {}).get("Code") or type(error).__name__
            if self._fallback is None:
                raise RuntimeError(f"SES send failed: {code}") from None
            log.warning("SES send failed (%s); the hand-off goes through the fallback channel", code)
            post_escalation = getattr(self._fallback, "post_escalation", None)
            if post_escalation is not None:
                post_escalation(e)
            else:
                self._fallback.post(format_message(e))

    def post(self, text: str) -> None:
        """The plain form, for a poster that is handed text alone."""
        self._client.send_email(
            Source=f"ACME Candidate Line <{self._sender}>",
            Destination={"ToAddresses": list(self._recipients)},
            Message={"Subject": {"Data": SNS_SUBJECT}, "Body": {"Text": {"Data": text}}},
        )


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
                post_escalation = getattr(self._poster, "post_escalation", None)
                if post_escalation is not None:
                    post_escalation(e)  # the email form, where the poster has one
                else:
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


def default_poster(
    webhook_url: str | None,
    sns_topic_arn: str | None = None,
    ses_sender: str | None = None,
    ses_recipients: Sequence[str] = (),
) -> Poster:
    """SES when a sender and recipients are set (the deployment's channel, with SNS as its fallback when a topic is
    set too), SNS when only the topic is, Slack when the webhook is, the log poster otherwise; the same interface
    either way, so a Slack webhook left in the environment never splits the hand-offs over two places."""
    sns = SnsPoster(sns_topic_arn) if sns_topic_arn else None
    if ses_sender and ses_recipients:
        return SesPoster(ses_sender, ses_recipients, fallback=sns)
    if sns is not None:
        return sns
    return SlackWebhookPoster(webhook_url) if webhook_url else LogPoster()


def default_queue(
    store: TraceStore,
    webhook_url: str | None,
    sns_topic_arn: str | None = None,
    ses_sender: str | None = None,
    ses_recipients: Sequence[str] = (),
) -> EscalationQueue:
    """What the phone and text mode run: one queue per process over the room's store. The eval runner passes no
    channel, so an eval never posts to a real one (card 06 submits through `ctx.escalations`)."""
    return EscalationQueue(store, default_poster(webhook_url, sns_topic_arn, ses_sender, ses_recipients))
