"""The gate (DR-025 section 5): pure, tested on every rule form, both sides of every bound, declined and unclear,
and every role in data/roles.yaml with an all-met set and each question unmet alone."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from candidate_line.tools import rules
from candidate_line.tools.roles import Question, Range, Role, Rule, load_roles
from candidate_line.tools.rules import GateResult, check, meets

ROLES = load_roles()


def _range_q(rule: Rule, low: int = 0, high: int = 60) -> Question:
    return Question(
        "q", "How many?", "range", (), Range(low, high, "hours a week"), "some hours", rule, "why"
    )


# Every rule form, on both sides of its bound.


def test_equals_yes_and_equals_no() -> None:
    licence = ROLES["care-aide"].questions[0]  # equals yes
    assert meets(licence, "yes") and not meets(licence, "no")
    flipped = Question(**{**licence.__dict__, "rule": Rule("equals", "no")})
    assert meets(flipped, "no") and not meets(flipped, "yes")


def test_one_of_takes_only_its_posted_options() -> None:
    days = ROLES["care-aide"].questions[1]  # one_of weekends, both
    assert meets(days, "weekends") and meets(days, "both") and not meets(days, "weekdays")
    assert not meets(days, "Weekends") and not meets(days, "sundays")


@pytest.mark.parametrize(
    ("value", "met"), [("19", False), ("20", True), ("21", True), ("0", False), ("60", True)]
)
def test_at_least_on_both_sides_of_its_bound(value: str, met: bool) -> None:
    assert meets(_range_q(Rule("at_least", 20)), value) is met


@pytest.mark.parametrize(("value", "met"), [("3", True), ("4", True), ("5", False), ("0", True)])
def test_at_most_on_both_sides_of_its_bound(value: str, met: bool) -> None:
    assert meets(_range_q(Rule("at_most", 4), high=26), value) is met


@pytest.mark.parametrize(
    ("value", "met"), [("9", False), ("10", True), ("15", True), ("20", True), ("21", False)]
)
def test_between_on_both_sides_of_both_bounds(value: str, met: bool) -> None:
    assert meets(_range_q(Rule("between", (10, 20))), value) is met


@pytest.mark.parametrize("value", ["declined", "unclear"])
def test_declined_and_unclear_meet_no_rule(value: str) -> None:
    for role in ROLES.values():
        for q in role.questions:
            assert not meets(q, value), (role.id, q.id)


@pytest.mark.parametrize("value", ["", "twenty", "20.5", "-1", " 20", "２０"])
def test_a_value_that_is_no_whole_number_meets_no_range_rule(value: str) -> None:
    assert not meets(_range_q(Rule("at_least", 0)), value)


# Every committed role: all met, then each question unmet alone, then each unasked alone.


def _met_value(q: Question) -> str:
    if q.rule.form == "equals":
        return str(q.rule.value)
    if q.rule.form == "one_of":
        assert isinstance(q.rule.value, tuple)
        return str(q.rule.value[0])
    assert isinstance(q.rule.value, int)
    return str(q.rule.value)


def _unmet_value(q: Question) -> str:
    if q.rule.form == "equals":
        return "no" if q.rule.value == "yes" else "yes"
    if q.rule.form == "one_of":
        return next(o.id for o in q.options if o.id not in q.rule.value)
    assert isinstance(q.rule.value, int) and q.range is not None
    return str(q.rule.value - 1) if q.rule.form == "at_least" else str(q.rule.value + 1)


@pytest.mark.parametrize("role_id", list(ROLES))
def test_every_role_with_every_answer_met_is_complete_and_met(role_id: str) -> None:
    role = ROLES[role_id]
    answers = {q.id: _met_value(q) for q in role.questions}
    assert check(role, answers) == GateResult(complete=True, met=True, unasked=(), unmet=())


@pytest.mark.parametrize(
    ("role_id", "index"), [(r, i) for r, role in ROLES.items() for i in range(len(role.questions))]
)
def test_every_role_with_one_question_unmet_alone_is_complete_and_not_met(role_id: str, index: int) -> None:
    role = ROLES[role_id]
    answers = {q.id: _met_value(q) for q in role.questions}
    unmet = role.questions[index]
    for value in (_unmet_value(unmet), "declined", "unclear"):
        answers[unmet.id] = value
        assert check(role, answers) == GateResult(complete=True, met=False, unasked=(), unmet=(unmet.id,))


@pytest.mark.parametrize(
    ("role_id", "index"), [(r, i) for r, role in ROLES.items() for i in range(len(role.questions))]
)
def test_a_question_with_no_recorded_answer_is_unasked_and_never_met(role_id: str, index: int) -> None:
    role = ROLES[role_id]
    answers = {q.id: _met_value(q) for q in role.questions}
    missing = role.questions[index].id
    del answers[missing]
    assert check(role, answers) == GateResult(complete=False, met=False, unasked=(missing,), unmet=())


def test_unasked_and_unmet_keep_the_posted_order_and_ignore_ids_the_role_does_not_post() -> None:
    role = ROLES["care-aide"]
    result = check(role, {"q5": "no", "q2": "weekdays", "q9": "yes"})
    assert result.unasked == ("q1", "q3", "q4") and result.unmet == ("q2", "q5")
    assert check(Role("r", "t", "s", "R", ()), {}) == GateResult(True, True, (), ())


def test_the_same_answers_always_give_the_same_result() -> None:
    role = ROLES["warehouse-associate"]
    answers = {"q1": "yes", "q2": "night", "q3": "yes", "q4": "4", "q5": "yes"}
    assert len({check(role, answers) for _ in range(50)}) == 1


def test_the_gate_reads_no_file_clock_network_model_or_randomness() -> None:
    # Pure by construction: its module imports only the roles' types and the standard library's typing helpers.
    tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(node, ast.Import) else f"{node.module}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert imported <= {"__future__", "collections.abc", "dataclasses", "candidate_line.tools.roles"}
