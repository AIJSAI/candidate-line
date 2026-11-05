"""The roles loader (DR-025 section 4): the committed file loads clean, and each thing the gate must never read is
refused in its own test, with the message naming where it is."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from candidate_line.tools.roles import (
    FORBIDDEN_TOPICS,
    ROLES_PATH,
    Question,
    Range,
    RolesError,
    Rule,
    allowed_values,
    load_roles,
    role,
    spoken_value,
)

COMMITTED: dict[str, Any] = yaml.safe_load(ROLES_PATH.read_text(encoding="utf-8"))


def _doc() -> dict[str, Any]:
    return copy.deepcopy(COMMITTED)


def _load(tmp_path: Path, doc: dict[str, Any]) -> None:
    path = tmp_path / "roles.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    load_roles(path)


def _refused(tmp_path: Path, doc: dict[str, Any], words: str) -> None:
    with pytest.raises(RolesError, match=words):
        _load(tmp_path, doc)


def test_the_committed_roles_load_clean_with_every_question_in_order() -> None:
    roles = load_roles()
    assert list(roles) == ["care-aide", "warehouse-associate", "front-desk"]
    aide = roles["care-aide"]
    assert aide.title == "Home Care Aide" and aide.recruiter == "Recruiter A"
    assert [q.id for q in aide.questions] == ["q1", "q2", "q3", "q4", "q5"]
    q2, q3 = aide.questions[1], aide.questions[2]
    assert q2.kind == "choice" and [o.id for o in q2.options] == ["weekdays", "weekends", "both"]
    assert q2.rule == Rule("one_of", ("weekends", "both"))
    assert q3.range == Range(0, 60, "hours a week") and q3.rule == Rule("at_least", 20)
    assert roles["warehouse-associate"].questions[3].rule == Rule("at_most", 4)
    assert role("front-desk") == roles["front-desk"]
    assert role("no-such-role") is None


# Unknown keys, anywhere.


@pytest.mark.parametrize("key", ["score", "weight", "rank", "knockout", "required", "expression"])
def test_an_unknown_key_on_a_question_is_refused(tmp_path: Path, key: str) -> None:
    doc = _doc()
    doc["roles"][0]["questions"][0][key] = 1
    _refused(tmp_path, doc, f"role care-aide question q1: unknown key {key}")


def test_an_unknown_key_on_a_role_the_file_an_option_a_range_or_a_slot_is_refused(tmp_path: Path) -> None:
    for where, words in (
        (lambda d: d["roles"][0].__setitem__("threshold", 3), "role care-aide: unknown key threshold"),
        (lambda d: d.__setitem__("weights", {}), "the file: unknown key weights"),
        (
            lambda d: d["roles"][0]["questions"][1]["options"][0].__setitem__("score", 2),
            "option: unknown key",
        ),
        (lambda d: d["roles"][0]["questions"][2]["range"].__setitem__("pass_mark", 20), "range: unknown key"),
        (
            lambda d: d["interview_slots"][0].__setitem__("priority", 1),
            "interview slot S1105-0900: unknown key",
        ),
    ):
        doc = _doc()
        where(doc)
        _refused(tmp_path, doc, words)


# A rule form that does not fit its kind.


@pytest.mark.parametrize(
    ("index", "rule", "words"),
    [
        (0, {"at_least": 1}, "rule at_least does not fit a yes_no question"),
        (1, {"equals": "yes"}, "rule equals does not fit a choice question"),
        (2, {"one_of": ["weekends"]}, "rule one_of does not fit a range question"),
        (2, {"at_least": 20, "at_most": 40}, "a rule is exactly one of"),
        (0, {"equals": True}, "equals takes 'yes' or 'no', quoted"),
        (1, {"one_of": ["sundays"]}, "one_of takes posted option ids"),
        (2, {"at_least": 61}, "at_least must sit inside the range"),
        (2, {"between": [30, 20]}, "between must sit inside the range, low first"),
        (2, {"at_least": True}, "is not a whole number"),
    ],
)
def test_a_rule_that_does_not_fit_its_kind_is_refused(
    tmp_path: Path, index: int, rule: dict[str, Any], words: str
) -> None:
    doc = _doc()
    doc["roles"][0]["questions"][index]["rule"] = rule
    _refused(tmp_path, doc, words)


def test_options_or_a_range_on_the_wrong_kind_and_duplicate_ids_are_refused(tmp_path: Path) -> None:
    doc = _doc()
    doc["roles"][0]["questions"][0]["options"] = [{"id": "a", "say": "a"}, {"id": "b", "say": "b"}]
    _refused(tmp_path, doc, "options belong to a choice question only")
    doc = _doc()
    doc["roles"][0]["questions"][0]["range"] = {"min": 0, "max": 9, "unit": "years"}
    _refused(tmp_path, doc, "a range belongs to a range question only")
    doc = _doc()
    doc["roles"][0]["questions"][1]["id"] = "q1"
    _refused(tmp_path, doc, "question q1: the id is used twice")
    doc = _doc()
    doc["roles"][1]["id"] = "care-aide"
    _refused(tmp_path, doc, "role care-aide: the id is used twice")


def test_a_question_without_its_asks_rule_or_reason_is_refused(tmp_path: Path) -> None:
    for key in ("asks", "reason", "rule"):
        doc = _doc()
        del doc["roles"][0]["questions"][0][key]
        _refused(tmp_path, doc, "role care-aide question q1")


# A question on a topic the line never asks about, each in its own test.


def _asking(tmp_path: Path, say: str, topic: str, field: str = "say") -> None:
    doc = _doc()
    doc["roles"][0]["questions"][0][field] = say
    _refused(tmp_path, doc, f"asks about {topic}")


def test_an_age_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "How old are you?", "age or birth date")
    _asking(tmp_path, "What is your date of birth?", "age or birth date")


def test_a_citizenship_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "Are you a US citizen?", "citizenship or nationality")


def test_a_pay_history_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "What is your current pay?", "salary history or current pay")
    _asking(tmp_path, "Please give your salary history.", "salary history or current pay")


def test_a_zip_code_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "What is your zip code?", "zip code or neighbourhood")
    _asking(tmp_path, "Which neighborhood do you live in?", "zip code or neighbourhood")


def test_a_health_question_is_refused_but_the_accommodation_clause_is_not(tmp_path: Path) -> None:
    _asking(tmp_path, "Do you have any medical conditions?", "health or disability")
    _asking(tmp_path, "Do you have a disability?", "health or disability")
    doc = _doc()
    doc["roles"][0]["questions"][0]["say"] = (
        "Can you lift 50 pounds, with or without a reasonable accommodation for a disability?"
    )
    _load(tmp_path, doc)


def test_an_arrest_or_conviction_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "Have you ever been convicted of a crime?", "arrests or convictions")
    _asking(tmp_path, "Have you been arrested?", "arrests or convictions")


def test_a_pregnancy_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "Are you pregnant?", "pregnancy")


def test_a_marital_or_family_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "Are you married?", "marital or family status")
    _asking(tmp_path, "Do you have children?", "marital or family status")


def test_a_religion_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "Which church do you attend?", "religion")


def test_a_race_or_ethnicity_question_is_refused(tmp_path: Path) -> None:
    _asking(tmp_path, "What is your ethnicity?", "race or ethnicity")


def test_a_topic_in_the_reason_or_the_asks_is_refused_too(tmp_path: Path) -> None:
    _asking(tmp_path, "Aides must be at least 21 years old.", "age or birth date", field="reason")
    _asking(tmp_path, "no criminal record", "arrests or convictions", field="asks")


def test_a_topic_in_a_range_unit_is_refused(tmp_path: Path) -> None:
    """The unit is said back after every answer ("Noted: 30 years of age."), so an age question cannot hide in it
    behind a say that names no topic (DR-025 section 4)."""
    doc = _doc()
    q3 = doc["roles"][0]["questions"][2]
    assert q3["kind"] == "range"
    q3["say"] = "The posting asks for at least 21. How many years have you had so far?"
    q3["range"]["unit"] = "years of age"
    q3["asks"] = "at least 21"
    q3["rule"] = {"at_least": 21}
    _refused(tmp_path, doc, "its range unit asks about age or birth date")


def test_no_committed_question_names_a_forbidden_topic() -> None:
    # The loader already refuses one at start; this says so in one line for the teach-back.
    assert len(FORBIDDEN_TOPICS) == 10 and load_roles()


# The words the line says back.


def _q(kind: str, **fields: Any) -> Question:
    roles = load_roles()
    found = next(q for r in roles.values() for q in r.questions if q.kind == kind)
    return found if not fields else Question(**{**found.__dict__, **fields})


def test_a_value_is_said_back_as_the_applicants_own_choice() -> None:
    yes_no, choice = _q("yes_no"), _q("choice")
    hours = load_roles()["care-aide"].questions[2]
    years = load_roles()["front-desk"].questions[1]
    assert spoken_value(yes_no, "yes") == "yes" and spoken_value(yes_no, "no") == "no"
    assert spoken_value(yes_no, "declined") == "skipped" and spoken_value(yes_no, "unclear") == "not clear"
    assert spoken_value(choice, "weekends") == "weekends only"
    assert spoken_value(hours, "25") == "25 hours a week" and spoken_value(hours, "1") == "1 hour a week"
    assert spoken_value(years, "3") == "3 years" and spoken_value(years, "1") == "1 year"


def test_the_allowed_values_name_every_posted_value() -> None:
    aide = load_roles()["care-aide"]
    assert allowed_values(aide.questions[0]) == "yes, no, declined or unclear"
    assert allowed_values(aide.questions[1]) == "weekdays, weekends, both, declined or unclear"
    assert (
        allowed_values(aide.questions[2]) == "a whole number from 0 to 60 (hours a week), declined or unclear"
    )
