"""Arm A's media session: Twilio frames in, Transcribe, one turn, Polly by sentence, Twilio frames out, barge-in.

Why one class with injected ears, mouth and brain: the whole loop is tested with fakes and no network, and the
same loop runs the real pair under `make dev`. Why barge-in is a `clear`: Twilio buffers what we send and plays
it; emptying that buffer is the only way to stop Gus mid-sentence (the WebSocket messages page, DR-005). What
counts as barge-in today: a partial transcript with words while Gus is speaking. Tracing spans are not written
here yet; they are added live, before the first tool (PREBUILT.md).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from candidate_line.brain import Brain
from candidate_line.hooks import Hooks
from candidate_line.telephony.audio import (
    decode_twilio_payload,
    encode_twilio_payload,
    frames,
    mulaw_to_pcm16,
    split_sentences,
)
from candidate_line.telephony.speech import Speaker, Transcriber
from candidate_line.turn import TurnContext, run_turn

log = logging.getLogger("candidate_line.media")
Send = Callable[[dict[str, Any]], Awaitable[None]]
OUT_CHUNK_BYTES = 4000  # half a second of mu-law per WebSocket message


async def _settle(task: asyncio.Future, timeout: float, what: str) -> None:
    """Awaits a task with a bound and never awaits it past that: a shield keeps the timeout from cancelling into
    the CRT transport, which can hang a cancel after the far side has gone (2026-11-02)."""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        task.cancel()
        log.warning("%s did not finish in %.0f s; left cancelled", what, timeout)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s failed", what)


class MediaSession:
    def __init__(
        self,
        send: Send,
        transcriber: Transcriber,
        speaker: Speaker,
        brain: Brain,
        hooks: Hooks,
        system: str,
        call_id: str,
        stream_sid: str,
        greeting: str | None = None,
    ) -> None:
        self._send = send
        self._transcriber = transcriber
        self._speaker = speaker
        self._brain = brain
        self._hooks = hooks
        self._greeting = greeting
        self.stream_sid = stream_sid
        self.ctx = TurnContext(call_id=call_id, channel="voice", system=system)
        self.speaking = False
        self.barge_ins = 0
        self.turns = 0
        self._interrupted = asyncio.Event()
        self._pending_marks: set[str] = set()
        self._speak_lock = asyncio.Lock()
        self._utterance_lock = asyncio.Lock()
        self._mark_seq = 0
        # Set when a final transcript arrives; cleared when the first reply byte goes out, for the turn-gap log line.
        self._turn_started: float | None = None

    async def run(self, incoming: AsyncIterator[dict[str, Any]]) -> None:
        await self._transcriber.start()
        listener = asyncio.create_task(self._listen())
        greeter = asyncio.create_task(self.speak(self._greeting)) if self._greeting else None
        try:
            async for message in incoming:
                event = message.get("event")
                if event == "media":
                    await self._transcriber.feed(
                        mulaw_to_pcm16(decode_twilio_payload(message["media"]["payload"]))
                    )
                elif event == "mark":
                    self._on_mark(message["mark"]["name"])
                elif event == "stop":
                    break
        finally:
            # Close our side of the Transcribe stream first and let the listener drain; cancelling it mid-read
            # trips the CRT transport (an InvalidStateError on a cancelled body future, seen 2026-11-01).
            # Same rule as the probe: the CRT transport can hang a close or a cancel after Twilio has gone, so wait
            # with a bound, cancel what is left, and never await a task that may be stuck (2026-11-02).
            await _settle(
                asyncio.ensure_future(self._transcriber.stop()), 5.0, f"transcriber stop {self.ctx.call_id}"
            )
            for task, what in ((listener, "listener"), (greeter, "greeter")):
                if task is not None:
                    await _settle(task, 3.0, f"{what} {self.ctx.call_id}")

    async def _listen(self) -> None:
        try:
            async for heard in self._transcriber.events():
                if heard.is_partial:
                    if self.speaking and heard.text.strip():
                        await self.barge_in()
                    continue
                await self.handle_utterance(heard.text)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("listening failed for %s", self.ctx.call_id)
            raise

    async def handle_utterance(self, text: str) -> None:
        async with self._utterance_lock:
            self.turns += 1
            self._turn_started = time.perf_counter()
            result = await asyncio.to_thread(run_turn, self._brain, self._hooks, self.ctx, text)
            reply = getattr(result, "reply", None)
            log.info(
                "turn %d %s heard=%r reply=%r brain_ms=%s",
                self.turns,
                self.ctx.call_id,
                text,
                result.spoken,
                getattr(reply, "latency_ms", None),
            )
            if result.spoken:
                await self.speak(result.spoken)

    async def speak(self, text: str) -> None:
        async with self._speak_lock:
            self._interrupted.clear()
            self.speaking = True
            for sentence in split_sentences(text):
                if self._interrupted.is_set():
                    break
                mulaw = await asyncio.to_thread(self._speaker.say, sentence)
                if self._interrupted.is_set():
                    break
                for chunk in frames(mulaw, OUT_CHUNK_BYTES):
                    if self._turn_started is not None:
                        gap_ms = int((time.perf_counter() - self._turn_started) * 1000)
                        log.info("turn %d %s first_audio_gap_ms=%d", self.turns, self.ctx.call_id, gap_ms)
                        self._turn_started = None
                    await self._send(
                        {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {"payload": encode_twilio_payload(chunk)},
                        }
                    )
                self._mark_seq += 1
                name = f"m{self._mark_seq}"
                self._pending_marks.add(name)
                await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})
            # Twilio is still playing what we sent; `speaking` clears when the last mark comes back.
            if not self._pending_marks:
                self.speaking = False

    def _on_mark(self, name: str) -> None:
        self._pending_marks.discard(name)
        if not self._pending_marks:
            self.speaking = False

    async def barge_in(self) -> None:
        self.barge_ins += 1
        log.info("barge-in %d %s", self.barge_ins, self.ctx.call_id)
        self._interrupted.set()
        self._pending_marks.clear()
        self.speaking = False
        await self._send({"event": "clear", "streamSid": self.stream_sid})
