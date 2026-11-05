"""The before_speak guard: what Gus must never say, checked sentence by sentence against a lexicon (card 05)."""

from candidate_line.guard.guard import LEXICON_PATH, Guard, Rule, Verdict, default_guard, load_lexicon

__all__ = ["LEXICON_PATH", "Guard", "Rule", "Verdict", "default_guard", "load_lexicon"]
