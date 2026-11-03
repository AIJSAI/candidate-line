"""Ears and mouth for arm A: Transcribe streaming in, Polly out, each behind a small protocol with a fake.

Why the protocols: the media session is tested with fakes and no network; the real pair is swapped in by
`make dev`. Why the official v4 client and not `amazon-transcribe`: that package's own README now says it is
deprecated and points here (read 2026-11-01, DR-006).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from candidate_line.telephony.audio import SAMPLE_RATE

log = logging.getLogger("candidate_line.speech")


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


def boto3_credentials_resolver() -> Any:
    """The streaming SDK's resolver built from boto3's credential chain, the one that knows Identity Center profiles."""
    import boto3
    from smithy_aws_core.identity import AWSCredentialsIdentity, StaticCredentialsResolver

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("no AWS credentials in boto3's chain; run aws sso login --profile candidate-line")
    frozen = credentials.get_frozen_credentials()
    return StaticCredentialsResolver(
        identity=AWSCredentialsIdentity(
            access_key_id=frozen.access_key, secret_access_key=frozen.secret_key, session_token=frozen.token
        )
    )


class TranscribeStreamingTranscriber:
    def __init__(self, region: str, language: str = "en-US") -> None:
        self._region = region
        self._language = language
        self._stream: Any = None
        self._client: Any = None
        self._dead = False
        self._in_flight = 0

    async def start(self) -> None:
        from aws_sdk_transcribe_streaming.client import AsyncTranscribeStreamingClient
        from aws_sdk_transcribe_streaming.config import AsyncTranscribeStreamingConfig
        from aws_sdk_transcribe_streaming.models import StartStreamTranscriptionInput
        from smithy_http.aio.crt import AWSCRTHTTPClient

        # The duplex stream needs the CRT transport; the SDK's default aiohttp transport refuses it (read 2026-11-01).
        # The SDK's own credential chain cannot read an Identity Center profile and its start never returns
        # (2026-11-02, the first silent call); boto3's chain can and refreshes the role, so the stream borrows from it.
        config = await AsyncTranscribeStreamingConfig.resolve(
            region=self._region,
            transport=AWSCRTHTTPClient(),
            aws_credentials_identity_resolver=boto3_credentials_resolver(),
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

        if self._dead or self._stream is None:
            return
        self._in_flight += 1
        if self._in_flight > 1:
            # Two senders on one event stream interleave frames and break its signature chain (DR-011); say so.
            log.warning("Transcribe feed overlap: %d sends in flight", self._in_flight)
        try:
            # A send to a stream AWS has already completed never returns on the CRT transport (2026-11-02, the
            # probe's call); two seconds is far longer than any live send, so a timeout means the stream is gone.
            # The send is shielded: cancelling a CRT write mid-frame leaves a half frame on the wire, and the
            # server answers the next one with a signature error (the probe's logs, 2026-11-02 17:30 CT).
            await asyncio.wait_for(
                asyncio.shield(
                    self._stream.input_stream.send(AudioStreamAudioEvent(value=AudioEvent(audio_chunk=pcm16)))
                ),
                2.0,
            )
        except (TimeoutError, Exception) as error:  # noqa: BLE001
            self._dead = True
            log.warning("Transcribe stream is gone; no more audio is fed (%s)", type(error).__name__)
        finally:
            self._in_flight -= 1

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
        if self._stream is not None and not self._dead:
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
