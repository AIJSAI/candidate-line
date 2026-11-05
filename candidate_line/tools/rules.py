"""The gate: does each of an applicant's own answers meet the requirement the employer posted for that question
(DR-025 section 5, spec 9.10).

Why pure: the gate decides only which fixed line follows the last answer and whether the line may offer a booking,
so it must give the same result for the same answers every time, with no file, clock, network, model or randomness
in it, and be read in one sitting. It looks at one question and one answer at a time; nothing here weighs, sums
or compares answers across questions or across applicants, which is the line between a posted requirement and a
score (spec section 5, Never 1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from candidate_line.tools.roles import DECLINED, UNCLEAR, Question, Role


@dataclass(frozen=True)
class GateResult:
    complete: bool  # every posted question has a recorded answer
    met: bool  # complete, and every recorded value meets its question's rule
    unasked: tuple[str, ...]  # question ids with no recorded answer, in posted order
    unmet: tuple[str, ...]  # question ids whose answer meets no rule (declined and unclear included)


def meets(question: Question, value: str) -> bool:
    """Whether one recorded value meets its question's posted rule. A skip or an unclear answer meets none, and a
    value the question does not take meets none, so a bad record can only ever send the call to a person."""
    if value in (DECLINED, UNCLEAR):
        return False
    rule = question.rule
    if rule.form == "equals":
        return value == rule.value
    if rule.form == "one_of":
        return isinstance(rule.value, tuple) and value in rule.value
    number = _whole(value)
    if number is None:
        return False
    if rule.form == "at_least":
        return isinstance(rule.value, int) and number >= rule.value
    if rule.form == "at_most":
        return isinstance(rule.value, int) and number <= rule.value
    if rule.form == "between" and isinstance(rule.value, tuple) and len(rule.value) == 2:
        low, high = rule.value
        return isinstance(low, int) and isinstance(high, int) and low <= number <= high
    return False


def check(role: Role, answers: Mapping[str, str]) -> GateResult:
    """answers maps a question id to its recorded value. Ids the role does not post are ignored."""
    unasked = tuple(q.id for q in role.questions if q.id not in answers)
    unmet = tuple(q.id for q in role.questions if q.id in answers and not meets(q, answers[q.id]))
    complete = not unasked
    return GateResult(complete=complete, met=complete and not unmet, unasked=unasked, unmet=unmet)


def _whole(value: str) -> int | None:
    return int(value) if value.isascii() and value.isdigit() else None
