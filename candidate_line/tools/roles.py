"""The roles ACME posted and the questions each one asks, read from data/roles.yaml (DR-025 section 4).

Why a strict loader: the gate in rules.py compares an applicant's answer with what the employer posted, so the file
is the gate's only input besides the answers. A key the line does not know (a score, a weight, a knockout), a rule
the kind cannot hold, or a question on a topic the line never asks about would let the file decide something the
spec forbids, so each is refused when the file is read, which is at start, never on a live call.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

DATA = Path(__file__).resolve().parents[2] / "data"
ROLES_PATH = DATA / "roles.yaml"

Kind = Literal["yes_no", "choice", "range"]
KINDS: tuple[Kind, ...] = ("yes_no", "choice", "range")
# The values every question takes besides its own: a skip, and words the model could not map to a posted value.
DECLINED = "declined"
UNCLEAR = "unclear"
# The only rule forms, by kind (spec 9.10). A rule is one of these and nothing else, so no file can hold a
# threshold over several answers or a weight.
RULE_FORMS: dict[Kind, frozenset[str]] = {
    "yes_no": frozenset({"equals"}),
    "choice": frozenset({"one_of"}),
    "range": frozenset({"at_least", "at_most", "between"}),
}
# A recorded number is a whole number from 0 to 999 (spec 3.7), so a scale never runs past it.
MAX_RANGE = 999

_TOP_KEYS = frozenset({"synthetic", "firm", "roles", "interview_slots"})
_ROLE_KEYS = frozenset({"id", "title", "site", "recruiter", "questions"})
_QUESTION_KEYS = frozenset({"id", "say", "kind", "options", "range", "asks", "rule", "reason"})
_OPTION_KEYS = frozenset({"id", "say"})
_RANGE_KEYS = frozenset({"min", "max", "unit"})
_SLOT_KEYS = frozenset({"id", "start", "duration_min", "recruiter", "status", "held_by"})
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")

# The topics the line never asks about (DR-025 section 4), each as the words that name it. The accommodation
# clause is taken out before matching, because a physical-ability question must be able to offer it. Each is
# checked in the question's own words, its options, what it asks for and its reason, since a reason "aides must be
# over 18" posts an age rule as surely as the question would.
_ACCOMMODATION = re.compile(
    r"(?i)\bwith or without (a |any )?reasonable accommodations?( for (a |any )?disabilit(y|ies))?"
)
FORBIDDEN_TOPICS: dict[str, re.Pattern[str]] = {
    "age or birth date": re.compile(
        r"(?i)\b(age|ages|aged|how old|years old|years of age|birth ?dates?|date of birth|birthday|birth year|"
        r"born)\b"
    ),
    "citizenship or nationality": re.compile(
        r"(?i)\b(citizen|citizens|citizenship|nationality|national origin|country of (origin|birth)|"
        r"immigration status|native language|mother tongue)\b"
    ),
    "salary history or current pay": re.compile(
        r"(?i)\b(salary|pay|wage|wages|earnings|compensation) history\b|"
        r"\b(current|previous|prior|last|past|present) (salary|pay|wage|wages|earnings|compensation|rate)\b|"
        r"\bhow much (do|did) you (make|earn|get paid)\b|\bwhat (do|did) you (make|earn)\b"
    ),
    "zip code or neighbourhood": re.compile(
        r"(?i)\b(zip|zip ?codes?|postal codes?|post ?codes?|neighbou?rhoods?|part of town|home address|"
        r"street address|where (do|did) you live)\b"
    ),
    "health or disability": re.compile(
        r"(?i)\b(health|healthy|medical|medications?|medicines?|disabilit(y|ies)|disabled|illness(es)?|ill|"
        r"sick|sickness|diagnos[a-z]*|injur(y|ies|ed)|handicap[a-z]*|impairments?|mental|chronic|"
        r"(physical|medical|health) conditions?|workers' compensation)\b"
    ),
    "arrests or convictions": re.compile(
        r"(?i)\b(arrest|arrests|arrested|convict|convicted|convictions?|criminal|felon|felony|felonies|"
        r"misdemeanou?rs?|jail|prison|police record|background check)\b"
    ),
    "pregnancy": re.compile(r"(?i)\b(pregnant|pregnancy|pregnancies|expecting a (baby|child)|maternity)\b"),
    "marital or family status": re.compile(
        r"(?i)\b(married|marital|marriage|spouse|husband|wife|divorced|widowed|maiden name|family status|"
        r"family plans|single parent|(do|will) you have (any )?(children|kids)|your (children|kids|family)|"
        r"childcare arrangements|child care arrangements)\b"
    ),
    "religion": re.compile(
        r"(?i)\b(religion|religions|religious|church|mosque|synagogue|temple|faith|worship|sabbath|pray|prayer)\b"
    ),
    "race or ethnicity": re.compile(
        r"(?i)\b(race|races|racial|ethnic|ethnicity|ancestry|skin colou?r|colou?r of your skin)\b"
    ),
}


class RolesError(ValueError):
    """data/roles.yaml holds something the gate must never read. The message names the role, question and key."""


@dataclass(frozen=True)
class Option:
    id: str
    say: str  # the words the line says and says back ("weekends only")


@dataclass(frozen=True)
class Range:
    min: int
    max: int
    unit: str  # said after the number ("hours a week")


@dataclass(frozen=True)
class Rule:
    form: str  # one of RULE_FORMS[kind]
    value: str | int | tuple[str, ...] | tuple[int, int]


@dataclass(frozen=True)
class Question:
    id: str
    say: str  # asked word for word, in posted order
    kind: Kind
    options: tuple[Option, ...]  # choice only
    range: Range | None  # range only
    asks: str  # the posted requirement in words, for the not-met line and the cockpit
    rule: Rule
    reason: str  # why the requirement is job-related, as posted

    def option(self, option_id: str) -> Option | None:
        return next((o for o in self.options if o.id == option_id), None)


@dataclass(frozen=True)
class Role:
    id: str
    title: str  # said after the PIN, never before
    site: str
    recruiter: str  # a label the interview slots name
    questions: tuple[Question, ...]

    def question(self, question_id: str) -> Question | None:
        return next((q for q in self.questions if q.id == question_id), None)


def load_roles(path: Path = ROLES_PATH) -> dict[str, Role]:
    """Every role in the file, by id, or a RolesError naming the first thing the gate must never read."""
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping):
        raise RolesError(f"{Path(path).name}: the file is not a mapping")
    _keys(doc, _TOP_KEYS, "the file")
    rows = doc.get("roles")
    if not isinstance(rows, list) or not rows:
        raise RolesError("roles: the file names no role")
    roles: dict[str, Role] = {}
    for row in rows:
        role = _role(row)
        if role.id in roles:
            raise RolesError(f"role {role.id}: the id is used twice")
        roles[role.id] = role
    _slots(doc.get("interview_slots"))
    return roles


@functools.cache
def default_roles() -> dict[str, Role]:
    """The committed roles, read once. A broken file raises here, which screening.py reaches at import."""
    return load_roles(ROLES_PATH)


def role(role_id: str) -> Role | None:
    return default_roles().get(str(role_id))


def spoken_value(question: Question, value: str) -> str:
    """A recorded value as the line says it back after "Noted:" (spec 9.9): the applicant's own choice, never a
    reaction to it."""
    if value == DECLINED:
        return "skipped"
    if value == UNCLEAR:
        return "not clear"
    if question.kind == "yes_no":
        return value
    if question.kind == "choice":
        found = question.option(value)
        return found.say if found is not None else value
    assert question.range is not None
    unit = question.range.unit
    if value == "1":
        # "1 years" said aloud is a slip a person would not make; the posted unit is kept, only its plural goes.
        first, _, rest = unit.partition(" ")
        unit = f"{first.removesuffix('s')} {rest}".strip() if first.endswith("s") else unit
    return f"{value} {unit}"


def allowed_values(question: Question) -> str:
    """The values record_answer takes for this question, in the words the model reads in a result or a refusal."""
    if question.kind == "yes_no":
        return "yes, no, declined or unclear"
    if question.kind == "choice":
        return ", ".join(o.id for o in question.options) + ", declined or unclear"
    assert question.range is not None
    r = question.range
    return f"a whole number from {r.min} to {r.max} ({r.unit}), declined or unclear"


# Inside the loader.


def _keys(row: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(str(k) for k in row if k not in allowed)
    if unknown:
        raise RolesError(
            f"{where}: unknown key {', '.join(unknown)}; the line reads only {', '.join(sorted(allowed))}"
        )


def _text(row: Mapping[str, Any], key: str, where: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RolesError(f"{where}: {key} must be words")
    return " ".join(value.split())


def _id(row: Mapping[str, Any], where: str) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise RolesError(f"{where}: the id must be a short lower-case slug")
    return value


def _whole(value: object, where: str) -> int:
    # bool is an int in Python, and a rule of "at_least: true" is no number.
    if not isinstance(value, int) or isinstance(value, bool):
        raise RolesError(f"{where}: {value!r} is not a whole number")
    return value


def _role(row: object) -> Role:
    if not isinstance(row, Mapping):
        raise RolesError("roles: each role must be a mapping")
    where = f"role {row.get('id', '?')}"
    _keys(row, _ROLE_KEYS, where)
    role_id = _id(row, where)
    questions_raw = row.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise RolesError(f"{where}: a role posts at least one question")
    questions: list[Question] = []
    for raw in questions_raw:
        question = _question(raw, role_id)
        if any(q.id == question.id for q in questions):
            raise RolesError(f"{where} question {question.id}: the id is used twice")
        questions.append(question)
    return Role(
        id=role_id,
        title=_text(row, "title", where),
        site=_text(row, "site", where),
        recruiter=_text(row, "recruiter", where),
        questions=tuple(questions),
    )


def _question(row: object, role_id: str) -> Question:
    if not isinstance(row, Mapping):
        raise RolesError(f"role {role_id}: each question must be a mapping")
    where = f"role {role_id} question {row.get('id', '?')}"
    _keys(row, _QUESTION_KEYS, where)
    kind = row.get("kind")
    if kind not in KINDS:
        raise RolesError(f"{where}: kind must be one of {', '.join(KINDS)}")
    if "options" in row and kind != "choice":
        raise RolesError(f"{where}: options belong to a choice question only")
    if "range" in row and kind != "range":
        raise RolesError(f"{where}: a range belongs to a range question only")
    options = _options(row.get("options"), where) if kind == "choice" else ()
    scale = _range(row.get("range"), where) if kind == "range" else None
    question = Question(
        id=_id(row, where),
        say=_text(row, "say", where),
        kind=kind,
        options=options,
        range=scale,
        asks=_text(row, "asks", where),
        rule=_rule(row.get("rule"), kind, options, scale, where),
        reason=_text(row, "reason", where),
    )
    _topics(question, where)
    return question


def _options(raw: object, where: str) -> tuple[Option, ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise RolesError(f"{where}: a choice question posts at least two options")
    options: list[Option] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise RolesError(f"{where}: each option must be a mapping")
        _keys(item, _OPTION_KEYS, f"{where} option")
        option = Option(id=_id(item, f"{where} option"), say=_text(item, "say", f"{where} option"))
        if option.id in (DECLINED, UNCLEAR) or any(o.id == option.id for o in options):
            raise RolesError(f"{where} option {option.id}: the id is used twice or is a reserved value")
        options.append(option)
    return tuple(options)


def _range(raw: object, where: str) -> Range:
    if not isinstance(raw, Mapping):
        raise RolesError(f"{where}: a range question posts its range")
    _keys(raw, _RANGE_KEYS, f"{where} range")
    low, high = _whole(raw.get("min"), f"{where} range"), _whole(raw.get("max"), f"{where} range")
    if not 0 <= low < high <= MAX_RANGE:
        raise RolesError(f"{where} range: min and max must run upward within 0 to {MAX_RANGE}")
    return Range(min=low, max=high, unit=_text(raw, "unit", f"{where} range"))


def _rule(raw: object, kind: Kind, options: tuple[Option, ...], scale: Range | None, where: str) -> Rule:
    if not isinstance(raw, Mapping) or len(raw) != 1:
        raise RolesError(f"{where}: a rule is exactly one of {', '.join(sorted(RULE_FORMS[kind]))}")
    [(form, value)] = raw.items()
    if form not in RULE_FORMS[kind]:
        raise RolesError(f"{where}: rule {form} does not fit a {kind} question")
    if form == "equals":
        # YAML reads a bare yes as True, so only the quoted words are taken.
        if value not in ("yes", "no"):
            raise RolesError(f"{where}: equals takes 'yes' or 'no', quoted")
        return Rule(form, value)
    if form == "one_of":
        ids = {o.id for o in options}
        if (
            not isinstance(value, list)
            or not value
            or any(v not in ids for v in value)
            or len(set(value)) != len(value)
        ):
            raise RolesError(f"{where}: one_of takes posted option ids, each once")
        return Rule(form, tuple(str(v) for v in value))
    assert scale is not None
    if form == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise RolesError(f"{where}: between takes two numbers")
        low, high = _whole(value[0], where), _whole(value[1], where)
        if not scale.min <= low <= high <= scale.max:
            raise RolesError(f"{where}: between must sit inside the range, low first")
        return Rule(form, (low, high))
    bound = _whole(value, where)
    if not scale.min <= bound <= scale.max:
        raise RolesError(f"{where}: {form} must sit inside the range")
    return Rule(form, bound)


def _topics(question: Question, where: str) -> None:
    fields = {"say": question.say, "asks": question.asks, "reason": question.reason}
    fields |= {f"option {o.id}": o.say for o in question.options}
    for field_name, words in fields.items():
        plain = _ACCOMMODATION.sub(" ", words)
        for topic, pattern in FORBIDDEN_TOPICS.items():
            if pattern.search(plain):
                raise RolesError(
                    f"{where}: its {field_name} asks about {topic}, which the line never asks about"
                )


def _slots(raw: object) -> None:
    """Only the keys of an interview slot; the ledger reads the slots themselves."""
    if raw is None:
        return
    if not isinstance(raw, list):
        raise RolesError("interview_slots must be a list")
    seen: set[str] = set()
    for slot in raw:
        if not isinstance(slot, Mapping):
            raise RolesError("interview_slots: each slot must be a mapping")
        _keys(slot, _SLOT_KEYS, f"interview slot {slot.get('id', '?')}")
        slot_id = str(slot.get("id"))
        if slot_id in seen:
            raise RolesError(f"interview slot {slot_id}: the id is used twice")
        seen.add(slot_id)
