"""The guard over Gus's own words: each sentence speech will say, checked against the lexicon (card 05, DR-020).

Why patterns and not a second model: the guard sits inside the latency budget on every reply (DR-001), so it has
to be deterministic and cost microseconds. Why a file: James approves every rule by diff, and each rule names the
spec line it serves. Why the same splitter as speech: a hit replaces one sentence and the rest is still said, so
the guard must cut the reply exactly where Polly will.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from candidate_line.telephony.audio import split_sentences
from candidate_line.text import straighten

LEXICON_PATH = Path(__file__).with_name("lexicon.txt")

# A refusal cue, not a hit: it excuses a hit that sits inside the refusal (the lexicon's header says how).
REFUSAL_PREFIX = "allow-"
# A PIN said aloud is a leak however the sentence frames it, so no refusal cue excuses these.
UNEXCUSED_PREFIX = "pin-"

# Where a clause ends, so a cue in one clause never excuses a hit in the next ("I can't say, but you did well").
# A comma or colon between digits is a number or a clock time, not a clause. "Except" and its kin turn a refusal
# into an exception that asserts ("I can't tell you anything except that you're a strong candidate"), and "notes
# that say" opens a clause that reports a judgement, so each ends the refusal's clause too.
_CLAUSE_BREAK = re.compile(
    r"[;()\u2013\u2014]|,(?!\d)|(?<!\d):|\s-\s"
    r"|\b(?:but|and|so|though|although|however|yet|because|except|besides|beyond|apart from|other than)\b"
    r"|\b(?:that|which) (?:say|says|said|show|shows|showed|note|notes|noted)\b",
    re.IGNORECASE,
)
# A check the caller's call adds beside the lexicon: it returns a rule id for a sentence, or None. The hooks pass
# one that knows the PINs given on this call, which the lexicon cannot.
Extra = Callable[[str], str | None]
# A hit inside a whether or if clause is the object of a refusal said elsewhere in the sentence, before it or
# after it ("Whether you did well is not something I can judge").
_WHETHER = re.compile(r"\b(?:whether|if)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    pattern: str
    serves: str
    regex: re.Pattern[str] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Verdict:
    sentence: str
    rule_id: str | None = None

    @property
    def label(self) -> str:
        """What the trace records for the sentence: the rule id, or "clean" (card 05's `ctx.data["guard"]`)."""
        return self.rule_id or "clean"


def load_lexicon(path: Path) -> tuple[Rule, ...]:
    """Every rule in file order. A broken line stops the guard at start, never on a live call."""
    rules: list[Rule] = []
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = [part.strip() for part in raw.split("\t")]
        if len(fields) != 3 or not all(fields):
            raise ValueError(
                f"{path.name} line {number}: expected an id, a regex and a spec line, tab-separated"
            )
        rule_id, pattern, serves = fields
        if rule_id in seen:
            raise ValueError(f"{path.name} line {number}: the id {rule_id} is used twice")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"{path.name} line {number}: rule {rule_id} does not compile: {exc}") from exc
        seen.add(rule_id)
        rules.append(Rule(rule_id, pattern, serves, regex))
    return tuple(rules)


class Guard:
    """Reads the lexicon once; after that it is read-only, so one instance serves every call and thread."""

    def __init__(self, path: Path | str = LEXICON_PATH) -> None:
        rules = load_lexicon(Path(path))
        self.rules = tuple(rule for rule in rules if not rule.id.startswith(REFUSAL_PREFIX))
        self.refusals = tuple(rule for rule in rules if rule.id.startswith(REFUSAL_PREFIX))
        if not self.rules:
            raise ValueError(f"{Path(path).name}: no rules, so the guard would catch nothing")

    def check(self, text: str, extra: Extra | None = None) -> list[Verdict]:
        """One verdict per sentence, in reading order. The sentence is kept as written; matching sees it
        straightened, which changes no length, so the two never disagree. `extra` is asked only about a
        sentence the lexicon passed."""
        return [
            Verdict(sentence, self._hit(straighten(sentence)) or (extra(sentence) if extra else None))
            for sentence in split_sentences(text)
        ]

    def apply(self, text: str, fallback: str, extra: Extra | None = None) -> tuple[str, tuple[str, ...]]:
        """The text to speak and the rule ids hit. A clean reply comes back as it was given, so the hook chain
        sees no change; two caught sentences in a row say the fallback once, not twice."""
        verdicts = self.check(text, extra)
        hits = tuple(v.rule_id for v in verdicts if v.rule_id is not None)
        if not hits:
            return text, ()
        spoken: list[str] = []
        for verdict in verdicts:
            if verdict.rule_id is None:
                spoken.append(verdict.sentence)
            elif not spoken or spoken[-1] != fallback:
                spoken.append(fallback)
        return " ".join(part for part in spoken if part), hits

    def _hit(self, sentence: str) -> str | None:
        for rule in self.rules:
            for match in rule.regex.finditer(sentence):
                if rule.id.startswith(UNEXCUSED_PREFIX) or not self._refused(sentence, match.start()):
                    return rule.id
        return None

    def _refused(self, sentence: str, start: int) -> bool:
        head = sentence[:start]
        breaks = [m.end() for m in _CLAUSE_BREAK.finditer(head)]
        clause = head[breaks[-1] :] if breaks else head
        if any(cue.regex.search(clause) for cue in self.refusals):
            return True
        return bool(_WHETHER.search(clause)) and any(cue.regex.search(sentence) for cue in self.refusals)


_default: Guard | None = None


def default_guard() -> Guard:
    """The guard over the committed lexicon, read on first use and shared after that."""
    global _default
    if _default is None:
        _default = Guard()
    return _default
