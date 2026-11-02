"""Ears and mouth for arm A: Transcribe streaming in, Polly out, each behind a small protocol with a fake.

Why the protocols: the media session is tested with fakes and no network; the real pair is swapped in by
`make dev`. Why the official v4 client and not `amazon-transcribe`: that package's own README now says it is
deprecated and points here (read 2026-11-01, DR-006).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from candidate_line.telephony.audio import SAMPLE_RATE


@dataclass(frozen=True)
class Heard:
    text: str
    is_partial: bool


class Transcriber(Protocol):
    async def start(self) -> None: ...

    async def feed(self, pcm16: bytes) -> None: ...

    def events(self) -> AsyncIterator[Heard]: ...

    async def stop(self) -> None: ...


class Speaker(Protocol):
    def say(self, text: str) -> bytes:
        """Returns 8 kHz mu-law for the text. Blocking; the session calls it in a thread."""


class TranscribeStreamingTranscriber:
    def __init__(self, region: str, language: str = "en-US") -> None:
        self._region = region
        self._language = language
        self._stream: Any = None
        self._client: Any = None

    async def start(self) -> None:
        from aws_sdk_transcribe_streaming.client import AsyncTranscribeStreamingClient
        from aws_sdk_transcribe_streaming.config import AsyncTranscribeStreamingConfig
        from aws_sdk_transcribe_streaming.models import StartStreamTranscriptionInput
        from smithy_http.aio.crt import AWSCRTHTTPClient

        # The duplex stream needs the CRT transport; the SDK's default aiohttp transport refuses it (read 2026-11-01).
        config = await AsyncTranscribeStreamingConfig.resolve(
            region=self._region, transport=AWSCRTHTTPClient()
        )
        self._client = AsyncTranscribeStreamingClient(config)
        self._stream = await self._client.start_stream_transcription(
            StartStreamTranscriptionInput(
                language_code=self._language,
                media_sample_rate_hertz=SAMPLE_RATE,
                media_encoding="pcm",
                enable_partial_results_stabilization=True,
                partial_results_stability="medium",
            )
        )

    async def feed(self, pcm16: bytes) -> None:
        from aws_sdk_transcribe_streaming.models import AudioEvent, AudioStreamAudioEvent

        await self._stream.input_stream.send(AudioStreamAudioEvent(value=AudioEvent(audio_chunk=pcm16)))

    async def events(self) -> AsyncIterator[Heard]:
        from aws_sdk_transcribe_streaming.models import TranscriptResultStreamTranscriptEvent

        _, output = await self._stream.await_output()
        async for event in output:
            if not isinstance(event, TranscriptResultStreamTranscriptEvent):
                continue
            for result in event.value.transcript.results:
                text = result.alternatives[0].transcript if result.alternatives else ""
                if text:
                    yield Heard(text=text, is_partial=bool(result.is_partial))

    async def stop(self) -> None:
        if self._stream is not None:
            await self._stream.input_stream.close()


class PollySpeaker:
    def __init__(
        self, region: str, voice_id: str = "Matthew", engine: str = "neural", client: Any | None = None
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("polly", region_name=region)
        self._client = client
        self._voice = voice_id
        self._engine = engine

    def say(self, text: str) -> bytes:
        response = self._client.synthesize_speech(
            Text=text,
            OutputFormat="mulaw",
            SampleRate=str(SAMPLE_RATE),
            VoiceId=self._voice,
            Engine=self._engine,
        )
        return response["AudioStream"].read()


class ScriptedTranscriber:
    """A fake: the test pushes what the caller 'said'; `feed` only counts bytes."""

    def __init__(self) -> None:
        self.fed = 0
        self._queue: asyncio.Queue[Heard | None] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.started = self.stopped = False

    async def start(self) -> None:
        self.started = True
        self._loop = asyncio.get_running_loop()

    async def feed(self, pcm16: bytes) -> None:
        self.fed += len(pcm16)

    def _put(self, item: Heard | None) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        else:
            self._queue.put_nowait(item)

    def hear(self, text: str, is_partial: bool = False) -> None:
        self._put(Heard(text, is_partial))

    def finish(self) -> None:
        self._put(None)

    async def events(self) -> AsyncIterator[Heard]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def stop(self) -> None:
        # Like the real stream: closing our side ends the events, so a listener drains instead of hanging.
        self.stopped = True
        self._put(None)


class FakeSpeaker:
    """A fake: one mu-law byte per character, so a test can count what was 'said'."""

    def __init__(self, delay: Callable[[], None] | None = None) -> None:
        self.said: list[str] = []
        self._delay = delay

    def say(self, text: str) -> bytes:
        if self._delay:
            self._delay()
        self.said.append(text)
        return bytes([0xFF]) * len(text)
