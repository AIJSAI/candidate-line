"""Twilio's edge: the voice webhook now, the media-stream WebSocket from item 3 on.

Why a factory: the tests build an app around their own Settings; uvicorn imports `app`, built from the
environment. Why the signature check: the webhook is a public URL behind a tunnel, so every request proves it
came from Twilio or it is refused (Twilio's security page, read 2026-11-01). It fails closed: with no auth token
in the environment the webhook answers 503 unless ALLOW_UNSIGNED_WEBHOOKS=1, which is for local curl only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request, Response

from candidate_line.settings import Settings

HELLO_LINE = (
    "Thanks for calling the ACME candidate line. This is Gus. "
    "The line is still being built. Please call back in a day or two."
)


def twilio_signature(auth_token: str, url: str, form: Mapping[str, str]) -> str:
    """Twilio's scheme: HMAC-SHA1 over the public URL followed by each POST field, name then value, sorted by name."""
    payload = url + "".join(f"{key}{form[key]}" for key in sorted(form))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def twiml_say(text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say voice="Polly.Matthew-Neural">{escape(text)}</Say></Response>'
    )


def public_url(request: Request, settings: Settings) -> str:
    """The URL Twilio signed. Behind the tunnel the app sees 127.0.0.1, so the public base comes from settings."""
    if settings.public_base_url:
        query = f"?{request.url.query}" if request.url.query else ""
        return settings.public_base_url.rstrip("/") + request.url.path + query
    return str(request.url)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Candidate Line", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "brain": settings.brain_provider}

    @app.post("/voice")
    async def voice(request: Request) -> Response:
        form = {key: str(value) for key, value in (await request.form()).items()}
        if settings.twilio_auth_token:
            expected = twilio_signature(settings.twilio_auth_token, public_url(request, settings), form)
            given = request.headers.get("X-Twilio-Signature", "")
            if not hmac.compare_digest(expected, given):
                raise HTTPException(status_code=403, detail="bad Twilio signature")
        elif not settings.allow_unsigned_webhooks:
            raise HTTPException(status_code=503, detail="TWILIO_AUTH_TOKEN is not set")
        return Response(content=twiml_say(HELLO_LINE), media_type="text/xml")

    return app


app = create_app(Settings.from_env())
