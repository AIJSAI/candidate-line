"""The probe caller: a scripted synthetic candidate that talks to the line as speech and brings back a transcript.

Why it exists: an edge case is tested as audio through the whole path, not only as text, and the turn gap
(the silence between the caller's last word and Gus's first) is measured in-process, which is DR-001's
measurement without a recording. The probe plays the Twilio side of the media stream: it sends `media` frames
of its own Polly voice in real time and silence frames in between (as a phone line does), returns Gus's
`mark`s once the audio they close has "played", honours `clear`, and transcribes what Gus said. Two ways to
connect share this class (DR-011): `direct` opens the line's `/media` WebSocket on the loopback or the tunnel;
`dial` places a real call through a second number and Twilio relays the same messages.
"""

from __future__ import annotations

import asyncio
import audioop
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from candidate_line.telephony.audio import (
    MULAW_FRAME_BYTES,
    SAMPLE_RATE,
    decode_twilio_payload,
    encode_twilio_payload,
    frames,
    mulaw_to_pcm16,
)
from candidate_line.telephony.speech import Speaker, Transcriber

log = logging.getLogger("candidate_line.probe")
Send = Callable[[dict[str, Any]], Awaitable[None]]
SILENCE_FRAME = b"\xff" * MULAW_FRAME_BYTES  # mu-law 0xFF is digital silence
SPEECH_RMS = (
    500  # 16-bit RMS above which a 20 ms frame counts as speech on a phone line (noise sits far below)
)


def has_speech(mulaw: bytes) -> bool:
    """Whether a mu-law frame carries speech-level energy; a real line sends silence frames between words."""
    return audioop.rms(mulaw_to_pcm16(mulaw), 2) >= SPEECH_RMS


@dataclass(frozen=True)
class Exchange:
    who: str  # "probe" or "gus"
    text: str
    at_ms: int
    gap_ms: int | None = None  # for gus: silence between the probe's last frame and Gus's first


@dataclass
class ProbeTranscript:
    exchanges: list[Exchange] = field(default_factory=list)
    clears: int = 0

    def gus_lines(self) -> list[str]:
        return [e.text for e in self.exchanges if e.who == "gus"]

    def gaps_ms(self) -> list[int]:
        return [e.gap_ms for e in self.exchanges if e.who == "gus" and e.gap_ms is not None]


class ProbeSession:
    def __init__(
        self,
        send: Send,
        transcriber: Transcriber,
        speaker: Speaker,
        lines: list[str],
        stream_sid: str = "probe",
        silence_ms: int = 700,
        reply_timeout_s: float = 12.0,
        real_time: bool = True,
        twilio_side: bool = False,
    ) -> None:
        # `twilio_side`: the probe sits where the line usually sits, on the far end of a Twilio stream (dial mode,
        # DR-011). Twilio then sends `start`, a continuous 8 kHz feed with silence in it, and acks for our marks; the
        # probe sends no `connected`, `start` or `stop`, and counts Gus as speaking only when a frame carries energy.
        self._twilio_side = twilio_side
        self._send = send
        self._transcriber = transcriber
        self._speaker = speaker
        self._lines = list(lines)
        self.stream_sid = stream_sid
        self._silence = silence_ms / 1000
        self._reply_timeout = reply_timeout_s
        self._real_time = real_time
        self.transcript = ProbeTranscript()
        self._t0 = time.monotonic()
        self._gus_audio_since_probe = False
        self._probe_finished_at: float | None = None
        self._pending_gap: int | None = None
        self._playing_until = time.monotonic()  # when the audio received so far finishes playing
        self._last_fed = time.monotonic()
        self._speaking_now = False
        self._mark_seq = 0

    def _ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    async def run(self, incoming: AsyncIterator[dict[str, Any]]) -> ProbeTranscript:
        await self._transcriber.start()
        listener = asyncio.create_task(self._listen())
        talker = asyncio.create_task(self._converse())
        keepalive = asyncio.create_task(self._keep_streams_alive()) if self._real_time else None
        try:
            async for message in incoming:
                event = message.get("event")
                if event == "start" and self._twilio_side:
                    self.stream_sid = str(message.get("streamSid") or self.stream_sid)
                elif event == "media":
                    mulaw = decode_twilio_payload(message["media"]["payload"])
                    now = time.monotonic()
                    if self._twilio_side and not has_speech(mulaw):
                        self._last_fed = now
                        await self._transcriber.feed(mulaw_to_pcm16(mulaw))
                        continue
                    if not self._gus_audio_since_probe and self._probe_finished_at is not None:
                        self._pending_gap = int((now - self._probe_finished_at) * 1000)
                    self._gus_audio_since_probe = True
                    # The line sends a sentence in a burst; a phone plays it at 8,000 bytes a second.
                    self._playing_until = max(self._playing_until, now) + len(mulaw) / SAMPLE_RATE
                    self._last_fed = now
                    await self._transcriber.feed(mulaw_to_pcm16(mulaw))
                elif event == "mark" and self._twilio_side:
                    pass  # Twilio acknowledging the probe's own marks; nothing to return
                elif event == "mark":
                    # Twilio returns a mark once the audio before it has played; so does the probe.
                    asyncio.get_running_loop().create_task(
                        self._return_mark(message["mark"]["name"], self._playing_until)
                    )
                elif event == "clear":
                    self.transcript.clears += 1
                    self._playing_until = time.monotonic()
                elif event == "stop" and self._twilio_side:
                    break
                if talker.done():
                    break
        finally:
            if keepalive is not None:
                keepalive.cancel()
            # The CRT transport can hang a close or a cancel after the far side has gone (2026-11-02, dial mode),
            # so nothing here awaits a task that may be stuck: wait with a bound, cancel the rest, move on.
            stopper = asyncio.ensure_future(self._transcriber.stop())
            done, pending = await asyncio.wait({stopper, listener, talker}, timeout=5.0)
            for task in pending:
                task.cancel()
                log.warning("probe task %s did not finish in 5 s; left cancelled", task.get_name())
            for task in done:
                if task is not stopper and not task.cancelled() and task.exception() is not None:
                    log.error("probe task failed: %r", task.exception())
        return self.transcript

    async def _listen(self) -> None:
        async for heard in self._transcriber.events():
            if heard.is_partial:
                continue
            self.transcript.exchanges.append(Exchange("gus", heard.text, self._ms(), self._pending_gap))
            self._pending_gap = None

    async def _return_mark(self, name: str, when: float) -> None:
        if self._real_time:
            await asyncio.sleep(max(0.0, when - time.monotonic()))
        await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})

    async def _wait_for_gus_to_finish(self) -> None:
        """Gus has answered when audio arrived since the probe last spoke, finished playing, and `silence_ms` passed."""
        deadline = time.monotonic() + self._reply_timeout
        while time.monotonic() < deadline:
            if self._gus_audio_since_probe and time.monotonic() - self._playing_until >= self._silence:
                return
            await asyncio.sleep(0.02)

    async def _keep_streams_alive(self) -> None:
        """A phone line carries silence between words, and Transcribe closes a stream that hears nothing for 15 s.
        The probe sends silence frames to the line whenever it is not speaking, and feeds silence to its own
        ears whenever Gus is not sending, so neither stream starves in a long pause."""
        silence_pcm = mulaw_to_pcm16(SILENCE_FRAME)
        while True:
            await asyncio.sleep(0.1)
            if not self._speaking_now:
                for _ in range(5):
                    await self._send(
                        {
                            "event": "media",
                            "streamSid": self.stream_sid,
                            "media": {"payload": encode_twilio_payload(SILENCE_FRAME)},
                        }
                    )
            if time.monotonic() - self._last_fed >= 0.1:
                for _ in range(5):
                    await self._transcriber.feed(silence_pcm)
                self._last_fed = time.monotonic()

    async def _converse(self) -> None:
        if not self._twilio_side:
            await self._send({"event": "connected", "protocol": "Call", "version": "1.0.0"})
            await self._send(
                {
                    "event": "start",
                    "streamSid": self.stream_sid,
                    "start": {
                        "callSid": f"probe-{self.stream_sid}",
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": SAMPLE_RATE,
                            "channels": 1,
                        },
                    },
                }
            )
        await self._wait_for_gus_to_finish()  # the greeting
        for line in self._lines:
            self.transcript.exchanges.append(Exchange("probe", line, self._ms()))
            mulaw = await asyncio.to_thread(self._speaker.say, line)
            self._gus_audio_since_probe = False
            self._speaking_now = True
            for chunk in frames(mulaw, MULAW_FRAME_BYTES):
                await self._send(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": encode_twilio_payload(chunk)},
                    }
                )
                if self._real_time:
                    await asyncio.sleep(len(chunk) / SAMPLE_RATE)
            self._speaking_now = False
            self._probe_finished_at = time.monotonic()
            if self._twilio_side:
                self._mark_seq += 1
                await self._send(
                    {
                        "event": "mark",
                        "streamSid": self.stream_sid,
                        "mark": {"name": f"probe-{self._mark_seq}"},
                    }
                )
            await self._wait_for_gus_to_finish()
        await asyncio.sleep(self._silence)
        self._speaking_now = True  # quiets the keepalive: nothing follows a stop
        if not self._twilio_side:
            await self._send({"event": "stop", "streamSid": self.stream_sid})
