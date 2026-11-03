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

# A final transcript is not the end of a thought. A caller who pauses mid-sentence gets a final at the pause, and
# answering it answers half a question (seen on both arms on the first dialled calls, 2026-11-02). So after a final
# the session waits a short grace for more speech: a partial inside it means the caller went on, and the finals are
# joined into one turn. The wait is short after a question mark, where the caller has handed over the turn, and
# longer after a full stop or no mark at all. The grace cannot be long enough on its own: on the dialled calls of
# 2026-11-02 the next sentence's first partial reached the line 1,234 ms after the previous final, and a grace that
# long on every statement is a slow Gus. So the grace is short, and a turn whose reply is still being made when the
# caller goes on is superseded: its reply is dropped, its words are carried into the next turn, and the caller never
# hears the half-answer. The cost is the grace on every turn plus one wasted model call when it happens; DR-006.
GRACE_AFTER_QUESTION_MS = 300
GRACE_OTHERWISE_MS = 600
GRACE_BACKSTOP_MS = 2000  # a partial that never becomes a final still releases the pending finals
_HANDOVER_MARKS = ("?", "!")


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
        grace_ms: tuple[int, int] = (GRACE_AFTER_QUESTION_MS, GRACE_OTHERWISE_MS),
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
        self._grace_ms = grace_ms
        self._pending: list[str] = []  # finals waiting out the grace, joined into one turn when it ends
        self._grace: asyncio.Task | None = None
        self._thinking = False  # a turn's reply is being made and nothing has been spoken yet
        self._superseded = (
            False  # the caller went on talking during that; the reply is dropped when it arrives
        )
        self._carry = ""  # the superseded turn's words, prepended to the next turn's
        self.superseded = 0
        self._stopped = (
            False  # set when Twilio's stop arrives; a turn finishing after it is dropped, not an error
        )

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
            self._stopped = True
            self._cancel_grace()  # the caller has gone; a turn still waiting out its grace is not spoken
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
                    log.debug("partial %s %r", self.ctx.call_id, heard.text[-60:])
                    if heard.text.strip():
                        if self.speaking:
                            await self.barge_in()
                        elif self._thinking:
                            self._superseded = True
                        # The caller went on talking: the pending finals wait for the next final, with a backstop.
                        self._arm_grace(None)
                    continue
                log.info("final %s %r", self.ctx.call_id, heard.text)
                if not self._pending:
                    # The turn's clock starts at the first final, grace included.
                    self._turn_started = time.perf_counter()
                self._pending.append(heard.text)
                self._arm_grace(heard.text)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("listening failed for %s", self.ctx.call_id)
            raise

    def _arm_grace(self, last_final: str | None) -> None:
        self._cancel_grace()
        if last_final is None:
            ms = GRACE_BACKSTOP_MS
        else:
            ms = self._grace_ms[0] if last_final.rstrip().endswith(_HANDOVER_MARKS) else self._grace_ms[1]
        self._grace = asyncio.create_task(self._end_of_turn(ms))

    def _cancel_grace(self) -> None:
        if self._grace is not None and not self._grace.done():
            self._grace.cancel()
        self._grace = None

    async def _end_of_turn(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)
        self._grace = None  # from here the task is a turn, and a later cancel must not reach the brain call
        text = " ".join(self._pending).strip()
        self._pending.clear()
        if not text:
            return
        try:
            await self.handle_utterance(text)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._stopped:
                # The caller hung up while the turn was being made (a goodbye, mostly); the socket is closed.
                log.info("turn dropped after the stop for %s (%s)", self.ctx.call_id, type(error).__name__)
            else:
                log.exception("turn failed for %s", self.ctx.call_id)

    async def handle_utterance(self, text: str) -> None:
        async with self._utterance_lock:
            if self._carry:
                text = f"{self._carry} {text}"
                self._carry = ""
            if self._turn_started is None:
                self._turn_started = time.perf_counter()
            self._thinking, self._superseded = True, False
            try:
                result = await asyncio.to_thread(run_turn, self._brain, self._hooks, self.ctx, text)
            finally:
                self._thinking = False
            if self._superseded:
                # The caller kept talking while this reply was being made: the reply is never spoken, the turn's
                # two messages come off the history, and its words lead the next turn, so one whole question is
                # answered once. The turn's clock keeps running from the first final.
                del self.ctx.history[-2:]
                self._carry = text
                self.superseded += 1
                log.info("turn superseded %s heard=%r (the caller kept talking)", self.ctx.call_id, text)
                return
            self.turns += 1
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
