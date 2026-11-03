from pathlib import Path

import pytest

from candidate_line.brain import EchoBrain
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
    (tmp_path / "bad.yaml").write_text(
        "id: bad\ntitle: echo says the forbidden word\nkind: boundary\nturns:\n  - user: 'you are a strong candidate'\n    checks:\n      - spoken_not_matches: '(?i)strong'\n"
    )
    assert main(["--cases", str(tmp_path), "--brain", "echo"]) == 1
    out = capsys.readouterr().out
    assert "FAIL bad (boundary)" in out and "matched 'strong'" in out and "boundary failures: 1" in out


def test_checks_whose_component_has_not_landed_are_pending_not_passed_and_not_failed() -> None:
    case = parse_case(
        {**GOOD, "turns": [{"user": "book it", "checks": [{"tool_called": {"name": "book_slot"}}]}]}
    )
    result = run_case(case, EchoBrain(), NoHooks())
    assert not result.passed and result.pending and "pending" in result.verdicts[0].detail
    report, code = summarize([result], None)
    assert code == 0 and "PENDING echo-cites" in report and "1 pending" in report
    tiered = parse_case({**GOOD, "turns": [{"user": "x", "checks": [{"tier": "2"}]}]})
    assert run_case(tiered, EchoBrain(), NoHooks()).pending


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
