"""Lane B's stand-ins for the other lanes' outbound surface, for card 08 until the merge.

`FakeLedger` keeps DR-025 section 7's records in memory with the method names and keyword arguments written
there, plus `set_not_dialled`, which lane B asks lane C for. Once lane C's ledger lands, the tests that use it can
take the real in-memory `Ledger` instead. The fixtures in data/applications.yaml are read as the real ledger reads
them; no raw number is ever written here, which the leak test checks.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

DATA = Path(__file__).resolve().parent.parent / "data"
CENTRAL = ZoneInfo("America/Chicago")
IN_FLIGHT = ("claimed", "placed", "in-progress")


def fictional(n: int) -> str:
    """A fictional 555-01xx US number, made at run time so no file holds one (DR-025 section 6)."""
    assert 100 <= n <= 199
    return f"+1312555{n:04d}"


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class FakeApplicant:
    code: str
    first_name: str
    role: str
    zone: str
    received_at: str
    consent: dict[str, Any]
    number_hmac: str | None

    @property
    def consented(self) -> bool:
        return bool(self.consent.get("accepted"))


class FakeLedger:
    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self.now = now or (lambda: datetime.now(UTC))
        doc = yaml.safe_load((DATA / "applications.yaml").read_text(encoding="utf-8"))
        self.fixtures: dict[str, FakeApplicant] = {}
        self.fixture_pins: dict[str, str] = {}
        for row in doc["applications"]:
            code = str(row["code"])
            self.fixture_pins[code] = str(row["pin"]).zfill(4)
            self.fixtures[code] = FakeApplicant(
                code=code,
                first_name=str(row["first_name"]),
                role=str(row["role"]),
                zone=str(row["zone"]),
                received_at=str(row["applied_at"]),
                consent=dict(row["consent"]),
                number_hmac=None,
            )
        self.applications: dict[str, dict[str, Any]] = {}
        self.dial_rows: list[dict[str, Any]] = []
        self.opt_outs: list[dict[str, Any]] = []
        self.screens: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, int] = {}
        self.callbacks: list[dict[str, Any]] = []
        self.purged_before: list[datetime] = []
        self.forgotten: list[str] = []

    # Applicants.

    def applicant(self, code: object) -> FakeApplicant | None:
        code = str(code)
        if code in self.applications:
            row = self.applications[code]
            return FakeApplicant(
                code=code,
                first_name=row["first_name"],
                role=row["role"],
                zone=row["zone"],
                received_at=row["received_at"],
                consent=dict(row["consent"]),
                number_hmac=row["number_hmac"],
            )
        return self.fixtures.get(code)

    def add_application(
        self,
        *,
        first_name: str,
        role: str,
        zone: str,
        pin: str,
        consent: dict[str, Any],
        number_hmac: str,
        number_masked: str,
        nonce: str,
        not_dialled: str | None = None,
        received_at: datetime | None = None,
    ) -> FakeApplicant:
        taken = set(self.applications) | set(self.fixtures)
        code = next(
            c for c in (f"ACME-{secrets.randbelow(9000) + 1000}" for _ in range(100)) if c not in taken
        )
        self.applications[code] = {
            "code": code,
            "first_name": first_name,
            "role": role,
            "zone": zone,
            # As the real ledger keeps it: an HMAC, never the digits.
            "pin_hmac": hmac.new(b"fake-pin-key", f"{code}:{pin}".encode(), hashlib.sha256).hexdigest(),
            "number_hmac": number_hmac,
            "number_masked": number_masked,
            "consent": dict(consent),
            "received_at": stamp(received_at or self.now()),
            "nonce": nonce,
            "not_dialled": not_dialled,
        }
        return self.applicant(code)  # type: ignore[return-value]

    def set_not_dialled(self, code: str, reason: str) -> None:
        if code in self.applications:
            self.applications[code]["not_dialled"] = reason

    def nonce_seen(self, nonce: str, since: datetime) -> bool:
        return any(
            a["nonce"] == nonce and datetime.fromisoformat(a["received_at"]) >= since
            for a in self.applications.values()
        )

    def screen(self, code: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.screens.get(code))

    def set_screen(self, code: str, result: str, call_id: str, promised_by: str | None) -> None:
        self.screens[code] = {
            "result": result,
            "at": stamp(self.now()),
            "call_id": call_id,
            "promised_by": promised_by,
        }

    # Opt-outs.

    def opt_out(self, code: str, how: str, call_id: str | None = None, number_hmac: str | None = None) -> int:
        applicant = self.applicant(code)
        hashed = number_hmac or (applicant.number_hmac if applicant else None)
        self.opt_outs.append(
            {"code": code, "number_hmac": hashed, "at": stamp(self.now()), "call_id": call_id, "how": how}
        )
        cancelled = 0
        for d in self.dial_rows:
            if d["code"] == code and d["status"] == "due":
                d.update(status="cancelled", outcome="opted_out")
                cancelled += 1
        return cancelled

    def opted_out(self, code: str | None = None, number_hmac: str | None = None) -> bool:
        if code is not None and number_hmac is None:
            applicant = self.applicant(code)
            number_hmac = applicant.number_hmac if applicant else None
        return any(
            (code is not None and o["code"] == code)
            or (number_hmac is not None and o["number_hmac"] == number_hmac)
            for o in self.opt_outs
        )

    # Dials.

    def schedule_dial(self, code: str, attempt: int, due_at: datetime) -> dict[str, Any]:
        row = {
            "dial_id": f"D-{secrets.token_hex(6)}",
            "code": code,
            "attempt": attempt,
            "due_at": stamp(due_at),
            "status": "due",
            "claimed_at": None,
            "placed_at": None,
            "call_sid": None,
            "twilio_status": None,
            "answered_at": None,
            "answered_by": None,
            "voicemail_left": False,
            "ended_at": None,
            "outcome": None,
        }
        self.dial_rows.append(row)
        return copy.deepcopy(row)

    def claim_due_dial(
        self, now: datetime, max_per_day: int, ready: Callable[[dict[str, Any], FakeApplicant], bool]
    ) -> dict[str, Any] | None:
        if any(d["status"] in IN_FLIGHT for d in self.dial_rows) or self.dials_placed_today() >= max_per_day:
            return None
        for d in sorted(self.dial_rows, key=lambda d: d["due_at"]):
            if d["status"] != "due" or datetime.fromisoformat(d["due_at"]) > now:
                continue
            applicant = self.applicant(d["code"])
            record = self.applications.get(d["code"], {})
            if applicant is None or not applicant.consented or record.get("not_dialled"):
                continue
            if self.opted_out(code=d["code"]) or not ready(copy.deepcopy(d), applicant):
                continue
            d.update(status="claimed", claimed_at=stamp(now))
            return copy.deepcopy(d)
        return None

    def _find(self, key: str) -> dict[str, Any] | None:
        return next((d for d in self.dial_rows if key in (d["dial_id"], d["call_sid"])), None)

    def bind_call(self, dial_id: str, call_sid: str) -> dict[str, Any] | None:
        row = self._find(dial_id)
        if row is None or (row["call_sid"] not in (None, call_sid)):
            return None
        row["call_sid"] = call_sid
        return copy.deepcopy(row)

    def update_dial(self, key: str, **fields: Any) -> dict[str, Any] | None:
        row = self._find(key)
        if row is None:
            return None
        row.update(fields)
        return copy.deepcopy(row)

    def dial(self, key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._find(key))

    def dials(self, code: str | None = None) -> list[dict[str, Any]]:
        return [copy.deepcopy(d) for d in self.dial_rows if code is None or d["code"] == code]

    def dials_placed_today(self) -> int:
        today = self.now().astimezone(CENTRAL).date()
        return sum(
            1
            for d in self.dial_rows
            if d["placed_at"] and datetime.fromisoformat(d["placed_at"]).astimezone(CENTRAL).date() == today
        )

    def purge_answers(self, before: datetime) -> int:
        self.purged_before.append(before)
        gone = [c for c, a in self.applications.items() if datetime.fromisoformat(a["received_at"]) < before]
        for code in gone:
            self.forget(code)
        return len(gone)

    def forget(self, code: str) -> None:
        self.forgotten.append(code)
        self.applications.pop(code, None)
        self.dial_rows = [d for d in self.dial_rows if d["code"] != code]
        self.screens.pop(code, None)

    # What the inbound tools ask of a ledger, for a scripted call that posts a callback hand-off.

    def candidate(self, code: object) -> None:
        return None  # no candidate from data/candidates.yaml is ever on an outbound call

    def request_callback(
        self, code: str | None, best_time: str | None, reason: str | None, call_id: str | None = None
    ) -> dict[str, Any]:
        record = {"code": code, "best_time": best_time, "reason": reason, "call_id": call_id}
        self.callbacks.append(record)
        return dict(record)

    # The inbound line's daily count, which the outbound /voice must never touch.

    def today(self) -> str:
        return self.now().astimezone(CENTRAL).date().isoformat()

    def count_call(self, day: str) -> int:
        self.calls[day] = self.calls.get(day, 0) + 1
        return self.calls[day]

    def calls_today(self) -> int:
        return self.calls.get(self.today(), 0)

    def everything(self) -> str:
        """Every record the fake holds, as text, for the leak test."""
        return repr((self.applications, self.dial_rows, self.opt_outs, self.screens, self.callbacks))
