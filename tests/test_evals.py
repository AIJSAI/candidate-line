import json
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from candidate_line.brain import EchoBrain, Message, Reply, ToolSpec
from candidate_line.evals import runner
from candidate_line.evals.runner import main, run_case, summarize
from candidate_line.evals.schema import CaseError, load_cases, parse_case
from candidate_line.hooks import NoHooks

GOOD = {
    "id": "echo-cites",
    "title": "the echo brain says back a line that cites F3.2",
    "kind": "boundary",
    "turns": [
        {
            "user": "See F3.2, you can move once.",
            "checks": [{"cites": "F3.2"}, {"spoken_not_matches": "(?i)strong"}],
        },
        {"silence_seconds": 6, "checks": []},
    ],
}


def test_zero_cases_prints_and_exits_zero(tmp_path: Path, capsys) -> None:
    assert main(["--cases", str(tmp_path), "--brain", "echo"]) == 0
    assert "0 cases" in capsys.readouterr().out


def test_a_good_case_passes_on_the_echo_brain() -> None:
    result = run_case(parse_case(GOOD), EchoBrain(), NoHooks())
    assert result.passed and [v.check.name for v in result.verdicts] == ["cites", "spoken_not_matches"]
    assert result.cost_usd is None  # the echo brain has no price


def test_a_failing_boundary_case_fails_the_run(tmp_path: Path, capsys) -> None:
    # The echo brain says "hello" back and never "Thursday", so this fails whatever the live hooks do: a guard
    # written on Wednesday (card 05) must not rescue it (the dry run of card 05 broke the first version, which
    # expected a forbidden word to come through unguarded).
    (tmp_path / "bad.yaml").write_text(
        "id: bad\ntitle: the echo never names a day\nkind: boundary\nturns:\n  - user: 'hello'\n    checks:\n      - spoken_matches: '(?i)thursday'\n"
    )
    assert main(["--cases", str(tmp_path), "--brain", "echo"]) == 1
    out = capsys.readouterr().out
    assert "FAIL bad (boundary)" in out and "spoken 'hello'" in out and "boundary failures: 1" in out


def test_checks_whose_component_has_not_landed_are_pending_not_passed_and_not_failed() -> None:
    # Built on a bare TurnResult, not on run_turn, because card 04 and card 06 fill these fields live and this
    # test must keep passing after they do (the dry run of card 04 broke its first version).
    from candidate_line.brain import Reply
    from candidate_line.evals.checks import evaluate
    from candidate_line.evals.runner import CaseResult
    from candidate_line.evals.schema import Check
    from candidate_line.turn import TurnResult

    bare = TurnResult("book it", "one moment", Reply("one moment", 0, 0, 0, "echo", "none"))
    tool = evaluate(Check("tool_called", {"name": "book_slot"}), bare)
    tier = evaluate(Check("tier", "2"), bare)
    assert tool.pending and tier.pending and not tool.passed and "pending" in tool.detail
    result = CaseResult(parse_case(GOOD), (tool, tier), None)
    assert not result.passed and result.pending
    report, code = summarize([result], None)
    assert code == 0 and "PENDING echo-cites" in report and "1 pending" in report


def test_a_pending_check_beside_a_real_failure_is_a_failure() -> None:
    case = parse_case(
        {
            **GOOD,
            "kind": "boundary",
            "turns": [
                {"user": "book it", "checks": [{"tool_called": "book_slot"}, {"spoken_matches": "thursday"}]}
            ],
        }
    )
    result = run_case(case, EchoBrain(), NoHooks())
    assert not result.passed and not result.pending
    assert summarize([result], None)[1] == 1


def test_landed_components_are_evaluated_from_the_turn_result() -> None:
    from candidate_line.brain import Reply
    from candidate_line.evals.checks import evaluate
    from candidate_line.evals.schema import Check
    from candidate_line.turn import TurnResult

    reply = Reply("", 0, 0, 0, "echo", "none")
    done = TurnResult(
        "x",
        "that is in the scheduling section",
        reply,
        cited=("F3.2",),
        tools_called=("book_slot",),
        state={"slot": "S1105-0930"},
        tier="1",
    )
    assert evaluate(Check("cites", "F3.2"), done).passed  # the id rode on the turn, not in the words
    assert evaluate(Check("tool_called", "book_slot"), done).passed
    assert not evaluate(Check("tool_called", "move_slot"), done).passed
    assert evaluate(Check("state", {"slot": "S1105-0930"}), done).passed
    assert evaluate(Check("tier", "1"), done).passed and not evaluate(Check("tier", "2"), done).passed


def test_unknown_keys_and_checks_are_refused() -> None:
    with pytest.raises(CaseError, match="unknown keys"):
        parse_case({**GOOD, "expected": "x"})
    with pytest.raises(CaseError, match="unknown check"):
        parse_case({**GOOD, "turns": [{"user": "x", "checks": [{"says": "x"}]}]})
    with pytest.raises(CaseError, match="exactly one of"):
        parse_case({**GOOD, "turns": [{"user": "x", "silence_seconds": 3}]})


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text("id: same\ntitle: t\nkind: regression\nturns:\n  - user: hi\n")
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(tmp_path)


def test_summary_applies_the_baseline_gates() -> None:
    passing = run_case(parse_case({**GOOD, "kind": "regression"}), EchoBrain(), NoHooks())
    report, code = summarize([passing], {"regression_pass_rate": 1.0, "cost_per_call_usd": 0.001})
    assert code == 0 and "1 cases, 1 passed" in report
    failing = run_case(
        parse_case(
            {
                **GOOD,
                "kind": "regression",
                "turns": [{"user": "strong", "checks": [{"spoken_not_matches": "strong"}]}],
            }
        ),
        EchoBrain(),
        NoHooks(),
    )
    report, code = summarize([failing], {"regression_pass_rate": 1.0, "cost_per_call_usd": 0.001})
    assert code == 1 and "fell below the baseline" in report


def test_a_case_carries_its_spec_line_and_note(tmp_path) -> None:
    (tmp_path / "CL-001-never-scores.yaml").write_text(
        "id: CL-001\ntitle: never scores\nkind: boundary\nspec_ref: '5.1'\nnote: the first Never line\n"
        "turns:\n- user: how did I do\n  checks:\n  - spoken_not_matches: '(?i)strong'\n"
    )
    [case] = load_cases(tmp_path)
    assert case.spec_ref == "5.1" and case.note == "the first Never line"


def test_the_runner_writes_its_calls_into_the_store_it_is_given_and_nowhere_else(tmp_path) -> None:
    from candidate_line.traces.store import TraceStore

    store = TraceStore(":memory:")
    case = parse_case(GOOD)
    result = run_case(case, EchoBrain(), NoHooks(), store=store)
    [call] = store.calls()
    assert call.call_id == result.ctx_call_id and call.channel == case.channel


def test_the_report_carries_a_brain_latency_line_when_a_model_ran() -> None:
    from candidate_line.evals.runner import CaseResult

    result = CaseResult(parse_case(GOOD), (), None, "eval-x", (640, 910, 720))
    report, _ = summarize([result], None)
    assert "brain latency: median 720 ms, worst 910 ms over 3 model turns" in report


def test_cache_reads_and_writes_are_priced_and_printed() -> None:
    from candidate_line.brain import Reply
    from candidate_line.evals.rates import cost_usd
    from candidate_line.evals.runner import CaseResult

    plain = Reply("x", 1000, 100, 0, "anthropic", "claude-haiku-5-5")
    cached = Reply("x", 100, 100, 0, "anthropic", "claude-haiku-5-5", cached_input_tokens=900)
    written = Reply("x", 100, 100, 0, "anthropic", "claude-haiku-5-5", cache_write_input_tokens=900)
    assert cost_usd(cached) < cost_usd(plain) < cost_usd(written)
    assert abs(cost_usd(cached) - (100 * 0.10 + 900 * 0.01 + 100 * 0.5) / 1e6) < 1e-12
    result = CaseResult(parse_case(GOOD), (), 0.0001, "eval-x", (700,), (900, 0))
    report, _ = summarize([result], None)
    assert "prompt cache: 900 input tokens read, 0 written" in report


def test_a_curly_apostrophe_does_not_slip_past_a_straight_pattern() -> None:
    from candidate_line.brain import Reply
    from candidate_line.evals.checks import evaluate
    from candidate_line.evals.schema import Check
    from candidate_line.turn import TurnResult

    curly = TurnResult("x", "You\u2019re a strong candidate.", Reply("", 0, 0, 0, "echo", "none"))
    assert not evaluate(Check("spoken_not_matches", "(?i)you're a strong"), curly).passed


def test_a_voice_case_is_left_to_the_probe_caller_and_not_run_as_text(tmp_path: Path, capsys) -> None:
    (tmp_path / "CL-901-voice.yaml").write_text(
        "id: CL-901\ntitle: a pause mid-sentence\nkind: boundary\nchannel: voice\n"
        "turns:\n  - user: my code is\n    checks:\n      - spoken_matches: never\n"
    )
    assert main(["--cases", str(tmp_path), "--brain", "echo"]) == 0
    out = capsys.readouterr().out
    assert "1 voice case(s) left to the probe caller: CL-901" in out and "no text cases to run" in out


def _write_case(folder: Path, case_id: str, kind: str, user: str) -> None:
    """A one-turn case the echo brain passes when the caller's words name Thursday and fails otherwise."""
    (folder / f"{case_id}.yaml").write_text(
        f"id: {case_id}\ntitle: {case_id}\nkind: {kind}\nturns:\n  - user: '{user}'\n"
        "    checks:\n      - spoken_matches: '(?i)thursday'\n"
    )


class _PricedEcho(EchoBrain):
    """The echo brain with a Haiku 5.5 price and a clock, so a green run has a rate, a cost and a brain time."""

    name = "anthropic"
    model = "claude-haiku-5-5"

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply:
        said = super().reply(system, messages, max_tokens, tools)
        return replace(
            said, input_tokens=1000, output_tokens=20, latency_ms=900, provider=self.name, model=self.model
        )


def test_a_second_run_names_the_cases_that_moved(tmp_path: Path, monkeypatch, capsys) -> None:
    # The last-run file sits beside the eval store; the conftest keeps that store in memory, which leaves no file.
    monkeypatch.setenv("EVAL_TRACE_STORE_PATH", str(tmp_path / "var" / "eval-traces.sqlite"))
    cases = tmp_path / "cases"
    cases.mkdir()
    _write_case(cases, "CL-021", "regression", "Thursday works")
    _write_case(cases, "CL-028", "boundary", "hello")
    run = ["--cases", str(cases), "--brain", "echo"]
    assert main(run) == 1
    assert "moved:" not in capsys.readouterr().out  # no previous run to compare with
    last = json.loads((tmp_path / "var" / "eval-last.json").read_text())
    assert last["cases"] == [
        {"id": "CL-021", "verdict": "passed", "boundary": False, "brain_ms": None},
        {"id": "CL-028", "verdict": "failed", "boundary": True, "brain_ms": None},
    ]
    _write_case(cases, "CL-028", "boundary", "Thursday then")  # the case changed between the runs
    assert main(run) == 0
    out = capsys.readouterr().out
    assert "\nmoved: CL-028 failed -> passed\n2 cases, 2 passed" in out
    assert main(run) == 0
    assert "\nmoved: none\n" in capsys.readouterr().out


def test_each_case_line_carries_its_median_brain_time_when_a_model_ran() -> None:
    from candidate_line.evals.runner import CaseResult

    timed = CaseResult(parse_case(GOOD), (), None, "eval-x", (1500, 2100, 1712))
    echoed = CaseResult(parse_case({**GOOD, "id": "echo-only"}), (), None, "eval-y", (0,))
    report, _ = summarize([timed, echoed], None)
    first, second = report.splitlines()[:2]
    assert first.startswith("PASS echo-cites (boundary)") and first.endswith(", brain 1,712 ms")
    assert second.startswith("PASS echo-only") and ", brain" not in second
    assert "brain latency: median 1712 ms, worst 2100 ms over 3 model turns" in report  # unchanged


def test_write_baseline_runs_only_on_the_real_cases_refuses_a_boundary_failure_and_writes_the_shape(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    committed = runner.BASELINE.read_bytes() if runner.BASELINE.exists() else None
    cases = tmp_path / "cases"
    cases.mkdir()
    baseline = tmp_path / "baseline.json"
    run = ["--cases", str(cases), "--write-baseline", "--baseline", str(baseline)]
    _write_case(cases, "CL-021", "regression", "Thursday works")
    assert main([*run, "--brain", "echo"]) == 1
    assert "runs only on evals/cases" in capsys.readouterr().out and not baseline.exists()

    monkeypatch.setattr(runner, "CASES", cases)  # this folder stands in for the room's evals/cases
    monkeypatch.setattr(runner, "make_brain", lambda settings, **_: _PricedEcho())
    _write_case(cases, "CL-028", "boundary", "hello")
    assert main(run) == 1
    refusal = capsys.readouterr().out.splitlines()[-1]
    assert (
        refusal.startswith("baseline not written: 1 boundary failure(s) (CL-028)") and not baseline.exists()
    )

    _write_case(cases, "CL-028", "boundary", "Thursday then")
    assert main(run) == 0
    out = capsys.readouterr().out
    assert "PASS CL-021 (regression) CL-021, brain 900 ms" in out
    written = json.loads(baseline.read_text())
    assert list(written) == ["regression_pass_rate", "cost_per_call_usd", "commit", "date"]
    # One turn a call at (1000 input x 0.10 + 20 output x 0.50) USD per million tokens (rates.py).
    assert written["regression_pass_rate"] == 1.0 and written["cost_per_call_usd"] == 0.00011
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=runner.ROOT, capture_output=True, text=True, check=True
    )
    assert written["commit"] == head.stdout.strip()
    assert datetime.fromisoformat(written["date"]).utcoffset() == timedelta(0)
    assert (runner.BASELINE.read_bytes() if runner.BASELINE.exists() else None) == committed
