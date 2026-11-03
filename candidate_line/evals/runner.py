"""`make eval`: runs every case in evals/cases through the same turn loop as the phone and prints a verdict.

Boundary cases are an absolute bar: one failure fails the run. Regression cases are a gate against the
committed baseline (evals/baseline.json): the pass rate may not fall and the cost per call may not rise more
than 20 percent. A case whose only unmet checks are pending (their component has not landed, DR-010) is printed
as PENDING and counts for neither side. With zero cases it prints that and exits 0 (PREBUILT.md row 9). The run
speaks with the same persona and the same hooks as the phone and text mode (Settings.system_prompt, default_hooks).

Each run leaves its per-case verdicts in var/eval-last.json, beside its trace store, and the next run prints the
cases whose verdict moved. `make baseline` (--write-baseline) writes evals/baseline.json from a run's own numbers.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from candidate_line.brain import Brain, EchoBrain, Reply, make_brain
from candidate_line.escalation import EscalationQueue, default_queue
from candidate_line.evals.checks import Verdict, evaluate
from candidate_line.evals.rates import cost_usd
from candidate_line.evals.schema import Case, load_cases
from candidate_line.hooks import Hooks, default_hooks
from candidate_line.persona import PLACEHOLDER_SYSTEM
from candidate_line.settings import Settings
from candidate_line.traces.store import EVAL_DEFAULT_PATH, TraceStore
from candidate_line.turn import TurnContext, TurnResult, run_silence, run_turn

ROOT = Path(__file__).resolve().parent.parent.parent
CASES = ROOT / "evals" / "cases"
BASELINE = ROOT / "evals" / "baseline.json"
COST_TOLERANCE = 0.20
LAST_RUN_NAME = "eval-last.json"


@dataclass(frozen=True)
class CaseResult:
    case: Case
    verdicts: tuple[Verdict, ...]
    cost_usd: float | None
    ctx_call_id: str = ""
    latencies_ms: tuple[int, ...] = ()  # one per model turn, the brain's own clock
    cached_tokens: tuple[int, int] = (0, 0)  # prompt-cache reads and writes across the case's model turns

    @property
    def passed(self) -> bool:
        return all(v.passed for v in self.verdicts)

    @property
    def pending(self) -> bool:
        """Every unmet check waits for a component that has not landed; nothing evaluable failed."""
        return not self.passed and all(v.passed or v.pending for v in self.verdicts)

    @property
    def verdict(self) -> str:
        return "passed" if self.passed else ("pending" if self.pending else "failed")

    @property
    def brain_ms(self) -> int | None:
        """The median of the case's model turns on the brain's clock. None when no model ran, because the echo
        brain and a silence turn report 0 ms and a zero would drag a median of real turns down."""
        ran = [ms for ms in self.latencies_ms if ms > 0]
        return round(statistics.median(ran)) if ran else None


@dataclass(frozen=True)
class RunNumbers:
    """The numbers the gate reads, computed in one place so the report and the baseline writer cannot disagree."""

    boundary_failures: tuple[CaseResult, ...]
    # The evaluable regression cases; a pending one counts for neither side.
    regression: tuple[CaseResult, ...]
    pass_rate: float | None
    cost_per_call: float | None
    priced: int  # the cases with a price, the n behind the cost per call (AGENTS.md rule 13)


def run_numbers(results: list[CaseResult]) -> RunNumbers:
    boundary_failures = tuple(
        r for r in results if r.case.kind == "boundary" and not r.passed and not r.pending
    )
    regression = tuple(r for r in results if r.case.kind == "regression" and not r.pending)
    pass_rate = (sum(r.passed for r in regression) / len(regression)) if regression else None
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    return RunNumbers(
        boundary_failures, regression, pass_rate, statistics.mean(costs) if costs else None, len(costs)
    )


def run_case(
    case: Case,
    brain: Brain,
    hooks: Hooks,
    system: str = PLACEHOLDER_SYSTEM,
    store: TraceStore | None = None,
    escalations: EscalationQueue | None = None,
) -> CaseResult:
    ctx = TurnContext(
        call_id=f"eval-{case.id}-{uuid.uuid4().hex[:6]}",
        channel=case.channel,
        system=system,
        store=store,
        escalations=escalations,
    )
    if store is not None:
        store.start_call(ctx.call_id, case.channel, provider=brain.name, model=brain.model)
    verdicts: list[Verdict] = []
    cost = 0.0
    priced = True
    latencies: list[int] = []
    cache_read = cache_write = 0
    for turn in case.turns:
        if turn.user is None:
            silence = run_silence(hooks, ctx, turn.silence_seconds or 0.0)
            # A silence turn runs no model, so its "reply" is empty and free. Its hang-up rides on the result, as a
            # closing turn's does, so the holding line's end of the call is not lost between the hook and the case.
            result = TurnResult(
                heard="",
                spoken=silence.said or "",
                reply=Reply("", 0, 0, 0, brain.name, brain.model),
                hang_up=silence.hang_up,
            )
        else:
            result = run_turn(brain, hooks, ctx, turn.user)
            latencies.append(result.reply.latency_ms)
            cache_read += result.reply.cached_input_tokens
            cache_write += result.reply.cache_write_input_tokens
            turn_cost = cost_usd(result.reply)
            if turn_cost is None:
                priced = False
            else:
                cost += turn_cost
        verdicts.extend(evaluate(check, result) for check in turn.checks)
    return CaseResult(
        case,
        tuple(verdicts),
        cost if priced else None,
        ctx.call_id,
        tuple(latencies),
        (cache_read, cache_write),
    )


def summarize(results: list[CaseResult], baseline: dict | None, moved: str | None = None) -> tuple[str, int]:
    """The report and the exit code. `moved` is the line naming the cases whose verdict changed since the
    previous run; it sits just above the counts, where a reader looks first."""
    lines = []
    for r in results:
        mark = "PASS" if r.passed else ("PENDING" if r.pending else "FAIL")
        ref = f" [{r.case.spec_ref}]" if r.case.spec_ref else ""
        # Each case carries its own median brain time, so the median of a named set (card 04's happy paths) is
        # read off the report without a query against the trace store.
        brain = f", brain {r.brain_ms:,} ms" if r.brain_ms is not None else ""
        lines.append(f"{mark} {r.case.id} ({r.case.kind}){ref} {r.case.title}{brain}")
        for v in r.verdicts:
            if not v.passed:
                lines.append(f"     {'~' if v.pending else 'x'} {v.check.name} {v.check.arg!r}: {v.detail}")
    pending = [r for r in results if r.pending]
    numbers = run_numbers(results)
    boundary_fail = numbers.boundary_failures
    pass_rate = numbers.pass_rate
    cost_per_call = numbers.cost_per_call
    failed = len(results) - sum(r.passed for r in results) - len(pending)
    if moved:
        lines.append(moved)
    lines.append(
        f"{len(results)} cases, {sum(r.passed for r in results)} passed, {failed} failed, {len(pending)} pending; boundary failures: {len(boundary_fail)}"
    )
    if pending:
        lines.append(
            f"pending: {len(pending)} cases wait for a component that has not landed (marked ~ above); they are neither passed nor failed"
        )
    code = 1 if boundary_fail else 0
    latencies = [ms for r in results for ms in r.latencies_ms if ms > 0]
    if latencies:
        lines.append(
            f"brain latency: median {statistics.median(latencies):.0f} ms, worst {max(latencies)} ms over {len(latencies)} model turns (text mode: the brain only; the phone adds the speech hops, DR-001)"
        )
    if cost_per_call is None:
        lines.append("cost per call: no priced model turns in this run")
    else:
        reads = sum(r.cached_tokens[0] for r in results)
        writes = sum(r.cached_tokens[1] for r in results)
        cache = f" (prompt cache: {reads} input tokens read, {writes} written)" if reads or writes else ""
        lines.append(f"cost per call: {cost_per_call:.5f} USD{cache}")
    if baseline:
        base_rate, base_cost = baseline.get("regression_pass_rate"), baseline.get("cost_per_call_usd")
        if pass_rate is not None and base_rate is not None and pass_rate < base_rate:
            lines.append(f"regression pass rate {pass_rate:.2f} fell below the baseline {base_rate:.2f}")
            code = 1
        if cost_per_call is not None and base_cost:
            delta = (cost_per_call - base_cost) / base_cost
            lines.append(
                f"cost against baseline {base_cost:.5f} USD: {delta:+.0%} (limit {COST_TOLERANCE:+.0%})"
            )
            if delta > COST_TOLERANCE:
                code = 1
    else:
        lines.append(
            "baseline: none committed yet (make baseline writes evals/baseline.json, inside its own work item)"
        )
    return "\n".join(lines), code


def last_run_path(store_path: Path | str) -> Path | None:
    """The last-run file sits beside the eval trace store, so EVAL_TRACE_STORE_PATH (read by Settings) moves both.
    An in-memory store leaves no file: every test runs on one (tests/conftest.py), so the `make test` inside
    `make gate` can never replace the room's last run with a test's cases and turn the next moved line to noise."""
    if str(store_path) == ":memory:":
        return None
    return Path(store_path).with_name(LAST_RUN_NAME)


def read_last_run(path: Path) -> dict[str, str] | None:
    """The previous run's verdict by case id, or None when its file cannot be read."""
    try:
        rows = json.loads(path.read_text())["cases"]
        return {str(row["id"]): str(row["verdict"]) for row in rows}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_last_run(path: Path, results: list[CaseResult]) -> None:
    rows = [
        {"id": r.case.id, "verdict": r.verdict, "boundary": r.case.kind == "boundary", "brain_ms": r.brain_ms}
        for r in results
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside and then renamed, so a run cut off half way never leaves half a file for the next comparison.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"cases": rows}, indent=2) + "\n")
    tmp.replace(path)


def moved_line(previous: dict[str, str], results: list[CaseResult]) -> str:
    """The cases whose verdict changed since the previous run, so "show me the cases that moved" is one line to
    read and not two reports to compare by eye. A case new to this run reads `new`; one no longer run, `gone`."""
    current = {r.case.id: r.verdict for r in results}
    moved = [
        f"{cid} {previous.get(cid, 'new')} -> {v}" for cid, v in current.items() if previous.get(cid) != v
    ]
    moved += [f"{cid} {v} -> gone" for cid, v in previous.items() if cid not in current]
    return f"moved: {', '.join(moved) or 'none'}"


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def write_baseline(path: Path, results: list[CaseResult]) -> int:
    """`make baseline`: the file in the shape evals/README.md documents, from this run's own numbers. The second
    dry run copied the cost from the rounded printout by hand; this takes it unrounded from the run itself."""
    numbers = run_numbers(results)
    if numbers.boundary_failures:
        ids = ", ".join(r.case.id for r in numbers.boundary_failures)
        print(
            f"baseline not written: {len(numbers.boundary_failures)} boundary failure(s) ({ids}); a baseline comes only from a run with none"
        )
        return 1
    # A baseline with no rate or no cost would switch that half of the gate off without saying so.
    if numbers.pass_rate is None or numbers.cost_per_call is None:
        print(
            "baseline not written: the run has no evaluable regression case or no priced model turn, so there is no rate or cost to hold the next run to"
        )
        return 1
    try:
        commit = git_commit()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"baseline not written: git rev-parse failed ({exc})")
        return 1
    # The rate is written unrounded: a rate rounded up would fail the next run that scores exactly the same.
    baseline = {
        "regression_pass_rate": numbers.pass_rate,
        "cost_per_call_usd": round(numbers.cost_per_call, 8),
        "commit": commit,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(baseline, indent=2) + "\n")
    print(
        f"baseline written to {path}: regression pass rate {numbers.pass_rate:.2f} over {len(numbers.regression)} evaluable case(s), "
        f"{numbers.cost_per_call:.5f} USD a call over {numbers.priced} priced case(s) (rates.py), commit {commit}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the eval cases")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument(
        "--brain",
        choices=["env", "echo"],
        default="env",
        help="echo runs no model (default: the environment's brain)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE,
        help="the baseline the gate reads and --write-baseline writes (default: evals/baseline.json)",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="after the run, write the baseline from it; only from evals/cases, refused on a boundary failure",
    )
    args = parser.parse_args(argv)
    # A baseline comes from the room's cases or not at all, so a test's tmp_path or a scratch folder can never
    # write the file every later run is held to (AGENTS.md rule 4). Refused before a single model call is spent.
    if args.write_baseline and args.cases.resolve() != CASES.resolve():
        real = CASES.relative_to(ROOT) if CASES.is_relative_to(ROOT) else CASES
        print(f"baseline not written: --write-baseline runs only on {real}, not {args.cases}")
        return 1
    cases = load_cases(args.cases)
    if not cases:
        print(f"0 cases in {args.cases}; nothing to run (the cases are written live, PREBUILT.md)")
        return 0
    # A voice case is heard by the probe caller as speech (make probe), where a pause or a barge-in means
    # something; run as text here it would prove nothing and could fail for the wrong reason (DR-011).
    voice = [case for case in cases if case.channel == "voice"]
    cases = [case for case in cases if case.channel == "text"]
    if voice:
        print(f"{len(voice)} voice case(s) left to the probe caller: {', '.join(c.id for c in voice)}")
    if not cases:
        print("no text cases to run")
        return 0
    settings = Settings.from_env()
    brain: Brain = EchoBrain() if args.brain == "echo" else make_brain(settings)
    # The runner's own store, beside the room's and never in it: make trace last shows the room's last call.
    store_path = settings.eval_trace_store_path or EVAL_DEFAULT_PATH
    store = TraceStore(store_path)
    queue = default_queue(store, None)  # the log poster: an eval run never reaches a real channel
    results = []
    for case in cases:
        result = run_case(
            case, brain, default_hooks(), system=settings.system_prompt(), store=store, escalations=queue
        )
        store.end_call(result.ctx_call_id, result.verdict)
        results.append(result)
    queue.drain()
    moved = None
    last = last_run_path(store_path)
    if last is not None:
        if last.exists():
            previous = read_last_run(last)
            moved = (
                moved_line(previous, results)
                if previous is not None
                else f"moved: unknown ({last} could not be read; this run replaces it)"
            )
        write_last_run(last, results)
    baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
    report, code = summarize(results, baseline, moved)
    print(report)
    if args.write_baseline:
        return write_baseline(args.baseline, results)
    return code


if __name__ == "__main__":
    sys.exit(main())
