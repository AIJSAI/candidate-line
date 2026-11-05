"""Two small tables the text paths share: straightening curly quotes, for the eval checks and the guard, and the
filler words, for the media session and the hooks.

Why its own module: a pattern written with ' must catch both the straight and the curly apostrophe, in the evals
exactly as in the guard (card 05's dry run); the guard cannot import it from the checks, because the checks import
the turn, the turn imports the hooks and the hooks import the guard. The fillers sit here for the same reason: the
media session imports the hooks, so the hooks cannot import the session.
"""

from __future__ import annotations

# Sounds a caller makes while thinking. On a real call on 2026-11-04 the caller's "Um," cut Gus off mid-sentence and
# then became a turn of its own that Gus answered. So a transcript made only of these is not speech: it never barges
# in, never supersedes a turn, never holds the turn open and never becomes one. "Mm-hmm" and "uh-huh" are not here
# because callers say them for yes.
FILLERS = frozenset({"um", "uh", "hmm", "mm", "mhm", "er", "erm", "ah", "huh"})

_CURLY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def straighten(text: str) -> str:
    """A model writes curly apostrophes as often as straight ones; the eval's and the guard's patterns see one kind."""
    return text.translate(_CURLY)
