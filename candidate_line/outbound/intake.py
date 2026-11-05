"""`POST /applications`: the careers form's signed application, the only way a number reaches the line (spec 9.1).

Why signed this way: the endpoint is public and every accepted application can ring a phone, so a request proves
it came from the holder of INTAKE_SIGNING_KEY with an HMAC-SHA256 over its timestamp, a fresh nonce and its raw
body, compared in constant time (DR-025 section 10). The timestamp bounds a captured request to 300 s; the nonce,
remembered for ten minutes, which is twice that, means it cannot be replayed even inside them, and the stored
applications carry their nonces so a restart forgets none that led to one. Why every refusal comes before any
store: a refused request leaves no trace but a log line. Why the answer is only the code and a status: the number
and the PIN are the applicant's, and the careers form already has them.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, StringConstraints, ValidationError

from candidate_line.outbound import Ledger, number_hmac, number_key
from candidate_line.outbound.contacts import Contacts
from candidate_line.outbound.window import first_dial_at
from candidate_line.settings import Settings
from candidate_line.tools.ledger import APPLICATIONS_PATH, US_ZONES
from candidate_line.tools.roles import ROLES_PATH, load_roles
from candidate_line.traces.store import mask_number

log = logging.getLogger("candidate_line.intake")


TIMESTAMP_HEADER = "X-Intake-Timestamp"
NONCE_HEADER = "X-Intake-Nonce"
SIGNATURE_HEADER = "X-Intake-Signature"
MAX_BODY_BYTES = 4096
TIMESTAMP_SKEW_S = 300
# Twice the timestamp's window, so a request captured at the edge of one is still refused at the far edge.
NONCE_MEMORY_S = 2 * TIMESTAMP_SKEW_S
NONCE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
Status = Literal["scheduled", "no_consent", "opted_out", "not_allowed"]


def intake_signature(key: str, timestamp: str, nonce: str, body: bytes) -> str:
    """Hex HMAC-SHA256 under the signing key over `{timestamp}.{nonce}.{raw body}`."""
    message = f"{timestamp}.{nonce}.".encode() + body
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_headers(
    key: str, body: bytes, now: float | None = None, nonce: str | None = None
) -> dict[str, str]:
    """The three headers a sender puts on one request: the probe, `make apply` and the tests send this way. A new
    nonce of 192 random bits every time unless one is given."""
    timestamp = str(int(time.time() if now is None else now))
    nonce = nonce or secrets.token_urlsafe(24)
    return {
        TIMESTAMP_HEADER: timestamp,
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: intake_signature(key, timestamp, nonce, body),
        "Content-Type": "application/json",
    }


def _first_name(value: str) -> str:
    if not 1 <= len(value) <= 40 or not value[0].isalpha():
        raise ValueError("a first name is 1 to 40 characters and starts with a letter")
    if not all(ch.isalpha() or ch in " -'’" for ch in value):
        raise ValueError("a first name holds letters, spaces, hyphens and apostrophes only")
    return value


def _us_zone(value: str) -> str:
    # The ledger's closed set, so intake and add_application refuse the same zones (spec 9.1).
    if value not in US_ZONES:
        raise ValueError("the zone is a US IANA zone")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("the zone is not one this machine knows") from None
    return value


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: str
    accepted: bool
    at: AwareDatetime
    source: Literal["careers-form", "ats", "operator"]


class ApplicationIn(BaseModel):
    """The closed schema: any other key is refused (DR-025 section 10)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    first_name: Annotated[str, AfterValidator(_first_name)]
    role: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    phone: Annotated[str, StringConstraints(pattern=r"^\+1[2-9]\d{2}[2-9]\d{6}$")]
    zone: Annotated[str, AfterValidator(_us_zone)]
    pin: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
    consent: ConsentIn


def load_role_ids(path: Path = ROLES_PATH) -> frozenset[str]:
    """The role ids an application may name, read once at start through the roles loader, which refuses a roles
    file the gate must never read (DR-025 section 4)."""
    return frozenset(load_roles(path))


def load_consent_texts(path: Path = APPLICATIONS_PATH) -> dict[str, str]:
    """Each consent version the careers form has shown, word for word, so the record keeps a hash of the text."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    texts = doc.get("consent_texts") or {}
    return {str(k): str(v) for k, v in texts.items()} if isinstance(texts, dict) else {}


def _refuse(status: int, reason: str) -> JSONResponse:
    # The reason is one fixed phrase: nothing the sender sent is ever echoed back.
    return JSONResponse({"error": reason}, status_code=status)


@dataclass
class Intake:
    settings: Settings
    ledger: Callable[[], Ledger]
    contacts: Contacts
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    role_ids: frozenset[str] = field(default_factory=load_role_ids)
    consent_texts: Mapping[str, str] = field(default_factory=load_consent_texts)
    _nonces: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _nonce_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/applications", self.receive, methods=["POST"], status_code=202)
        return router

    async def receive(self, request: Request) -> Response:
        key = self.settings.intake_signing_key
        if not key:
            return _refuse(503, "intake is not configured")
        body = await _bounded_body(request)
        if body is None:
            return _refuse(413, "the application is over 4 KB")
        now = self.clock()
        timestamp = request.headers.get(TIMESTAMP_HEADER, "")
        nonce = request.headers.get(NONCE_HEADER, "")
        given = request.headers.get(SIGNATURE_HEADER, "")
        if not timestamp.isdigit() or abs(now.timestamp() - int(timestamp)) > TIMESTAMP_SKEW_S:
            return _refuse(401, "the timestamp is missing or too far from now")
        if not NONCE.match(nonce):
            return _refuse(401, "the nonce is missing or malformed")
        if not hmac.compare_digest(intake_signature(key, timestamp, nonce, body), given):
            return _refuse(401, "the signature does not match")
        # Only a signed request spends a nonce, so nobody can burn a sender's nonces without the key.
        if not self._first_sight(nonce, now.timestamp()) or await asyncio.to_thread(self._stored, nonce, now):
            log.warning("intake refused a replayed nonce")
            return _refuse(409, "this request was already received")
        try:
            application = ApplicationIn.model_validate_json(body)
        except ValidationError as error:
            # Field names and error kinds only: pydantic's own message quotes the input, the number and PIN in it.
            fields = sorted({".".join(str(p) for p in e["loc"]) or "body" for e in error.errors()})
            return JSONResponse({"error": "the application does not fit the schema", "fields": fields}, 422)
        if application.role not in self.role_ids:
            return JSONResponse({"error": "the application does not fit the schema", "fields": ["role"]}, 422)
        if application.consent.version not in self.consent_texts:
            return JSONResponse(
                {"error": "the application does not fit the schema", "fields": ["consent.version"]}, 422
            )
        code, status = await asyncio.to_thread(self._accept, application, nonce, now)
        return JSONResponse({"code": code, "status": status}, status_code=202)

    def _first_sight(self, nonce: str, now: float) -> bool:
        """True the first time a nonce is seen in this process's ten-minute memory; it is then remembered."""
        with self._nonce_lock:
            for stale in [n for n, at in self._nonces.items() if now - at > NONCE_MEMORY_S]:
                del self._nonces[stale]
            if nonce in self._nonces:
                return False
            self._nonces[nonce] = now
            return True

    def _stored(self, nonce: str, now: datetime) -> bool:
        return self.ledger().nonce_seen(nonce, now - timedelta(seconds=NONCE_MEMORY_S))

    def _accept(self, application: ApplicationIn, nonce: str, now: datetime) -> tuple[str, Status]:
        """Stores the application, and its number and first dial only when it may be dialled."""
        ledger = self.ledger()
        key = number_key(str(self.settings.intake_signing_key))
        hashed = number_hmac(key, application.phone)
        status: Status = "scheduled"
        if not application.consent.accepted:
            status = "no_consent"
        elif ledger.opted_out(number_hmac=hashed):
            status = "opted_out"
        elif application.phone not in self.settings.outbound_allowed_numbers:
            status = "not_allowed"
        consent: dict[str, Any] = {
            "version": application.consent.version,
            "text_sha256": hashlib.sha256(
                self.consent_texts[application.consent.version].encode("utf-8")
            ).hexdigest(),
            "accepted": application.consent.accepted,
            "at": application.consent.at.isoformat(),
            "source": application.consent.source,
        }
        stored = ledger.add_application(
            first_name=application.first_name,
            role=application.role,
            zone=application.zone,
            pin=application.pin,
            consent=consent,
            number_hmac=hashed,
            number_masked=str(mask_number(application.phone)),
            nonce=nonce,
            not_dialled=None if status == "scheduled" else status,
            received_at=now,
        )
        if status == "scheduled":
            # The number is kept only beside a dial, and goes again if the dial cannot be written.
            self.contacts.put(stored.code, application.phone, now)
            try:
                ledger.schedule_dial(
                    stored.code, 1, first_dial_at(now, application.zone, self.settings.call_window)
                )
            except Exception:
                self.contacts.delete(stored.code)
                raise
        log.info("application %s from %s: %s", stored.code, mask_number(application.phone), status)
        return stored.code, status


async def _bounded_body(request: Request) -> bytes | None:
    """The raw body, or None once it passes MAX_BODY_BYTES; read in chunks so an oversized one is never held."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
