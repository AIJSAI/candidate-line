"""The outbound call's own parts: the signed intake, the contacts store, the calling window and the dialler.

Why a package of its own: the outbound call shares the inbound line's /voice, media stream, turn loop and ledger
(spec section 9), but these four pieces exist only for it, and each is a pure function or a small store that is
tested alone with a pinned clock and a fake Twilio (DR-025, sections 9 to 12).

What this module holds is the surface the other parts of card 08 give this one, by their own names: the fixed
lines from `persona.py`, the outbound tool specs from the tools, and the ledger's applicant and keyed hashes.
"""

from __future__ import annotations

from candidate_line.persona import PIN_ASK, outbound_opening, voicemail_line
from candidate_line.tools import OUTBOUND_TOOL_SPECS
from candidate_line.tools.ledger import NUMBER_PURPOSE, Applicant, Ledger, derive_key, number_hmac


def number_key(signing_key: str) -> bytes:
    """The key a number's HMAC is made under, derived from INTAKE_SIGNING_KEY for the number purpose, so intake,
    the dialler and the ledger's opt-outs all hash a number the same way (DR-025 section 7)."""
    return derive_key(signing_key, NUMBER_PURPOSE)


__all__ = [
    "NUMBER_PURPOSE",
    "OUTBOUND_TOOL_SPECS",
    "PIN_ASK",
    "Applicant",
    "Ledger",
    "derive_key",
    "number_hmac",
    "number_key",
    "outbound_opening",
    "voicemail_line",
]
