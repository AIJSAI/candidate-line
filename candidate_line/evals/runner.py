"""`make eval`: runs every case in evals/cases through the same turn loop as the phone and prints a verdict.

Boundary cases are an absolute bar: one failure fails the run. Regression cases are a gate against the
committed baseline (evals/baseline.json): the pass rate may not fall and the cost per call may not rise more
than 20 percent. A case whose only unmet checks are pending (their component has not landed, DR-010) is printed
as PENDING and counts for neither side. With zero cases it prints that and exits 0 (PREBUILT.md row 9). The run
speaks with the same persona and the same hooks as the phone and text mode (Settings.system_prompt, default_hooks).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from candidate_line.brain import Brain, EchoBrain, Reply, make_brain
from candidate_line.evals.checks import Verdict, evaluate
from candidate_line.evals.rates import cost_usd
from candidate_line.evals.schema import Case, load_cases
from candidate_line.hooks import Hooks, default_hooks
from candidate_line.persona import PLACEHOLDER_SYSTEM
from candidate_line.settings import Settings
from candidate_line.turn import TurnContext, TurnResult, run_silence, run_turn

ROOT = Path(__file__).resolve().parent.parent.parent
CASES = ROOT / "evals" / "cases"
BASELINE = ROOT / "evals" / "baseline.json"
COST_TOLERANCE = 0.20


@dataclass(frozen=True)
class CaseResult:
    case: Case
    verdicts: tuple[Verdict, ...]
    cost_usd: float | None

    @property
    def passed(self) -> bool:
        return all(v.passed for v in self.verdicts)

    @property
    def pending(self) -> bool:
        """Every unmet check waits for a component that has not landed; nothing evaluable failed."""
        return not self.passed and all(v.passed or v.pending for v in self.verdicts)


def run_case(case: Case, brain: Brain, hooks: Hooks, system: str = PLACEHOLDER_SYSTEM) -> CaseResult:
    ctx = TurnContext(call_id=f"eval-{case.id}-{uuid.uuid4().hex[:6]}", channel=case.channel, system=system)
    verdicts: list[Verdict] = []
    cost = 0.0
    priced = True
    for turn in case.turns:
        if turn.user is None:
            said = run_silence(hooks, ctx, turn.silence_seconds or 0.0)
            # A silence turn runs no model, so its "reply" is empty and free.
            result = TurnResult(
                heard="", spoken=said or "", reply=Reply("", 0, 0, 0, brain.name, brain.model)
            )
        else:
            result = run_turn(brain, hooks, ctx, turn.user)
            turn_cost = cost_usd(result.reply)
            if turn_cost is None:
                priced = False
            else:
                cost += turn_cost
        verdicts.extend(evaluate(check, result) for check in turn.checks)
    return CaseResult(case, tuple(verdicts), cost if priced else None)


def summarize(results: list[CaseResult], baseline: dict | None) -> tuple[str, int]:
    """The report and the exit code."""
    lines = []
    for r in results:
        mark = "PASS" if r.passed else ("PENDING" if r.pending else "FAIL")
        ref = f" [{r.case.spec_ref}]" if r.case.spec_ref else ""
        lines.append(f"{mark} {r.case.id} ({r.case.kind}){ref} {r.case.title}")
        for v in r.verdicts:
            if not v.passed:
                lines.append(f"     {'~' if v.pending else 'x'} {v.check.name} {v.check.arg!r}: {v.detail}")
    pending = [r for r in results if r.pending]
    boundary_fail = [r for r in results if r.case.kind == "boundary" and not r.passed and not r.pending]
    regression = [r for r in results if r.case.kind == "regression" and not r.pending]
    pass_rate = (sum(r.passed for r in regression) / len(regression)) if regression else None
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    cost_per_call = statistics.mean(costs) if costs else None
    failed = len(results) - sum(r.passed for r in results) - len(pending)
    lines.append(
        f"{len(results)} cases, {sum(r.passed for r in results)} passed, {failed} failed, {len(pending)} pending; boundary failures: {len(boundary_fail)}"
    )
    if pending:
        lines.append(
            f"pending: {len(pending)} cases wait for a component that has not landed (marked ~ above); they are neither passed nor failed"
        )
    code = 1 if boundary_fail else 0
    if cost_per_call is None:
        lines.append("cost per call: no priced model turns in this run")
    else:
        lines.append(f"cost per call: {cost_per_call:.5f} USD")
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
        lines.append("baseline: none committed yet (evals/baseline.json is written by its own work item)")
    return "\n".join(lines), code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the eval cases")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument(
        "--brain",
        choices=["env", "echo"],
        default="env",
        help="echo runs no model (default: the environment's brain)",
    )
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    if not cases:
        print(f"0 cases in {args.cases}; nothing to run (the cases are written live, PREBUILT.md)")
        return 0
    settings = Settings.from_env()
    brain: Brain = EchoBrain() if args.brain == "echo" else make_brain(settings)
    results = [run_case(case, brain, default_hooks(), system=settings.system_prompt()) for case in cases]
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    report, code = summarize(results, baseline)
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
