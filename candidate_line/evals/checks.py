"""Deterministic checks over one turn. A check whose component has not landed yet (the tool loop, the tier rule)
returns a verdict marked pending: not a pass, so a case never passes because a check was skipped, and not a failure,
so the gate can be read between the cards that land those components (DR-010)."""

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
    pending: bool = False  # the component this check reads has not landed; neither a pass nor a failure


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
        # The id may be said aloud or carried on the turn by the retrieval step (card 04); either counts.
        cited = set(result.cited) | set(SECTION_ID.findall(result.spoken))
        return Verdict(check, str(arg) in cited, f"cited {sorted(cited) or 'nothing'}")
    if name == "tool_called":
        wanted = str(arg["name"]) if isinstance(arg, dict) else str(arg)
        if result.tools_called is None:
            return Verdict(check, False, "pending: the tool loop has not landed (card 04)", pending=True)
        return Verdict(
            check, wanted in result.tools_called, f"tools called {list(result.tools_called) or 'none'}"
        )
    if name == "state":
        if result.state is None:
            return Verdict(check, False, "pending: no tool has reported state yet (card 04)", pending=True)
        wanted = dict(arg) if isinstance(arg, dict) else {}
        differs = {k: v for k, v in wanted.items() if result.state.get(k) != v}
        return Verdict(
            check, not differs, f"state differs on {differs}" if differs else f"state {dict(result.state)}"
        )
    if name == "tier":
        if result.tier is None:
            return Verdict(check, False, "pending: the tier rule has not landed (card 06)", pending=True)
        return Verdict(check, str(arg) == result.tier, f"tier {result.tier}")
    return Verdict(check, False, f"unknown check {name!r}")
