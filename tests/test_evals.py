import json
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from candidate_line.brain import Brain, EchoBrain, Message, Reply, ToolSpec
from candidate_line.evals import runner
from candidate_line.evals.runner import CaseResult, main, run_case, summarize
from candidate_line.evals.schema import Case, CaseError, load_cases, parse_case
from candidate_line.hooks import Hooks, NoHooks
from candidate_line.tools.ledger import Ledger

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
    base = {"regression_pass_rate": 1.0, "cost_per_call_usd": 0.001}
    # One flake does not turn the gate red; two do (DR-017). Nineteen cases, as the room has, so the floor is
    # 1 - 1/19 and the rate 18/19 must equal it, not miss it by a float's last bit.
    report, code = summarize([passing] * 18 + [failing], base)
    assert code == 0 and "regression pass rate 0.95 against the baseline 1.00 over 19 evaluable" in report
    assert "tolerance 1 case (floor 0.95)" in report
    report, code = summarize([passing] * 17 + [failing] * 2, base)
    assert code == 1 and "fell below the baseline 1.00 over 19 evaluable case(s), tolerance 1 case" in report
    assert runner.REGRESSION_TOLERANCE_CASES == 1


def test_every_case_runs_on_the_pinned_clock_with_a_ledger_of_its_own(tmp_path: Path, monkeypatch) -> None:
    seen: list[Ledger] = []

    def spy(case: Case, brain: Brain, hooks: Hooks, **kwargs: Any) -> CaseResult:
        seen.append(kwargs["ledger"])
        return run_case(case, brain, hooks, **kwargs)

    monkeypatch.setattr(runner, "run_case", spy)
    _write_case(tmp_path, "CL-021", "regression", "Thursday works")
    _write_case(tmp_path, "CL-022", "regression", "Thursday too")
    main(["--cases", str(tmp_path), "--brain", "echo"])
    assert len(seen) == 2 and seen[0] is not seen[1]
    # The first open slot is the first in data/slots.yaml after the pinned instant, whatever today's date is.
    assert runner.EVAL_CLOCK.isoformat() == "2026-11-04T18:00:00-06:00"
    assert all(ledger.open_slots(limit=1)[0].id == "S1105-0930" for ledger in seen)


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


# The outbound case (DR-025 section 18). Lane A's tools and fixed lines are not in this lane's branch, so the tests
# put small stand-ins in their place by name; the real ones replace them at the merge and these still hold.

OUTBOUND = {
    "id": "CL-941",
    "title": "the opening for the dialled applicant, then the PIN",
    "kind": "boundary",
    "outbound": "ACME-3108",
    "turns": [
        {"fixed": "opening", "checks": [{"spoken_matches": "calling for Lerato"}]},
        {"user": "It's 4398.", "checks": [{"spoken_matches": "4398"}]},
        {"fixed": "voicemail", "checks": [{"spoken_not_matches": "(?i)care aide|ACME-\\d{4}"}]},
    ],
}
_STAND_IN_TOOLS = (
    ToolSpec("confirm_applicant", "confirms the dialled applicant by PIN", {"type": "object"}),
)


class _ToolSpy(EchoBrain):
    """The echo brain, keeping what each call was given."""

    def __init__(self) -> None:
        self.tools: list[tuple[str, ...]] = []
        self.histories: list[list[str]] = []

    def reply(
        self, system: str, messages: Sequence[Message], max_tokens: int = 200, tools: Sequence[ToolSpec] = ()
    ) -> Reply:
        self.tools.append(tuple(t.name for t in tools))
        self.histories.append([m.text for m in messages])
        return super().reply(system, messages, max_tokens, tools)


def _outbound_stand_ins(monkeypatch: pytest.MonkeyPatch) -> None:
    from candidate_line import persona
    from candidate_line import tools as line_tools

    monkeypatch.setattr(line_tools, "OUTBOUND_TOOL_SPECS", _STAND_IN_TOOLS, raising=False)
    monkeypatch.setattr(
        persona, "outbound_opening", lambda first: f"Hello, this is ACME, calling for {first}.", raising=False
    )
    monkeypatch.setattr(persona, "PIN_ASK", "Please say your PIN.", raising=False)
    monkeypatch.setattr(
        persona,
        "voicemail_line",
        lambda first, number: f"A message for {first}. Call {number}.",
        raising=False,
    )


def test_the_schema_takes_outbound_fixed_and_the_hand_off_checks_and_still_refuses_unknown_keys() -> None:
    case = parse_case(
        {
            **OUTBOUND,
            "turns": [
                *OUTBOUND["turns"],
                {
                    "user": "no",
                    "checks": [{"hand_off_matches": "^Screening"}, {"hand_off_not_matches": "licen"}],
                },
            ],
        }
    )
    assert case.outbound == "ACME-3108" and [t.fixed for t in case.turns] == [
        "opening",
        None,
        "voicemail",
        None,
    ]
    assert [c.name for c in case.turns[3].checks] == ["hand_off_matches", "hand_off_not_matches"]
    assert parse_case(GOOD).outbound is None and all(t.fixed is None for t in parse_case(GOOD).turns)
    refused = [
        ({**OUTBOUND, "dialled": "ACME-3108"}, "unknown keys"),
        ({**OUTBOUND, "outbound": "3108"}, "application code"),
        ({**OUTBOUND, "turns": [{"fixed": "greeting"}]}, "fixed must be one of"),
        ({**OUTBOUND, "turns": [{"fixed": "opening", "user": "hello"}]}, "exactly one of"),
        ({**GOOD, "turns": [{"fixed": "opening"}]}, "belongs to an outbound case"),
        ({**OUTBOUND, "turns": [{"user": "x", "checks": [{"hand_off_says": "x"}]}]}, "unknown check"),
    ]
    for raw, message in refused:
        with pytest.raises(CaseError, match=message):
            parse_case(raw)


def test_the_hand_off_checks_read_every_hand_off_s_subject_and_email() -> None:
    from types import SimpleNamespace

    from candidate_line.escalation import Escalation
    from candidate_line.evals.checks import evaluate
    from candidate_line.evals.schema import Check

    hand_off = Escalation(
        call_id="eval-CL-941",
        tier="2",
        reason="screening hand-off from ACME-3108 (Lerato): Home Care Aide; recruiter call promised by Friday",
        suggested_action="read the answers on the applicant's record and call them by the promised time",
        trace_url="http://127.0.0.1:8001/calls/eval-CL-941",
    )
    posted = SimpleNamespace(heard="", spoken="", hand_offs=(hand_off,))
    none = SimpleNamespace(heard="", spoken="", hand_offs=())
    assert evaluate(
        Check("hand_off_matches", r"(?i)^Screening hand-off: Lerato \(ACME-3108\)"), posted
    ).passed
    assert evaluate(Check("hand_off_matches", "ACME-3108"), posted).passed
    assert not evaluate(Check("hand_off_matches", "forklift"), posted).passed
    assert not evaluate(Check("hand_off_not_matches", "Home Care Aide"), posted).passed
    assert evaluate(Check("hand_off_not_matches", "forklift"), posted).passed
    missing = evaluate(Check("hand_off_matches", "."), none)
    assert not missing.passed and not missing.pending and "no hand-off" in missing.detail
    assert evaluate(Check("hand_off_not_matches", "."), none).passed
    # Before the turn carries its hand-offs (lane A), the check waits, and is never a pass.
    waiting = evaluate(Check("hand_off_matches", "."), SimpleNamespace(heard="", spoken=""))
    assert waiting.pending and not waiting.passed


def test_an_outbound_case_is_seeded_from_a_dial_and_runs_with_the_outbound_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candidate_line.turn import TurnContext

    _outbound_stand_ins(monkeypatch)
    seen: list[TurnContext] = []
    real = runner.run_turn

    def spy(brain: Brain, hooks: Hooks, ctx: TurnContext, text: str, **kwargs: Any) -> Any:
        seen.append(ctx)
        return real(brain, hooks, ctx, text, **kwargs)

    monkeypatch.setattr(runner, "run_turn", spy)
    brain = _ToolSpy()
    ledger = Ledger(now=lambda: runner.EVAL_CLOCK)
    result = run_case(parse_case(OUTBOUND), brain, NoHooks(), ledger=ledger)
    assert result.passed, [v.detail for v in result.verdicts if not v.passed]
    assert seen and len({id(c) for c in seen}) == 1
    ctx = seen[0]
    seeded = ctx.data["outbound"]
    assert (seeded["code"], seeded["first_name"], seeded["attempt"]) == ("ACME-3108", "Lerato", 1)
    [dial] = ledger.dials("ACME-3108")
    assert dial["dial_id"] == seeded["dial_id"] and dial["status"] == "in-progress"
    assert dial["call_sid"] == result.ctx_call_id and dial["answered_by"] == "human"
    # Every model call had the outbound tools, and the history began with the applicant's own words.
    assert brain.tools and set(brain.tools) == {("confirm_applicant",)}
    assert brain.histories[0] == ["It's 4398."]


def test_a_fixed_turn_says_the_opening_and_the_pin_ask_or_the_voicemail_with_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candidate_line.tools.ledger import Ledger as L

    _outbound_stand_ins(monkeypatch)
    lerato = L().applicant("ACME-3108")
    assert lerato is not None
    assert (
        runner.fixed_line("opening", lerato)
        == "Hello, this is ACME, calling for Lerato. Please say your PIN."
    )
    voicemail = runner.fixed_line("voicemail", lerato)
    assert voicemail == f"A message for Lerato. Call {runner.EVAL_LINE_NUMBER}."
    assert runner.EVAL_LINE_NUMBER.startswith("+155555501")  # fictional, never the line's own number
    brain = _ToolSpy()
    case = parse_case({**OUTBOUND, "turns": OUTBOUND["turns"][:1]})
    assert run_case(case, brain, NoHooks()).passed and brain.tools == []


def test_an_outbound_case_waits_for_its_tools_and_lines_and_refuses_an_applicant_never_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candidate_line import persona
    from candidate_line import tools as line_tools

    monkeypatch.setattr(line_tools, "OUTBOUND_TOOL_SPECS", None, raising=False)
    brain = _ToolSpy()
    result = run_case(parse_case(OUTBOUND), brain, NoHooks())
    assert result.pending and brain.tools == [] and "outbound tools" in result.verdicts[0].detail
    _outbound_stand_ins(monkeypatch)
    monkeypatch.setattr(persona, "outbound_opening", None)
    waiting = run_case(parse_case({**OUTBOUND, "turns": OUTBOUND["turns"][:1]}), brain, NoHooks())
    assert waiting.pending and "fixed lines" in waiting.verdicts[0].detail
    with pytest.raises(CaseError, match="not an application"):
        run_case(parse_case({**OUTBOUND, "outbound": "ACME-0001"}), brain, NoHooks())
    with pytest.raises(CaseError, match="never dials ACME-7941"):
        run_case(parse_case({**OUTBOUND, "outbound": "ACME-7941"}), brain, NoHooks())  # no consent
