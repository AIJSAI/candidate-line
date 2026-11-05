"""The eval case file. Loaded strictly: an unknown key or an unknown check is a refused case, never a pass.

Why strict: AGENTS.md rule 4 forbids bending a case to make a run pass, and a case the runner silently
cannot read is the quietest way to bend one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Kind = Literal["boundary", "regression"]

CHECKS = (
    "heard_matches",
    "spoken_matches",
    "spoken_not_matches",
    "cites",
    "tool_called",
    "state",
    "tier",
    # DR-025 section 18: a regular expression over the subject and the email of each hand-off the turn posted.
    "hand_off_matches",
    "hand_off_not_matches",
)
# `outbound` names an application in data/applications.yaml: the case is the line's call to that applicant.
CASE_KEYS = {"id", "title", "kind", "channel", "turns", "judge", "spec_ref", "note", "outbound"}
TURN_KEYS = {"user", "checks", "silence_seconds", "fixed"}
# A fixed turn runs no model: its spoken text is that fixed line for the case's applicant (DR-025 section 18).
FIXED_LINES = ("opening", "voicemail")
_OUTBOUND_CODE = re.compile(r"ACME-\d{4}")


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    arg: Any


@dataclass(frozen=True)
class Turn:
    user: str | None
    silence_seconds: float | None
    checks: tuple[Check, ...]
    fixed: str | None = None  # "opening" or "voicemail", on an outbound case only


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    kind: Kind
    channel: Literal["text", "voice"]
    turns: tuple[Turn, ...]
    judge: dict[str, Any] | None = None
    spec_ref: str | None = None  # the spec section and line the case tests (card 02)
    note: str | None = None  # one line on why the case exists
    outbound: str | None = None  # the application code the line calls (DR-025 section 18)
    path: Path | None = field(default=None, compare=False)


def _check(raw: Any, where: str) -> Check:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise CaseError(f"{where}: a check is one key, one of {CHECKS}")
    ((name, arg),) = raw.items()
    if name not in CHECKS:
        raise CaseError(f"{where}: unknown check {name!r}; the runner knows {CHECKS}")
    return Check(name, arg)


def parse_case(raw: dict[str, Any], path: Path | None = None) -> Case:
    where = str(path or "<case>")
    unknown = set(raw) - CASE_KEYS
    if unknown:
        raise CaseError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("id", "title", "kind", "turns"):
        if key not in raw:
            raise CaseError(f"{where}: missing {key!r}")
    if raw["kind"] not in ("boundary", "regression"):
        raise CaseError(f"{where}: kind must be boundary or regression")
    outbound = raw.get("outbound")
    if outbound is not None and not (isinstance(outbound, str) and _OUTBOUND_CODE.fullmatch(outbound)):
        raise CaseError(f"{where}: outbound must be an application code, ACME and four digits")
    turns = []
    for i, t in enumerate(raw["turns"]):
        if not isinstance(t, dict) or set(t) - TURN_KEYS:
            raise CaseError(f"{where}: turn {i} has keys outside {sorted(TURN_KEYS)}")
        if sum(key in t for key in ("user", "silence_seconds", "fixed")) != 1:
            raise CaseError(f"{where}: turn {i} needs exactly one of user, silence_seconds, fixed")
        fixed = t.get("fixed")
        if "fixed" in t and fixed not in FIXED_LINES:
            raise CaseError(f"{where}: turn {i}: fixed must be one of {FIXED_LINES}")
        if fixed is not None and outbound is None:
            raise CaseError(
                f"{where}: turn {i}: a fixed line belongs to an outbound case, which names its applicant"
            )
        checks = tuple(_check(c, f"{where} turn {i}") for c in t.get("checks", []))
        turns.append(Turn(t.get("user"), t.get("silence_seconds"), checks, fixed))
    if not turns:
        raise CaseError(f"{where}: a case needs at least one turn")
    return Case(
        id=str(raw["id"]),
        title=str(raw["title"]),
        kind=raw["kind"],
        channel=raw.get("channel", "text"),
        turns=tuple(turns),
        judge=raw.get("judge"),
        spec_ref=None if raw.get("spec_ref") is None else str(raw["spec_ref"]),
        note=None if raw.get("note") is None else str(raw["note"]),
        outbound=outbound,
        path=path,
    )


def load_cases(folder: Path) -> list[Case]:
    cases = []
    for path in sorted(folder.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise CaseError(f"{path}: not a mapping")
        cases.append(parse_case(raw, path))
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise CaseError("duplicate case ids")
    return cases
