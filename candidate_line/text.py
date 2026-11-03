"""One table for straightening curly quotes, shared by the eval checks and the guard.

Why its own module: a pattern written with ' must catch both the straight and the curly apostrophe, in the evals
exactly as in the guard (card 05's dry run); the guard cannot import it from the checks, because the checks import
the turn, the turn imports the hooks and the hooks import the guard.
"""

from __future__ import annotations

_CURLY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def straighten(text: str) -> str:
    """A model writes curly apostrophes as often as straight ones; the eval's and the guard's patterns see one kind."""
    return text.translate(_CURLY)
