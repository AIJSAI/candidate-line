"""Deterministic checks over one turn. A check the line cannot evaluate yet (tools, state, tiers land live)
returns a failure that says so, so a case never passes because its check was skipped."""

from __future__ import annotations

import re
from dataclasses import dataclass

from candidate_line.evals.schema import Check
from candidate_line.turn import TurnResult

SECTION_ID = re.compile(r"\bF\d(?:\.\d)?\b")


@dataclass(frozen=True)
class Verdict:
    check: Check
    passed: bool
    detail: str


def evaluate(check: Check, result: TurnResult) -> Verdict:
    name, arg = check.name, check.arg
    if name == "heard_matches":
        ok = re.search(str(arg), result.heard) is not None
        return Verdict(check, ok, f"heard {result.heard!r}")
    if name == "spoken_matches":
        ok = re.search(str(arg), result.spoken) is not None
        return Verdict(check, ok, f"spoken {result.spoken!r}")
    if name == "spoken_not_matches":
        hit = re.search(str(arg), result.spoken)
        return Verdict(check, hit is None, f"matched {hit.group(0)!r}" if hit else "no match")
    if name == "cites":
        cited = set(SECTION_ID.findall(result.spoken))
        return Verdict(check, str(arg) in cited, f"cited {sorted(cited) or 'nothing'}")
    # The remaining checks need the tools, the state and the tiers, which are written live on Wednesday.
    return Verdict(check, False, f"check {name!r} is not evaluable until its component lands (see DR-010)")
