"""`make voice-regression URL=wss://<host>/media [CASES=...]`: every eval case through the deployed line's audio
path, one at a time, scored from the line's own trace store (DR-024).

Why the store and not the probe's ears: the probe hears Gus through its own Transcribe, which wrote "Section F 2.1"
for F2.1, "2 p.m." for 2 PM and "Bing" for Booking on the first run (2026-11-05), and it cannot hear a tool call, a
tier or a citation at all. The store holds the words the line handed to Polly, the tools it ran, the tier it gave
each turn and the sections it cited, so each check is read where its truth is. What only the audio side can measure
(the turn gaps, when the greeting was heard) still comes from the probe. Why one at a time: the cases share one
live ledger, and two calls at once book against each other's state.

Every check ends PASS, FAIL or UNOBSERVABLE with its reason. UNOBSERVABLE is a check the store cannot settle: a
digit the store masked (spec section 5, Never 4), or a silence turn, which the probe does not hold. A case fails
only on a check the line could have passed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import bisect
import json
import logging
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from candidate_line.brain import Reply
from candidate_line.evals.checks import evaluate
from candidate_line.evals.schema import Case, Check
from candidate_line.probe import in_container
from candidate_line.probe.session import ProbeTranscript
from candidate_line.telephony.media import mask_spoken_digits
from candidate_line.text import straighten
from candidate_line.turn import TurnResult

log = logging.getLogger("candidate_line.probe.regression")

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases"
DEFAULT_REPORT = ROOT / "var" / "voice-regression.md"
CENTRAL = ZoneInfo("America/Chicago")
PASS, FAIL, UNOBSERVABLE = "PASS", "FAIL", "UNOBSERVABLE"
# The container's files, as the Dockerfile and the stack name them (TRACE_STORE_PATH, STATE_PATH) and as
# scripts/deploy.sh names the kill switch. The snapshot sits beside the ledger, on the task's volume.
PATHS = {
    "state": "/app/var/state.json",
    "snapshot": "/app/var/state.json.pre-regression",
    "store": "/app/var/traces.sqlite",
    "kill": "/app/var/kill",
}
SOURCE = Path(in_container.__file__).read_text(encoding="utf-8")
_PACKED = re.compile(re.escape(in_container.BEGIN) + r"([A-Za-z0-9+/=\s]+?)" + re.escape(in_container.END))
_DIGIT_IN_PATTERN = re.compile(r"[0-9]|\\d")
_VERIFIED = re.compile(r"^verified (ACME-\d{4})")
_BOOKED = re.compile(r"^booked (S\d{4}-\d{4})")
MASKED_DIGITS = "the store masks each run of three or more digits in Gus's words"
SILENCE = "the probe speaks the case's lines and holds no silence, so a silence turn is not run by voice"

# The container.


class RemoteError(RuntimeError):
    """The container could not be reached, or did not answer in the expected shape."""


Runner = Callable[[list[str]], str]


def _aws(argv: list[str], timeout: float = 180.0) -> str:
    """Runs one AWS CLI command and returns everything it printed. Its stdin is a pipe that stays open and empty
    until the command exits: an inherited stdin would send the person's keystrokes into the container's shell, and
    an empty one (/dev/null) ends the session at its first read, cutting a long answer off (the first two-case run,
    2026-11-05: "Cannot perform start session: EOF" halfway through the read)."""
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    try:
        assert proc.stdout is not None
        out = proc.stdout.read()
        proc.wait()
    finally:
        killer.cancel()
        if proc.stdin is not None:
            proc.stdin.close()
    return out


def _no_account(text: str) -> str:
    return re.sub(r"\d{12}", "<account>", text)


def unpack(output: str) -> dict[str, Any] | None:
    """The container's answer from the session's output, or None when it is not there. Whitespace inside the
    base64 is dropped, since a terminal session may wrap a long line."""
    found = _PACKED.search(output)
    if found is None:
        return None
    raw = zlib.decompress(base64.b64decode(re.sub(r"\s", "", found.group(1))))
    answer = json.loads(raw)
    return answer if isinstance(answer, dict) else None


def command(args: Mapping[str, Any]) -> str:
    """The `python -c` line that runs in_container.py on these arguments inside the task."""
    program = in_container.program(SOURCE, dict(args))
    packed = base64.b64encode(zlib.compress(program.encode())).decode()
    return f"python -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('{packed}')))\""


class Container:
    """The line's running task, reached as scripts/deploy.sh reaches it for line-off: `aws ecs execute-command` under
    the break-glass admin profile, with the cluster, service and container names deploy.sh uses. Names only: no
    account id and no host is written here, and any twelve-digit number in an error is masked."""

    def __init__(
        self,
        run: Runner = _aws,
        profile: str = "candidate-line-admin",
        region: str = "us-east-1",
        cluster: str = "candidate-line",
        service: str = "candidate-line",
        container: str = "line",
    ) -> None:
        self._run = run
        self._where = ["--profile", profile, "--region", region, "--cluster", cluster]
        self._service = service
        self._container = container
        self._task: str | None = None

    def task(self) -> str:
        if self._task is None:
            out = self._run(
                ["aws", "ecs", "list-tasks", *self._where, "--service-name", self._service]
                + ["--query", "taskArns[0]", "--output", "text"]
            ).strip()
            task = out.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[0-9a-f]{16,64}", task):
                raise RemoteError(f"no running task for the service: {_no_account(out)[-300:]}")
            self._task = task
        return self._task

    def call(self, op: str, **args: Any) -> dict[str, Any]:
        """Runs one operation of in_container.py. Tried twice, since a session can drop before it prints; every
        operation is safe to run again (a snapshot carries this run's token, so its retry is not a leftover)."""
        argv = ["aws", "ecs", "execute-command", *self._where, "--task", self.task()]
        argv += ["--container", self._container, "--interactive"]
        argv += ["--command", command({"op": op, **PATHS, **args})]
        out = ""
        for _ in range(2):
            out = self._run(argv)
            answer = unpack(out)
            if answer is not None:
                return answer
        raise RemoteError(f"no answer from the container for {op}: {_no_account(out)[-400:]}")


# What the store says about one call.


@dataclass(frozen=True)
class Span:
    seq: int
    kind: str
    name: str
    at: float  # the store's started_at, as Unix seconds
    text: str
    meta: Mapping[str, Any]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Span:
        meta = row.get("meta")
        parsed = json.loads(meta) if isinstance(meta, str) and meta else meta
        return cls(
            seq=int(row["seq"]),
            kind=str(row["kind"]),
            name=str(row["name"]),
            at=datetime.fromisoformat(str(row["at"])).timestamp(),
            text=str(row.get("text") or ""),
            meta=parsed if isinstance(parsed, dict) else {},
        )


@dataclass
class StoreTurn:
    """One run of the turn loop on the phone: the finals it answered, its model, tool, cite, hook and tier spans,
    and what Gus then said. A superseded turn was never spoken and its tool effects were taken back (media.py)."""

    at: float  # the first final's time, which places the turn under the probe line it answers
    finals: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    speech: list[str] = field(default_factory=list)
    superseded: bool = False

    def of(self, kind: str) -> list[Span]:
        return [s for s in self.spans if s.kind == kind]

    @property
    def tier(self) -> str | None:
        tiers = self.of("tier")
        return tiers[-1].name if tiers else None


def store_turns(spans: Sequence[Span]) -> tuple[list[str], list[StoreTurn]]:
    """The greeting and the turns, from one call's spans in order. A final opens a turn once the last one has its
    tier or its words; a superseded turn's finals lead the turn after it, as its words did (media.py); Gus's words
    belong to the latest turn waiting for them, so a final that arrives while a reply is still going out cannot take
    that reply for itself."""
    greeting: list[str] = []
    turns: list[StoreTurn] = []
    current: StoreTurn | None = None
    for span in spans:
        if span.kind == "transcribe":
            if span.meta.get("dropped"):
                continue  # a filler the line let go never became a turn
            if current is None or current.tier is not None or current.speech:
                current = StoreTurn(at=span.at)
                turns.append(current)
            current.finals.append(span.text)
        elif span.kind == "speech":
            waiting = next(
                (t for t in reversed(turns) if t.tier is not None and not t.speech and not t.superseded),
                None,
            )
            target = waiting or (turns[-1] if turns else None)
            (greeting if target is None else target.speech).append(span.text)
        elif span.kind == "hook" and span.name == "superseded":
            if current is not None:
                current.superseded = True
                current = StoreTurn(at=current.at, finals=list(current.finals))
                turns.append(current)
        elif current is not None:
            current.spans.append(span)
    return greeting, turns


def assign(turns: Sequence[StoreTurn], starts: Sequence[float]) -> tuple[list[list[StoreTurn]], int]:
    """Each store turn under the probe line it answers: the last line the probe began before the turn's first final.
    The second number counts turns that came before the probe's first line, which only a clock disagreement
    between this machine and the task explains; they go under the first line."""
    by_line: list[list[StoreTurn]] = [[] for _ in starts]
    early = 0
    for turn in turns:
        k = bisect.bisect_right(starts, turn.at) - 1
        if k < 0:
            early += 1
            k = 0
        if by_line:
            by_line[k].append(turn)
    return by_line, early


def _effects(turn: StoreTurn) -> list[tuple[str, str]]:
    """What the turn's tools did to the verified candidate's state: a verification, a booking, a callback."""
    done: list[tuple[str, str]] = []
    for span in turn.of("tool"):
        if span.meta.get("is_error"):
            continue
        if span.name == "verify_caller" and (verified := _VERIFIED.match(span.text)):
            done.append(("verified", verified.group(1)))
        elif span.name == "book_slot":
            booked = _BOOKED.match(span.text)
            done.append(("booked", str(span.meta.get("slot_id") or (booked.group(1) if booked else ""))))
        elif span.name == "request_callback":
            done.append(("callback", ""))
    return done


def states_by_line(
    by_line: Sequence[Sequence[StoreTurn]],
    start: Mapping[str, Mapping[str, Any]],
    end: Mapping[str, Mapping[str, Any]],
) -> list[tuple[dict[str, Any] | None, str]]:
    """The verified candidate's state after each line, and where it came from. After the call's last change the
    container's own ledger is the truth; before it, the state is replayed from the snapshot every case starts from
    and the call's tool spans. Before anyone is verified there is no state, as in text mode."""
    effects = [[e for t in turns if not t.superseded for e in _effects(t)] for turns in by_line]
    out: list[tuple[dict[str, Any] | None, str]] = []
    code: str | None = None
    changed: dict[str, dict[str, Any]] = {}
    for k, line_effects in enumerate(effects):
        for kind, value in line_effects:
            if kind == "verified":
                code = value
            elif code is not None and kind == "booked":
                changed.setdefault(code, {})["booked_slot"] = value
            elif code is not None and kind == "callback":
                changed.setdefault(code, {})["callback_requested"] = True
        later = any(kind != "verified" for rest in effects[k + 1 :] for kind, _ in rest)
        if code is None:
            out.append((None, ""))
        elif not later and code in end:
            out.append((dict(end[code]), "from the container's ledger after the call"))
        elif code in start:
            replayed = {**start[code], **changed.get(code, {})}
            out.append((replayed, "replayed from the snapshot and this call's tool spans"))
        else:
            out.append((None, f"{code} is not in the container's ledger"))
    return out


def _tier_rank(tier: str) -> int:
    return int(tier) if tier.isdigit() else 0


def line_result(turns: Sequence[StoreTurn], state: Mapping[str, Any] | None) -> TurnResult:
    """One probe line's turns as the TurnResult text mode would have built, so the eval's own checks read it. A
    line the phone split into two turns is read as one: its words joined, its tools together, its highest tier."""
    live = [t for t in turns if not t.superseded]
    heard = " ".join(f for t in (live or turns) for f in t.finals)
    spoken = " ".join(s for t in turns for s in t.speech)
    cited = dict.fromkeys(c for t in live for s in t.of("cite") for c in s.name.split() if c != "none")
    tiers = [t.tier for t in live if t.tier is not None]
    return TurnResult(
        heard=heard,
        spoken=spoken,
        reply=Reply(spoken, 0, 0, 0, "store", "store"),
        cited=tuple(cited),
        tools_called=tuple(s.name for t in live for s in t.of("tool")),
        state=None if state is None else dict(state),
        tier=max(tiers, key=_tier_rank) if tiers else None,
    )


# The checks.


def _class_end(pattern: str, start: int) -> int:
    i = start + 1
    if i < len(pattern) and pattern[i] == "^":
        i += 1
    if i < len(pattern) and pattern[i] == "]":
        i += 1
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "]":
            return i
        i += 1
    return -1


def mask_variant(pattern: str) -> re.Pattern[str] | None:
    """The pattern with every digit it names also matching the store's mask, "*", so a check can tell words that did
    not say it from a mask that may hide it. None when the pattern is too unusual to rewrite."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            pair = pattern[i : i + 2]
            out.append(r"[\d*]" if pair == r"\d" else pair)
            i += 2
        elif ch == "[":
            end = _class_end(pattern, i)
            if end < 0:
                return None
            body = pattern[i + 1 : end]
            if not body.startswith("^") and _DIGIT_IN_PATTERN.search(body):
                body = "*" + body
            out.append(f"[{body}]")
            i = end + 1
        elif ch == "{" and (quantifier := re.match(r"\{\d*(?:,\d*)?\}", pattern[i:])):
            out.append(quantifier.group())  # a repeat count, not a digit to say
            i += len(quantifier.group())
        elif ch.isdigit():
            out.append(f"[{ch}*]")
            i += 1
        else:
            out.append(ch)
            i += 1
    try:
        return re.compile("".join(out))
    except re.error:
        return None


def mask_may_hide(pattern: str, spoken: str) -> bool:
    """Whether a masked run in Gus's words could stand where the pattern's digits would match."""
    if "*" not in spoken:
        return False
    variant = mask_variant(pattern)
    return variant is None or variant.search(straighten(spoken)) is not None


def mark(check: Check, result: TurnResult, probe_heard: str = "", state_source: str = "") -> tuple[str, str]:
    """One check against one line, as PASS, FAIL or UNOBSERVABLE with the reason. The verdict is the eval's own
    (checks.evaluate) wherever the store can settle it."""
    name, arg = check.name, str(check.arg)
    heard_by_probe = f"; the probe heard {probe_heard!r}" if probe_heard else ""
    if name == "heard_matches" and _DIGIT_IN_PATTERN.search(arg):
        return UNOBSERVABLE, "unobservable by voice: the store masks digits"
    verdict = evaluate(check, result)
    if name == "spoken_matches":
        if verdict.passed:
            return PASS, verdict.detail
        if mask_may_hide(arg, result.spoken):
            return (
                UNOBSERVABLE,
                f"{MASKED_DIGITS}, and a mask may hide a match: {result.spoken!r}{heard_by_probe}",
            )
        return FAIL, verdict.detail
    if name == "spoken_not_matches":
        if not verdict.passed:
            return FAIL, verdict.detail
        if mask_may_hide(arg, result.spoken):
            hit = re.search(arg, straighten(probe_heard)) if probe_heard else None
            said = f" (the probe's own hearing matches {hit.group(0)!r}: read the call)" if hit else ""
            return UNOBSERVABLE, (
                f"{MASKED_DIGITS}, and a mask may hide the forbidden digits: {result.spoken!r}{heard_by_probe}{said}"
            )
        return PASS, verdict.detail
    if verdict.pending:
        why = {
            "state": state_source or "nobody was verified on the call by this line",
            "tier": "the line wrote no tier for this line",
        }.get(name, verdict.detail)
        return FAIL, why
    if name == "state" and state_source:
        return (PASS if verdict.passed else FAIL), f"{verdict.detail}, {state_source}"
    return (PASS if verdict.passed else FAIL), verdict.detail


# One case.


@dataclass(frozen=True)
class Mark:
    turn: int  # the case's turn index, silence turns included
    check: Check
    verdict: str
    reason: str


@dataclass(frozen=True)
class CaseResult:
    case: Case
    marks: tuple[Mark, ...]
    seconds: float
    gaps_ms: tuple[int, ...] = ()
    # When the probe's ears gave the greeting's final, from the session's start.
    greeting_ms: int | None = None
    clears: int = 0
    error: str | None = None
    notes: tuple[str, ...] = ()
    heard: tuple[str, ...] = ()  # the probe's transcript of both sides, digit runs masked, for the report

    def count(self, verdict: str) -> int:
        return sum(m.verdict == verdict for m in self.marks)

    @property
    def verdict(self) -> str:
        if self.error is not None and not self.heard:
            return "ERROR"
        if self.count(FAIL):
            return FAIL
        return PASS if self.count(PASS) or not self.marks else "UNOBSERVED"

    @property
    def gap_median(self) -> int | None:
        return round(statistics.median(self.gaps_ms)) if self.gaps_ms else None


def _probe_heard(transcript: ProbeTranscript) -> list[str]:
    """What the probe heard Gus say after each of its lines, up to its next line."""
    after: list[list[str]] = []
    for e in transcript.exchanges:
        if e.who == "probe":
            after.append([])
        elif after:
            after[-1].append(e.text)
    return [" ".join(words) for words in after]


def score_case(
    case: Case,
    transcript: ProbeTranscript | None,
    spans: Sequence[Span],
    start_states: Mapping[str, Mapping[str, Any]],
    end_states: Mapping[str, Mapping[str, Any]],
    seconds: float = 0.0,
    error: str | None = None,
) -> CaseResult:
    if transcript is None:
        reason = f"the probe failed before it could report: {error}"
        marks = tuple(Mark(i, c, UNOBSERVABLE, reason) for i, t in enumerate(case.turns) for c in t.checks)
        return CaseResult(case, marks, seconds, error=error)
    _, turns = store_turns(spans)
    lines = [e for e in transcript.exchanges if e.who == "probe"]
    starts = [transcript.started_unix + e.at_ms / 1000 for e in lines]
    by_line, early = assign(turns, starts)
    states = states_by_line(by_line, start_states, end_states)
    probe_heard = _probe_heard(transcript)
    notes: list[str] = []
    if early:
        notes.append(f"{early} store turn(s) came before the probe's first line: the two clocks may disagree")
    marks: list[Mark] = []
    k = -1
    for i, turn in enumerate(case.turns):
        if turn.user is None:
            marks.extend(Mark(i, c, UNOBSERVABLE, SILENCE) for c in turn.checks)
            continue
        k += 1
        if k >= len(starts) or not by_line[k]:
            why = (
                "the call ended before the probe said this line"
                if k >= len(starts)
                else "the line made no turn for this line"
            )
            for check in turn.checks:
                if check.name == "heard_matches" and _DIGIT_IN_PATTERN.search(str(check.arg)):
                    marks.append(
                        Mark(i, check, UNOBSERVABLE, "unobservable by voice: the store masks digits")
                    )
                else:
                    marks.append(Mark(i, check, FAIL, why))
            continue
        superseded = sum(t.superseded for t in by_line[k])
        answered = len(by_line[k]) - superseded
        if superseded or answered > 1:
            notes.append(f"line {k + 1}: {answered} turn(s) answered it, {superseded} superseded")
        state, source = states[k]
        result = line_result(by_line[k], state)
        heard = probe_heard[k] if k < len(probe_heard) else ""
        for check in turn.checks:
            verdict, reason = mark(check, result, heard, source)
            marks.append(Mark(i, check, verdict, reason))
    first_gus = next((e for e in transcript.exchanges if e.who == "gus"), None)
    greeting = (
        first_gus.at_ms if first_gus is not None and (not lines or first_gus.at_ms < lines[0].at_ms) else None
    )
    return CaseResult(
        case,
        tuple(marks),
        seconds,
        gaps_ms=tuple(transcript.gaps_ms()),
        greeting_ms=greeting,
        clears=transcript.clears,
        error=error,
        notes=tuple(notes),
        heard=tuple(
            f"{e.at_ms:6d} ms {e.who:>5}: {mask_spoken_digits(e.text)}"
            + (f" (gap {e.gap_ms} ms)" if e.gap_ms is not None else "")
            for e in transcript.exchanges
        ),
    )


# The run.

Probe = Callable[[str, Case], ProbeTranscript]


@dataclass
class Run:
    started: float
    ended: float = 0.0
    results: list[CaseResult] = field(default_factory=list)
    stopped: str | None = None  # why the run ended before its last case, or never began
    ledger: str = ""  # what happened to the live ledger, in one sentence

    @property
    def code(self) -> int:
        if self.stopped:
            return 2
        return 1 if any(r.verdict in (FAIL, "ERROR") for r in self.results) else 0


def run_regression(
    cases: Sequence[Case],
    url: str,
    container: Container,
    probe: Probe,
    clock: Callable[[], float] = time.time,
    say: Callable[[str], None] = print,
) -> Run:
    """Each case alone against the live line: the ledger put back to the snapshot, the probe's call, the call's
    spans read and scored. The next case starts only after the last one's spans are read, so no two calls overlap.
    The ledger is put back at the end unless a real call came in, whose bookings it would take back."""
    run = Run(started=clock())
    token = uuid.uuid4().hex
    snap = container.call("snapshot", token=token)
    errors = {
        "leftover": f"a snapshot from an earlier run is still at {PATHS['snapshot']}, so that run never restored the "
        "ledger; check whether a real call came since, then restore or delete it by hand",
        "live": "a call is on the line now (a call row with no end in the last ten minutes); try again after it",
        "kill": "the line is off (the kill switch file exists), so every case would hear the closing line",
    }
    if "error" in snap:
        run.stopped = errors.get(str(snap["error"]), f"the snapshot failed: {snap['error']}")
        run.ledger = "no snapshot was taken, so the ledger was not touched"
        run.ended = clock()
        return run
    marker = snap["calls"]
    start_states = snap.get("states") or {}
    try:
        for case in cases:
            call_id = f"probe-{case.id}"  # session.py's callSid: "probe-" before the stream sid, the case id
            reset = container.call("reset", call_id=call_id, calls=marker)
            if reset.get("real_call"):
                run.stopped = f"a real call arrived before {case.id}, so the run stopped there"
                break
            began = clock()
            transcript: ProbeTranscript | None = None
            error: str | None = None
            try:
                transcript = probe(url, case)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                log.exception("the probe failed on %s", case.id)
            read = container.call("read", call_id=call_id, after=int(reset.get("seq", 0)))
            spans = [Span.from_row(row) for row in read.get("spans") or ()]
            result = score_case(
                case, transcript, spans, start_states, read.get("states") or {}, clock() - began, error
            )
            run.results.append(result)
            gap = f"{result.gap_median:,} ms" if result.gap_median is not None else "-"
            say(
                f"{case.id} {result.verdict:<10} pass {result.count(PASS)} fail {result.count(FAIL)} "
                f"unobservable {result.count(UNOBSERVABLE)}, gap median {gap}, {result.seconds:.0f} s"
            )
            if read.get("calls") != marker:
                run.stopped = f"a real call arrived during {case.id}, so the run stopped after it"
                break
    except KeyboardInterrupt:
        run.stopped = "interrupted"
    except RemoteError as exc:
        run.stopped = f"the container stopped answering: {exc}"
    finally:
        try:
            restore = container.call("restore", calls=marker)
            if restore.get("restored"):
                run.ledger = "the live ledger was put back to the snapshot taken at the start"
            elif restore.get("why") == "real call":
                run.ledger = (
                    f"a real call row appeared during the run, so the ledger was NOT put back; the snapshot is "
                    f"kept at {PATHS['snapshot']}"
                )
            else:
                run.ledger = f"the ledger was not put back: {restore.get('why', restore)}"
        except RemoteError as exc:
            run.ledger = f"the restore failed ({exc}); the snapshot is still at {PATHS['snapshot']}"
        run.ended = clock()
    return run


# The report.


def _clock(at: float) -> str:
    when = datetime.fromtimestamp(at, UTC)
    return f"{when.isoformat(timespec='seconds')} ({when.astimezone(CENTRAL).strftime('%H:%M')} CT)"


def table(results: Sequence[CaseResult]) -> list[str]:
    rows = ["| Case | Verdict | Pass | Fail | Unobservable | Turn gap median |", "| - | - | - | - | - | - |"]
    for r in results:
        gap = f"{r.gap_median:,} ms" if r.gap_median is not None else "-"
        rows.append(
            f"| {r.case.id} | {r.verdict} | {r.count(PASS)} | {r.count(FAIL)} | {r.count(UNOBSERVABLE)} | {gap} |"
        )
    return rows


def totals(run: Run) -> str:
    results = run.results
    checks = [m for r in results for m in r.marks]
    by = {v: sum(m.verdict == v for m in checks) for v in (PASS, FAIL, UNOBSERVABLE)}
    verdicts = {v: sum(r.verdict == v for r in results) for v in (PASS, FAIL, "UNOBSERVED", "ERROR")}
    return (
        f"{len(results)} cases: {verdicts[PASS]} pass, {verdicts[FAIL]} fail, {verdicts['UNOBSERVED']} with no "
        f"observable check, {verdicts['ERROR']} probe errors; {len(checks)} checks: {by[PASS]} pass, {by[FAIL]} fail, "
        f"{by[UNOBSERVABLE]} unobservable"
    )


def report(run: Run, commit: str) -> str:
    results = run.results
    gaps = [g for r in results for g in r.gaps_ms]
    greetings = [r.greeting_ms for r in results if r.greeting_ms is not None]
    wall = run.ended - run.started
    lines = [
        f"# Voice regression, {datetime.fromtimestamp(run.started, CENTRAL).strftime('%Y-%m-%d')}",
        "",
        (
            f"Started {_clock(run.started)}, ended {_clock(run.ended)}, wall time {wall / 60:.1f} minutes; runner at "
            f"commit {commit}. Written by `make voice-regression` (candidate_line/probe/regression.py, DR-024)."
        ),
        "",
        "## Method",
        "",
        (
            "- Every case ran alone, one after another, against the deployed line through its media WebSocket (the host "
            "is `make -s deploy STEP=url` and is not written here), played by the direct probe: Polly's Joanna voice for "
            "the caller, the probe's own Transcribe for its ears."
        ),
        (
            "- Before each case the live ledger in the container was put back to a snapshot taken at the start of the "
            "run; after it, the call's spans were read from the container's trace store, both through "
            "`aws ecs execute-command` as `scripts/deploy.sh` does for line-off."
        ),
        (
            "- Each check was scored from the store, where its truth is: spoken_matches and spoken_not_matches against "
            "the speech spans (the words the line handed to Polly); tool_called, state, tier and cites against the "
            "tool, tier and cite spans, through the eval's own `checks.evaluate`; state from the container's ledger "
            "after the call, or replayed from the snapshot and the tool spans for a line before the call's last change; "
            "heard_matches against the transcribe spans, and unobservable when its pattern holds a digit, because the "
            "store masks digits. A check a masked digit run could hide is unobservable; a silence turn is unobservable, "
            "because the probe holds no silence. A case fails only on a check the line could have passed."
        ),
        (
            "- Each store turn sits under the probe line it answers by time: the last line the probe began before the "
            "turn's first final (this machine's clock against the task's)."
        ),
        (
            "- The audio side is the probe's own clock: a turn gap runs from the probe's last frame of its line to the "
            "first frame of Gus's reply reaching it (session.py); the greeting time runs from the session's start to "
            "the probe's transcriber final of the greeting."
        ),
        "",
        "## Summary",
        "",
        *table(results),
        "",
        totals(run) + ".",
        "",
        f"The ledger: {run.ledger}.",
    ]
    if run.stopped:
        lines += ["", f"The run stopped early: {run.stopped}."]
    lines += ["", "## The audio side", ""]
    if gaps:
        lines.append(
            f"- Turn gap: median {statistics.median(gaps):,.0f} ms, worst {max(gaps):,} ms, over {len(gaps)} replies "
            f"in {sum(bool(r.gaps_ms) for r in results)} cases."
        )
    if greetings:
        lines.append(
            f"- Greeting heard at: median {statistics.median(greetings):,.0f} ms, worst {max(greetings):,} ms, "
            f"over {len(greetings)} calls."
        )
    lines.append(f"- Clears (barge-ins the line sent): {sum(r.clears for r in results)}.")
    lines += ["", "## Checks that did not pass", ""]
    if all(m.verdict == PASS for r in results for m in r.marks) and not any(
        r.notes or r.error for r in results
    ):
        lines += ["None.", ""]
    for r in results:
        missed = [m for m in r.marks if m.verdict != PASS]
        if not missed and not r.notes and r.error is None:
            continue
        lines.append(f"### {r.case.id} {r.verdict}: {r.case.title}")
        lines.append("")
        if r.error:
            lines.append(f"- probe error: {r.error}")
        for note in r.notes:
            lines.append(f"- note: {note}")
        for m in missed:
            lines.append(f"- turn {m.turn} {m.verdict} {m.check.name} `{m.check.arg!r}`: {m.reason}")
        lines.append("")
    lines += ["## The calls as the probe heard them (digit runs masked)", ""]
    for r in results:
        lines += [f"### {r.case.id}", "", "```", *r.heard, "```", ""]
    return "\n".join(lines).rstrip() + "\n"


def summary(run: Run) -> str:
    rows = [f"{'case':<8} {'verdict':<11} {'pass':>4} {'fail':>4} {'unobs':>5}  turn gap median"]
    for r in run.results:
        gap = f"{r.gap_median:,} ms" if r.gap_median is not None else "-"
        rows.append(
            f"{r.case.id:<8} {r.verdict:<11} {r.count(PASS):>4} {r.count(FAIL):>4} {r.count(UNOBSERVABLE):>5}  {gap}"
        )
    rows.append(totals(run))
    rows.append(f"wall time {(run.ended - run.started) / 60:.1f} minutes; the ledger: {run.ledger}")
    if run.stopped:
        rows.append(f"STOPPED: {run.stopped}")
    return "\n".join(rows)


def commit_label() -> str:
    """The runner's commit, and whether the tree had changes on top of it, so a report says what code scored it."""
    from candidate_line.evals.runner import git_commit

    try:
        commit = git_commit()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit} plus uncommitted changes" if dirty else commit


def _direct_probe(voice: str) -> Probe:
    from candidate_line.probe.direct import run_direct
    from candidate_line.settings import Settings

    settings = Settings.from_env()

    def run(url: str, case: Case) -> ProbeTranscript:
        return asyncio.run(run_direct(url, case, settings, voice))

    return run


def voice_cases(cases: list[Any]) -> tuple[list[Any], list[str]]:
    """The cases the direct probe can run, and the ids it cannot: an outbound case is the line's call to an
    applicant, seeded from a dial record, which only the dialled probe's answer mode exercises (DR-025 section 18)."""
    runnable = [case for case in cases if getattr(case, "outbound", None) is None]
    return runnable, [case.id for case in cases if getattr(case, "outbound", None) is not None]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="every eval case through the deployed line's audio path, one at a time, scored from its store"
    )
    parser.add_argument("--url", required=True, help="the line's media WebSocket, wss://<host>/media")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--voice", default="Joanna", help="the probe's Polly voice; not Gus's")
    parser.add_argument("cases", nargs="*", type=Path, help="case files (default: every file in evals/cases)")
    args = parser.parse_args(argv)
    if not args.url.startswith(("ws://", "wss://")):
        print(
            "--url must be the line's media WebSocket, wss://<host>/media (make -s deploy STEP=url gives the host)"
        )
        return 2
    from candidate_line.probe.direct import load_case
    from candidate_line.settings import Settings

    if not Settings.from_env().twilio_auth_token:
        print(
            "TWILIO_AUTH_TOKEN is not set, and the deployed line opens a stream only with a token: . scripts/env.sh"
        )
        return 2
    paths = args.cases or sorted(CASES.glob("*.yaml"))
    cases, dialled = voice_cases([load_case(path) for path in paths])
    if dialled:
        print(
            f"{len(dialled)} outbound case(s) left to the dialled probe (make probe-answer, DR-025): {', '.join(dialled)}"
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    # The probe's own log (its event counts, a stream the line closed) goes beside the report, not over the table.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=str(args.report.with_suffix(".log")),
        filemode="w",
    )
    print(f"{len(cases)} cases, one at a time; the probe's log is {args.report.with_suffix('.log')}")
    run = run_regression(cases, args.url, Container(), _direct_probe(args.voice))
    args.report.write_text(report(run, commit_label()), encoding="utf-8")
    print(summary(run))
    print(f"report: {args.report}")
    return run.code


if __name__ == "__main__":
    sys.exit(main())
