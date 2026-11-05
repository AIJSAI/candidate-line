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
import time
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
from candidate_line.tools.ledger import Ledger
from candidate_line.traces.store import DEFAULT_PATH, TraceStore

log = logging.getLogger("candidate_line.app")

HELLO_LINE = (
    "Thanks for calling the ACME candidate line. This is Gus. "
    "The line is still being built. Please call back in a day or two."
)
# Said by Twilio, not by Gus, once the day's calls pass Settings.max_calls_per_day (DR-021): no stream is opened,
# so a call past the cap costs no transcriber, voice or model time.
CLOSED_LINE = "This is the ACME candidate line. The line is closed for the moment. Please try again later."
CLOSED_OUTCOME = "closed: daily cap"
# Twilio opens the stream a second or two after it reads the TwiML; a token older than this is refused.
STREAM_TOKEN_TTL_S = 60


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


def twiml_closed() -> str:
    return twiml_say(CLOSED_LINE)


def _stream_mac(auth_token: str, call_sid: str, expires: int) -> str:
    message = f"stream|{call_sid}|{expires}".encode()
    return hmac.new(auth_token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def stream_token(auth_token: str, call_sid: str, now: float | None = None) -> str:
    """The token that opens one call's media stream: its expiry and an HMAC over the call and the expiry, keyed by
    the auth token. /voice mints it after the signature check and the daily count. It is keyed and not kept in a
    table so the probe, which holds the same auth token, can mint its own for `make probe` (DR-011), and a second
    process or task can check one the first minted."""
    expires = int((time.time() if now is None else now) + STREAM_TOKEN_TTL_S)
    return f"{expires}.{_stream_mac(auth_token, call_sid, expires)}"


def stream_token_ok(auth_token: str, call_sid: str, token: str, now: float | None = None) -> bool:
    """True when the token was minted with this auth token for this call and has not expired."""
    expires_text, _, mac = token.partition(".")
    if not expires_text.isdigit() or not mac:
        return False
    if int(expires_text) < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(_stream_mac(auth_token, call_sid, int(expires_text)), mac)


def twiml_stream(public_base_url: str, token: str | None = None) -> str:
    """`<Connect><Stream>`: the bidirectional stream (DR-005). The greeting comes through the stream so barge-in applies.
    The token rides as a custom parameter, because Twilio takes no query string on a stream URL."""
    wss = public_base_url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    url = f"{escape(wss)}/media"
    stream = f'<Stream url="{url}" />'
    if token:
        stream = f'<Stream url="{url}"><Parameter name="token" value="{escape(token)}" /></Stream>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect>{stream}</Connect></Response>'


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
    # Built over the store: SNS when SNS_TOPIC_ARN is set, Slack when SLACK_WEBHOOK_URL is, the log otherwise.
    escalations: EscalationQueue | None = None
    # The tools' ledger for each call. Ledger.default is one shared ledger over var/state.json per process, so two
    # calls never book one slot; None leaves it to the first tool of the call (the tests).
    ledger: Callable[[], Ledger] | None = None
    # Open the speech clients once at startup, before the first caller: on a fresh task the first call paid about
    # twenty seconds of silence before the greeting for their first connections (the operator's call of
    # 2026-11-04, 20:14 CT, DR-023). The tests pass fakes and leave this off.
    warm_up: bool = False


def default_deps(settings: Settings) -> Deps:
    return Deps(
        transcriber=lambda: TranscribeStreamingTranscriber(settings.aws_region),
        speaker=lambda: PollySpeaker(settings.aws_region, voice_id=settings.polly_voice),
        brain=lambda: make_brain(settings),
        hooks=default_hooks,
        system=settings.system_prompt(),
        store=(store := TraceStore(settings.trace_store_path or DEFAULT_PATH)),
        escalations=default_queue(store, settings.slack_webhook_url, settings.sns_topic_arn),
        ledger=Ledger.default,
        warm_up=settings.brain_provider != "echo",
    )


def public_url(request: Request, settings: Settings) -> str:
    """The URL Twilio signed. Behind the tunnel the app sees 127.0.0.1, so the public base comes from settings."""
    if settings.public_base_url:
        query = f"?{request.url.query}" if request.url.query else ""
        return settings.public_base_url.rstrip("/") + request.url.path + query
    return str(request.url)


async def _warm_up(deps: Deps) -> None:
    """One short synthesis and one opened and closed transcription stream, so their connections exist before
    /health answers and the load balancer sends the first call. A failure here is logged and never stops the
    line: a cold first call is slower, not broken."""
    started = time.perf_counter()
    try:
        await asyncio.to_thread(deps.speaker().say, "Warming up.")
        polly_ms = int((time.perf_counter() - started) * 1000)
        transcriber = deps.transcriber()
        await asyncio.wait_for(transcriber.start(), timeout=20)
        await asyncio.wait_for(transcriber.stop(), timeout=10)
        log.info(
            "warm-up: polly %d ms, transcribe %d ms",
            polly_ms,
            int((time.perf_counter() - started) * 1000) - polly_ms,
        )
    except Exception:
        log.warning("warm-up failed; the first call pays the cold start", exc_info=True)


def create_app(settings: Settings, deps: Deps | None = None) -> FastAPI:
    deps = deps or default_deps(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if deps.warm_up:
            await _warm_up(deps)
        yield
        # A hand-off still queued when the process stops would die with the daemon worker (DR-013). Text mode
        # and the eval runner drain before they exit; the phone, which `make restart` stops mid-day, does too.
        if deps.escalations is not None:
            await asyncio.to_thread(deps.escalations.drain, 5.0)

    app = FastAPI(title="Candidate Line", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # The daily cap counts on one ledger for the life of the process. A file-backed Ledger.default is shared
    # anyway; an in-memory one is new on every call, and counting on a fresh one would never pass the cap.
    counter: list[Ledger] = []
    # /media is a public WebSocket, and Twilio does not sign its handshake (the Stream TwiML and WebSocket messages
    # pages, read 2026-11-04). With the auth token set (every real deployment) a stream opens only with the token
    # /voice minted for that call, so a client that learns the wss URL cannot step around the signature check or the
    # daily count and spend on Transcribe, Polly and the model. Each token opens one stream in this process.
    used_tokens: dict[str, float] = {}

    def stream_allowed(meta: Mapping[str, Any]) -> bool:
        if not settings.twilio_auth_token:
            # As /voice does: no auth token means local curl only, and only when unsigned requests are allowed.
            return settings.allow_unsigned_webhooks
        params = meta.get("customParameters")
        given = str(params.get("token") or "") if isinstance(params, Mapping) else ""
        now = time.time()
        for stale in [t for t, expires in used_tokens.items() if expires < now]:
            del used_tokens[stale]
        call_sid = str(meta.get("callSid") or "")
        if given in used_tokens or not stream_token_ok(settings.twilio_auth_token, call_sid, given, now):
            return False
        used_tokens[given] = float(given.partition(".")[0])
        return True

    def count_this_call() -> int | None:
        """The day's count with this call in it, or None when it could not be counted. The call then goes
        through: the cap bounds the bill, and a fault in the state file must not close the line to a candidate."""
        if deps.ledger is None:
            return None
        try:
            if not counter:
                counter.append(deps.ledger())
            ledger = counter[0]
            return ledger.count_call(ledger.today())
        except Exception:
            log.exception("the daily call count failed; the call goes through uncounted")
            return None

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
        call_sid = form.get("CallSid")
        if deps.store is not None and call_sid:
            deps.store.start_call(
                call_sid, "voice", caller=form.get("From"), provider=settings.brain_provider
            )
        # In a thread, because the count takes the state file's lock and the live calls' audio shares this loop.
        count = await asyncio.to_thread(count_this_call)
        if count is not None and count > settings.max_calls_per_day:
            log.warning(
                "daily cap: call %d today is past the cap of %d; answered closed",
                count,
                settings.max_calls_per_day,
            )
            if deps.store is not None and call_sid:
                deps.store.end_call(call_sid, CLOSED_OUTCOME)
            return Response(content=twiml_closed(), media_type="text/xml")
        token = (
            stream_token(settings.twilio_auth_token, call_sid or "") if settings.twilio_auth_token else None
        )
        return Response(content=twiml_stream(settings.public_base_url, token), media_type="text/xml")

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
        meta = start.get("start")
        meta = meta if isinstance(meta, Mapping) else {}
        if not stream_allowed(meta):
            # Refused before any ears, mouth or brain is built, so a refused stream costs nothing.
            log.warning("media stream refused: no live stream token for this call")
            await ws.close(code=1008)
            return
        stream_sid = str(start["streamSid"])
        call_id = str(meta.get("callSid") or stream_sid)

        async def incoming() -> AsyncIterator[dict[str, Any]]:
            while True:
                try:
                    message = await ws.receive_json()
                except WebSocketDisconnect:
                    return
                yield message
                if message.get("event") == "stop":
                    return

        ledger: Ledger | None = None
        if deps.ledger is not None:
            try:
                ledger = deps.ledger()
            except Exception:
                # The call goes on: the first tool tries the ledger again and turns a failure into a sentence.
                log.exception("ledger failed to open for %s", call_id)
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
            ledger=ledger,
            max_call_seconds=settings.max_call_seconds,
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


def __getattr__(name: str) -> Any:
    # `uvicorn candidate_line.telephony.app:app` asks for `app` once. Building it here and not at import keeps a
    # test or a tool that merely imports this module from opening the room's store (card 03's dry run, 2026-11-03).
    if name == "app":
        return create_app(Settings.from_env())
    raise AttributeError(name)
