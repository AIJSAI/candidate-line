"""Arm A's media session: Twilio frames in, Transcribe, one turn, Polly by sentence, Twilio frames out, barge-in.

Why one class with injected ears, mouth and brain: the whole loop is tested with fakes and no network, and the
same loop runs the real pair under `make dev`. Why barge-in is a `clear`: Twilio buffers what we send and plays
it; emptying that buffer is the only way to stop Gus mid-sentence (the WebSocket messages page, DR-005). What
counts as barge-in today: a partial transcript with words while Gus is speaking. Tracing spans are not written
here yet; they are added live, before the first tool (PREBUILT.md).
"""

from __future__ import annotations

import asyncio
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

Send = Callable[[dict[str, Any]], Awaitable[None]]
OUT_CHUNK_BYTES = 4000  # half a second of mu-law per WebSocket message


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
            await self._transcriber.stop()
            for task in (listener, greeter):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (listener, greeter) if t is not None), return_exceptions=True)

    async def _listen(self) -> None:
        async for heard in self._transcriber.events():
            if heard.is_partial:
                if self.speaking and heard.text.strip():
                    await self.barge_in()
                continue
            await self.handle_utterance(heard.text)

    async def handle_utterance(self, text: str) -> None:
        async with self._utterance_lock:
            self.turns += 1
            result = await asyncio.to_thread(run_turn, self._brain, self._hooks, self.ctx, text)
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
        self._interrupted.set()
        self._pending_marks.clear()
        self.speaking = False
        await self._send({"event": "clear", "streamSid": self.stream_sid})
