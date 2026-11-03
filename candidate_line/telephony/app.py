"""Twilio's edge: the voice webhook now, the media-stream WebSocket from item 3 on.

Why a factory: the tests build an app around their own Settings; uvicorn imports `app`, built from the
environment. Why the signature check: the webhook is a public URL behind a tunnel, so every request proves it
came from Twilio or it is refused (Twilio's security page, read 2026-11-01). It fails closed: with no auth token
in the environment the webhook answers 503 unless ALLOW_UNSIGNED_WEBHOOKS=1, which is for local curl only.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from candidate_line.brain import Brain, make_brain
from candidate_line.escalation import EscalationQueue, default_queue
from candidate_line.hooks import Hooks, default_hooks
from candidate_line.persona import GREETING, PLACEHOLDER_SYSTEM
from candidate_line.settings import Settings
from candidate_line.telephony.media import MediaSession
from candidate_line.telephony.speech import PollySpeaker, Speaker, Transcriber, TranscribeStreamingTranscriber
from candidate_line.traces.store import DEFAULT_PATH, TraceStore

log = logging.getLogger("candidate_line.app")

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


def twiml_stream(public_base_url: str) -> str:
    """`<Connect><Stream>`: the bidirectional stream (DR-005). The greeting comes through the stream so barge-in applies."""
    wss = public_base_url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Connect><Stream url="{escape(wss)}/media" /></Connect></Response>'
    )


@dataclass(frozen=True)
class Deps:
    """Ears, mouth and brain for a call. The tests pass fakes; `default_deps` builds the real ones from settings."""

    transcriber: Callable[[], Transcriber]
    speaker: Callable[[], Speaker]
    brain: Callable[[], Brain]
    hooks: Callable[[], Hooks]
    # The same prompt text mode runs; the echo brain ignores it, a real brain follows it (two real calls echoed the
    # caller on 2026-11-02 because this defaulted to the echo line while the brain was Haiku 5.5).
    system: str = PLACEHOLDER_SYSTEM
    greeting: str | None = GREETING
    # The room's trace store, one per process; None in tests that do not trace. The call row starts at /voice
    # (the number is masked by the store) and ends when the stream stops.
    store: TraceStore | None = None
    escalations: EscalationQueue | None = None  # built over the store; Slack when SLACK_WEBHOOK_URL is set


def default_deps(settings: Settings) -> Deps:
    return Deps(
        transcriber=lambda: TranscribeStreamingTranscriber(settings.aws_region),
        speaker=lambda: PollySpeaker(settings.aws_region, voice_id=settings.polly_voice),
        brain=lambda: make_brain(settings),
        hooks=default_hooks,
        system=settings.system_prompt(),
        store=(store := TraceStore(settings.trace_store_path or DEFAULT_PATH)),
        escalations=default_queue(store, settings.slack_webhook_url),
    )


def public_url(request: Request, settings: Settings) -> str:
    """The URL Twilio signed. Behind the tunnel the app sees 127.0.0.1, so the public base comes from settings."""
    if settings.public_base_url:
        query = f"?{request.url.query}" if request.url.query else ""
        return settings.public_base_url.rstrip("/") + request.url.path + query
    return str(request.url)


def create_app(settings: Settings, deps: Deps | None = None) -> FastAPI:
    deps = deps or default_deps(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # A hand-off still queued when the process stops would die with the daemon worker (DR-013). Text mode
        # and the eval runner drain before they exit; the phone, which `make restart` stops mid-day, does too.
        if deps.escalations is not None:
            await asyncio.to_thread(deps.escalations.drain, 5.0)

    app = FastAPI(title="Candidate Line", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # uvicorn configures only its own loggers; without a root handler the line's per-turn INFO lines vanish.
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:     %(name)s %(message)s")
    logging.getLogger("candidate_line").setLevel(settings.log_level)

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
        if settings.voice_mode == "say":
            return Response(content=twiml_say(HELLO_LINE), media_type="text/xml")
        if not settings.public_base_url:
            raise HTTPException(
                status_code=503, detail="PUBLIC_BASE_URL is not set; the stream needs a public wss host"
            )
        if deps.store is not None and form.get("CallSid"):
            deps.store.start_call(
                form["CallSid"], "voice", caller=form.get("From"), provider=settings.brain_provider
            )
        return Response(content=twiml_stream(settings.public_base_url), media_type="text/xml")

    @app.websocket("/media")
    async def media(ws: WebSocket) -> None:
        await ws.accept()
        start: dict[str, Any] | None = None
        try:
            while start is None:
                message = await ws.receive_json()
                if message.get("event") == "start":
                    start = message
                elif message.get("event") == "stop":
                    return
        except WebSocketDisconnect:
            return
        stream_sid = str(start["streamSid"])
        call_id = str(start.get("start", {}).get("callSid") or stream_sid)

        async def incoming() -> AsyncIterator[dict[str, Any]]:
            while True:
                try:
                    message = await ws.receive_json()
                except WebSocketDisconnect:
                    return
                yield message
                if message.get("event") == "stop":
                    return

        session = MediaSession(
            send=ws.send_json,
            transcriber=deps.transcriber(),
            speaker=deps.speaker(),
            brain=deps.brain(),
            hooks=deps.hooks(),
            system=deps.system,
            call_id=call_id,
            stream_sid=stream_sid,
            greeting=deps.greeting,
            store=deps.store,
            escalations=deps.escalations,
        )
        try:
            await session.run(incoming())
        except WebSocketDisconnect:
            return
        except Exception:
            log.exception("media session failed for %s", call_id)
            raise
        try:
            await ws.close()  # a close frame after `stop`, so the other side sees an orderly end, not a reset
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app


app = create_app(Settings.from_env())
