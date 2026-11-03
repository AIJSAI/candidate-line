"""The eval case file. Loaded strictly: an unknown key or an unknown check is a refused case, never a pass.

Why strict: AGENTS.md rule 4 forbids bending a case to make a run pass, and a case the runner silently
cannot read is the quietest way to bend one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Kind = Literal["boundary", "regression"]

CHECKS = ("heard_matches", "spoken_matches", "spoken_not_matches", "cites", "tool_called", "state", "tier")
CASE_KEYS = {"id", "title", "kind", "channel", "turns", "judge", "spec_ref", "note"}
TURN_KEYS = {"user", "checks", "silence_seconds"}


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
    turns = []
    for i, t in enumerate(raw["turns"]):
        if not isinstance(t, dict) or set(t) - TURN_KEYS:
            raise CaseError(f"{where}: turn {i} has keys outside {sorted(TURN_KEYS)}")
        if ("user" in t) == ("silence_seconds" in t):
            raise CaseError(f"{where}: turn {i} needs exactly one of user, silence_seconds")
        checks = tuple(_check(c, f"{where} turn {i}") for c in t.get("checks", []))
        turns.append(Turn(t.get("user"), t.get("silence_seconds"), checks))
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
