"""Audio arithmetic for the phone path: mu-law to PCM and back, frames, and where a sentence ends.

Why audioop: Twilio sends 8 kHz 8-bit mu-law and Transcribe wants PCM; the standard library did this in four
lines until 3.13 removed it, which is why the project pins 3.12 (DR-004). Polly speaks mu-law directly, so the
way back needs no codec; `pcm16_to_mulaw` exists for the probe caller and the tests.
"""

from __future__ import annotations

import audioop  # noqa: DEP004  (deprecated in 3.12, gone in 3.13; DR-004 pins 3.12 for it)
import base64
import re
from collections.abc import Iterator

SAMPLE_RATE = 8000
FRAME_MS = 20
MULAW_FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000  # 160 bytes of mu-law per 20 ms frame
PCM_FRAME_BYTES = MULAW_FRAME_BYTES * 2

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def mulaw_to_pcm16(data: bytes) -> bytes:
    return audioop.ulaw2lin(data, 2)


def pcm16_to_mulaw(data: bytes) -> bytes:
    return audioop.lin2ulaw(data, 2)


def decode_twilio_payload(payload: str) -> bytes:
    """Twilio's media payload is base64 of raw mu-law."""
    return base64.b64decode(payload)


def encode_twilio_payload(mulaw: bytes) -> str:
    return base64.b64encode(mulaw).decode("ascii")


def frames(data: bytes, size: int = MULAW_FRAME_BYTES) -> Iterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


def split_sentences(text: str) -> list[str]:
    """Polly is called per sentence so the first one plays while the rest are still being made."""
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    return parts


def rms(pcm16: bytes) -> int:
    return audioop.rms(pcm16, 2) if pcm16 else 0
