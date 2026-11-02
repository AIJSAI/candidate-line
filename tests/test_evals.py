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


def test_checks_that_need_live_components_fail_loudly() -> None:
    case = parse_case(
        {**GOOD, "turns": [{"user": "book it", "checks": [{"tool_called": {"name": "book_slot"}}]}]}
    )
    result = run_case(case, EchoBrain(), NoHooks())
    assert not result.passed and "not evaluable" in result.verdicts[0].detail


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
