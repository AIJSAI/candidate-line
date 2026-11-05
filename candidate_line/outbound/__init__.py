"""The outbound call's own parts: the signed intake, the contacts store, the calling window and the dialler.

Why a package of its own: the outbound call shares the inbound line's /voice, media stream, turn loop and ledger
(spec section 9), but these four pieces exist only for it, and each is a pure function or a small store that is
tested alone with a pinned clock and a fake Twilio (DR-025, sections 9 to 12).

What this module holds is the surface the other lanes' code gives this one. Card 08's merge order is lane C's
ledger, lane A, then lane B, so on this branch alone the lines in `persona.py`, the outbound tool specs and the
ledger's key functions are not there yet. The fallbacks below carry DR-025's own words and definitions so the
branch runs and tests on its own; once the merge brings the real ones the imports find them and every fallback
here is dead code, to delete in the merge commit.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from candidate_line.brain import ToolSpec

try:  # lane A: the fixed lines of spec 9.9, word for word (DR-025 section 13)
    from candidate_line.persona import PIN_ASK, outbound_opening, voicemail_line  # type: ignore[attr-defined]
except ImportError:
    PIN_ASK = (
        "To go on, please say the four-digit PIN you chose when you applied. "
        "Or say stop, and this line won't call you again."
    )

    def outbound_opening(first_name: str) -> str:
        return (
            f"Hello, this is ACME's automated hiring line, calling for {first_name} about a job application. "
            "I'm Gus, an automated voice, and this call is transcribed so a recruiter can read your answers. "
            "No audio is kept."
        )

    def voicemail_line(first_name: str, line_number: str) -> str:
        # As lane A's helper does: the line's own E.164 number in, said digit by digit in its three groups.
        return (
            f"This is ACME's automated hiring line with a message for {first_name} about a job application. "
            f"Please call us back at {spoken_number(line_number)}, or we'll try again later. "
            "To stop these calls, call that number and say stop."
        )


try:  # lane A: the outbound call's tools (DR-025 section 1)
    from candidate_line.tools import OUTBOUND_TOOL_SPECS  # type: ignore[attr-defined]
except ImportError:
    OUTBOUND_TOOL_SPECS: Sequence[ToolSpec] = ()


try:  # lane C: the keyed hashes (DR-025 section 7)
    from candidate_line.tools.ledger import derive_key, number_hmac  # type: ignore[attr-defined]
except ImportError:

    def derive_key(root: str, purpose: str) -> bytes:
        return hmac.new(root.encode("utf-8"), f"candidate-line {purpose}".encode(), hashlib.sha256).digest()

    def number_hmac(key: bytes, e164: str) -> str:
        return hmac.new(key, e164.encode("utf-8"), hashlib.sha256).hexdigest()


# The purpose the number's HMAC key is derived under, so intake, the dialler and the ledger's opt-outs all hash a
# number the same way (DR-025 section 7: the PIN and number keys derive from INTAKE_SIGNING_KEY).
NUMBER_KEY_PURPOSE = "number"


def number_key(signing_key: str) -> bytes:
    return derive_key(signing_key, NUMBER_KEY_PURPOSE)


def spoken_number(e164: str) -> str:
    """A US number in E.164 form as its ten national digits in their groups of three, three and four, each digit
    said apart, so the voice never reads a group as one large number. Lane A's `persona.spoken_number` is the
    same rule."""
    digits = "".join(ch for ch in e164 if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return " ".join(digits)
    return ", ".join(" ".join(group) for group in (digits[:3], digits[3:6], digits[6:]))


class Applicant(Protocol):
    """What lane B reads of `tools.ledger.Applicant` (DR-025 section 7)."""

    code: str
    first_name: str
    role: str
    zone: str
    received_at: str
    consent: Mapping[str, Any]
    number_hmac: str | None

    @property
    def consented(self) -> bool: ...


class OutboundLedger(Protocol):
    """The ledger methods lane B calls, by DR-025 section 7's names, with `set_not_dialled` added (asked of lane C
    in lane B's report): the allow-list check at dial time must record why an application was never dialled."""

    def applicant(self, code: object) -> Applicant | None: ...

    def add_application(
        self,
        *,
        first_name: str,
        role: str,
        zone: str,
        pin: str,
        consent: Mapping[str, Any],
        number_hmac: str,
        number_masked: str,
        nonce: str,
        not_dialled: str | None = None,
        received_at: datetime | None = None,
    ) -> Applicant: ...

    def nonce_seen(self, nonce: str, since: datetime) -> bool: ...

    def opted_out(self, code: str | None = None, number_hmac: str | None = None) -> bool: ...

    def schedule_dial(self, code: str, attempt: int, due_at: datetime) -> dict[str, Any]: ...

    def claim_due_dial(
        self, now: datetime, max_per_day: int, ready: Callable[[dict[str, Any], Applicant], bool]
    ) -> dict[str, Any] | None: ...

    def bind_call(self, dial_id: str, call_sid: str) -> dict[str, Any] | None: ...

    def update_dial(self, key: str, **fields: Any) -> dict[str, Any] | None: ...

    def dial(self, key: str) -> dict[str, Any] | None: ...

    def dials(self, code: str | None = None) -> list[dict[str, Any]]: ...

    def dials_placed_today(self) -> int: ...

    def screen(self, code: str) -> dict[str, Any] | None: ...

    def purge_answers(self, before: datetime) -> int: ...

    def set_not_dialled(self, code: str, reason: str) -> None: ...


__all__ = [
    "NUMBER_KEY_PURPOSE",
    "OUTBOUND_TOOL_SPECS",
    "PIN_ASK",
    "Applicant",
    "OutboundLedger",
    "derive_key",
    "number_hmac",
    "number_key",
    "outbound_opening",
    "spoken_number",
    "voicemail_line",
]
