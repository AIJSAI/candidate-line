"""DR-001's method of record: the turn gap read from a Twilio dual-channel call recording.

One channel carries the caller, the other the line. A turn gap is the silence between the caller's last word
and the line's first word that answers it. Speech is found by energy: a 20 ms frame with a 16-bit RMS over
`SPEECH_RMS` is speech, and a segment ends after `hangover_ms` of quiet. The channel that speaks first is the
line (the greeting is always first); the other is the caller.
"""

from __future__ import annotations

import audioop
import wave
from dataclasses import dataclass
from pathlib import Path

SPEECH_RMS = 500
FRAME_MS = 20


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float


@dataclass(frozen=True)
class RecordedGap:
    turn: int
    caller_end_s: float
    line_start_s: float

    @property
    def gap_ms(self) -> int:
        return round((self.line_start_s - self.caller_end_s) * 1000)


def speech_segments(
    pcm16: bytes, rate: int, threshold: int = SPEECH_RMS, hangover_ms: int = 300
) -> list[Segment]:
    frame_bytes = rate * FRAME_MS // 1000 * 2
    segments: list[Segment] = []
    start: float | None = None
    quiet_ms = 0
    for i in range(0, len(pcm16) - frame_bytes + 1, frame_bytes):
        t = i / (rate * 2)
        loud = audioop.rms(pcm16[i : i + frame_bytes], 2) >= threshold
        if loud:
            if start is None:
                start = t
            quiet_ms = 0
        elif start is not None:
            quiet_ms += FRAME_MS
            if quiet_ms >= hangover_ms:
                segments.append(Segment(start, t - quiet_ms / 1000))
                start, quiet_ms = None, 0
    if start is not None:
        segments.append(Segment(start, len(pcm16) / (rate * 2)))
    return segments


def turn_gaps(caller: list[Segment], line: list[Segment]) -> list[RecordedGap]:
    """For each caller segment, the line's first segment that starts after it and before the caller's next one."""
    gaps: list[RecordedGap] = []
    for n, seg in enumerate(caller):
        next_caller = caller[n + 1].start_s if n + 1 < len(caller) else float("inf")
        answer = next((s for s in line if s.start_s >= seg.end_s and s.start_s < next_caller), None)
        if answer is not None:
            gaps.append(RecordedGap(turn=n + 1, caller_end_s=seg.end_s, line_start_s=answer.start_s))
    return gaps


def read_dual_wav(path: Path) -> tuple[bytes, bytes, int]:
    """Returns (channel 1, channel 2, rate) as 16-bit mono PCM."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 2:
            raise ValueError(f"{path}: expected a dual-channel recording, got {w.getnchannels()} channel(s)")
        width, rate = w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    if width != 2:
        data = audioop.lin2lin(data, width, 2)
    left = audioop.tomono(data, 2, 1, 0)
    right = audioop.tomono(data, 2, 0, 1)
    return left, right, rate


def gaps_from_recording(path: Path) -> tuple[list[RecordedGap], str]:
    """The recorded turn gaps and a one-line note saying which channel was taken as the line."""
    a, b, rate = read_dual_wav(path)
    seg_a, seg_b = speech_segments(a, rate), speech_segments(b, rate)
    if not seg_a or not seg_b:
        return [], "one channel is silent; no gaps measured"
    # The line speaks first: its greeting opens every call.
    if seg_a[0].start_s <= seg_b[0].start_s:
        line, caller, note = seg_a, seg_b, "channel 1 is the line (it spoke first), channel 2 the caller"
    else:
        line, caller, note = seg_b, seg_a, "channel 2 is the line (it spoke first), channel 1 the caller"
    return turn_gaps(caller, line), note
