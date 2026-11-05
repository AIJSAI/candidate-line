"""Deterministic checks over one turn. A check whose component has not landed yet (the tool loop, the tier rule)
returns a verdict marked pending: not a pass, so a case never passes because a check was skipped, and not a failure,
so the gate can be read between the cards that land those components (DR-010)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from candidate_line.escalation import Escalation, format_email, format_subject
from candidate_line.evals.schema import Check
from candidate_line.text import straighten
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
    heard, spoken = straighten(result.heard), straighten(result.spoken)
    if name == "heard_matches":
        ok = re.search(str(arg), heard) is not None
        return Verdict(check, ok, f"heard {result.heard!r}")
    if name == "spoken_matches":
        ok = re.search(str(arg), spoken) is not None
        return Verdict(check, ok, f"spoken {result.spoken!r}")
    if name == "spoken_not_matches":
        hit = re.search(str(arg), spoken)
        # The whole reply is printed, because a refusal can quote the forbidden phrase ("I can't tell you whether
        # you'll move on") and only the sentence around the match says which it was (the dry run of card 02).
        return Verdict(
            check, hit is None, f"matched {hit.group(0)!r} in {result.spoken!r}" if hit else "no match"
        )
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
    if name in ("hand_off_matches", "hand_off_not_matches"):
        # The hand-offs the turn posted (TurnResult.hand_offs, DR-025 section 3).
        return _hand_off_verdict(check, result.hand_offs)
    return Verdict(check, False, f"unknown check {name!r}")


def _hand_off_verdict(check: Check, hand_offs: Sequence[Escalation]) -> Verdict:
    """The pattern is searched in each hand-off's subject and email body as the recruiter receives them, one
    hand-off at a time, so a ^ anchors at a subject. hand_off_matches fails when nothing was posted; the not form
    passes then, since nothing posted can carry the words."""
    texts = [straighten(f"{format_subject(e)}\n{format_email(e)}") for e in hand_offs]
    subjects = [format_subject(e) for e in hand_offs]
    if check.name == "hand_off_matches":
        if not texts:
            return Verdict(check, False, "no hand-off was posted on this turn")
        ok = any(re.search(str(check.arg), text) for text in texts)
        return Verdict(check, ok, f"hand-offs {subjects}")
    hit = next((m for text in texts if (m := re.search(str(check.arg), text))), None)
    return Verdict(check, hit is None, f"matched {hit.group(0)!r} in {subjects}" if hit else "no match")
