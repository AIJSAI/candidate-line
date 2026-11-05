"""`make probe CASE=... URL=ws://127.0.0.1:8000/media`: the probe talks to the line over its media WebSocket.

No phone number is involved, so it costs nothing and runs on the loopback. The `dial` mode (DR-011) places a
real call through a second number once one exists; the session class is the same.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
from pathlib import Path

import yaml

log = logging.getLogger("candidate_line.probe")

from candidate_line.brain import Reply
from candidate_line.evals.checks import evaluate
from candidate_line.evals.schema import Case, parse_case
from candidate_line.probe.session import ProbeSession, ProbeTranscript
from candidate_line.settings import Settings
from candidate_line.telephony.speech import PollySpeaker, TranscribeStreamingTranscriber
from candidate_line.turn import TurnResult


def load_case(path: Path) -> Case:
    return parse_case(yaml.safe_load(path.read_text()), path)


def score(case: Case, transcript: ProbeTranscript) -> list[str]:
    """Runs each turn's checks against what Gus was heard to say after that line. Returns the failures."""
    failures = []
    gus = transcript.gus_lines()
    spoken_turns = [t for t in case.turns if t.user is not None]
    everything = " ".join(gus)
    for i, turn in enumerate(spoken_turns):
        heard = gus[i + 1] if i + 1 < len(gus) else ""  # gus[0] is the greeting
        result = TurnResult(
            heard=turn.user or "", spoken=heard, reply=Reply(heard, 0, 0, 0, "probe", "probe")
        )
        for check in turn.checks:
            if check.name == "spoken_not_matches":
                # Rule (a) is absolute: a forbidden sentence anywhere in the call counts, however the replies
                # split into transcript lines (the recording's finals do not align one to one with turns).
                whole = TurnResult(
                    heard=turn.user or "",
                    spoken=everything,
                    reply=Reply(everything, 0, 0, 0, "probe", "probe"),
                )
                verdict = evaluate(check, whole)
            else:
                verdict = evaluate(check, result)
            if not verdict.passed:
                failures.append(f"turn {i}: {check.name} {check.arg!r}: {verdict.detail}")
    return failures


async def run_direct(url: str, case: Case, settings: Settings, voice: str) -> ProbeTranscript:
    import websockets

    counts: dict[str, int] = {}

    def count(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    async with websockets.connect(url, max_size=None, ping_interval=20, ping_timeout=60) as ws:

        async def send(message: dict) -> None:
            count("sent:" + message["event"])
            await ws.send(json.dumps(message))

        async def incoming():
            try:
                async for raw in ws:
                    message = json.loads(raw)
                    count("got:" + str(message.get("event")))
                    yield message
            except websockets.ConnectionClosed as closed:
                # The transcript so far is still worth printing; the close is reported next to it.
                log.warning("the line closed the stream: %s; events so far %s", closed, counts)

        session = ProbeSession(
            send,
            TranscribeStreamingTranscriber(settings.aws_region),
            PollySpeaker(settings.aws_region, voice_id=voice),
            [t.user for t in case.turns if t.user is not None],
            stream_sid=f"probe-{case.id}",
            auth_token=settings.twilio_auth_token,
        )
        transcript = await session.run(incoming())
        log.info("events %s", counts)
        return transcript


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="a scripted synthetic candidate that talks to the line")
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/media")
    parser.add_argument("--voice", default="Joanna", help="the probe's Polly voice; not Gus's")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    case = load_case(args.case)
    transcript = asyncio.run(run_direct(args.url, case, Settings.from_env(), args.voice))
    for e in transcript.exchanges:
        gap = f" (gap {e.gap_ms} ms)" if e.gap_ms is not None else ""
        print(f"{e.at_ms:6d} ms {e.who:>5}: {e.text}{gap}")
    gaps = transcript.gaps_ms()
    if gaps:
        print(
            f"turn gap: median {statistics.median(gaps):.0f} ms, max {max(gaps)} ms over {len(gaps)} replies; clears {transcript.clears}"
        )
    failures = score(case, transcript)
    for f in failures:
        print("FAIL", f)
    print(f"{case.id}: {'PASS' if not failures else f'{len(failures)} failed checks'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
