"""`make probe-dial CASE=... PUBLIC=https://probe-host ARM=A`: the probe places a real call through its own number.

The probe runs a small WebSocket server; Twilio dials the line's number from the probe's number and connects
that call leg's audio to the server, so both arms hear the same Polly voice through the phone network. The
call is recorded on Twilio (dual channel), the recording is downloaded, the turn gaps are read from it (DR-001's
method of record) and from the probe's own clock (DR-011), both are printed, rows go to the bake-off CSV, and
the recording is deleted from Twilio. Credentials and numbers come from the environment (scripts/env.sh).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import logging
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from candidate_line.probe.direct import load_case, score
from candidate_line.probe.recording import gaps_from_recording, line_channel, transcribe_pcm16
from candidate_line.probe.session import Exchange, ProbeSession, ProbeTranscript
from candidate_line.settings import Settings
from candidate_line.telephony.speech import PollySpeaker, TranscribeStreamingTranscriber

log = logging.getLogger("candidate_line.probe")
API = "https://api.twilio.com/2010-04-01/Accounts"


class Twilio:
    """The four REST calls the dial mode needs, over the standard library; no SDK, nothing cached."""

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self.sid = account_sid
        self._auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()

    def _request(self, method: str, path: str, data: dict[str, str] | None = None, raw: bool = False) -> Any:
        url = f"{API}/{self.sid}/{path}"
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(
            url, data=body, method=method, headers={"Authorization": f"Basic {self._auth}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
        return payload if raw else json.loads(payload or b"{}")

    def place_call(self, to: str, from_: str, probe_wss: str) -> str:
        twiml = f'<Response><Connect><Stream url="{probe_wss}/probe-media" /></Connect></Response>'
        call = self._request("POST", "Calls.json", {"To": to, "From": from_, "Twiml": twiml})
        if "sid" not in call:
            raise RuntimeError(f"Twilio refused the call: {call.get('message')}")
        return str(call["sid"])

    def call_status(self, call_sid: str) -> str:
        return str(self._request("GET", f"Calls/{call_sid}.json").get("status"))

    def start_recording(self, call_sid: str) -> str:
        rec = self._request("POST", f"Calls/{call_sid}/Recordings.json", {"RecordingChannels": "dual"})
        if "sid" not in rec:
            raise RuntimeError(f"Twilio refused the recording: {rec.get('message')}")
        return str(rec["sid"])

    def hang_up(self, call_sid: str) -> None:
        self._request("POST", f"Calls/{call_sid}.json", {"Status": "completed"})

    def recording_ready(self, recording_sid: str) -> bool:
        return self._request("GET", f"Recordings/{recording_sid}.json").get("status") == "completed"

    def download_recording(self, recording_sid: str, to: Path) -> None:
        to.write_bytes(self._request("GET", f"Recordings/{recording_sid}.wav?RequestedChannels=2", raw=True))

    def delete_recording(self, recording_sid: str) -> None:
        self._request("DELETE", f"Recordings/{recording_sid}.json")


async def serve_one_call(port: int, make_session) -> tuple[ProbeTranscript, dict[str, int]]:
    """Accepts Twilio's one connection on /probe-media, runs the session on it, returns the transcript."""
    import websockets

    done: asyncio.Future = asyncio.get_running_loop().create_future()
    counts: dict[str, int] = {}

    def count(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    async def handler(ws) -> None:
        if done.done():
            await ws.close()
            return

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
                log.warning("Twilio closed the stream: %s; events so far %s", closed, counts)

        session = make_session(send)
        try:
            # The transcript lives on the session, so a slow cleanup cannot take the measurements with it.
            transcript = await asyncio.wait_for(session.run(incoming()), timeout=180)
        except TimeoutError:
            log.warning("the probe session did not finish in 180 s; keeping what it heard")
            transcript = session.transcript
        except Exception as error:
            if not done.done():
                done.set_exception(error)
            raise
        try:
            await ws.close()  # the probe has said its last line; closing the stream ends the call leg
        except Exception as error:  # noqa: BLE001
            log.debug("close after the last line: %s", error)
        if not done.done():
            done.set_result(transcript)

    server = await websockets.serve(
        handler, "127.0.0.1", port, max_size=None, ping_interval=20, ping_timeout=60
    )
    try:
        transcript = await asyncio.wait_for(done, timeout=240)
    finally:
        # Never wait on a handler that is stuck in a close: shut the server down with a bound.
        server.close(close_connections=True)
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=5)
        except TimeoutError:
            log.warning("the probe server did not close within 5 s; continuing")
    return transcript, counts


def wait_until(predicate, timeout_s: float, every_s: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(every_s)
    return False


def append_rows(csv_path: Path, arm: str, call: str, transcript: ProbeTranscript, recorded, note: str) -> int:
    """One row per measured turn: the probe's clock and, where it exists, the recording's reading."""
    probe_lines = [e for e in transcript.exchanges if e.who == "probe"]
    gus_replies = [e for e in transcript.exchanges if e.who == "gus"]
    rows = []
    for n, line in enumerate(probe_lines, start=1):
        reply = next((g for g in gus_replies if g.at_ms > line.at_ms), None)
        probe_gap = reply.gap_ms if reply is not None else ""
        reply_text = reply.text if reply is not None else ""
        rows.append([arm, call, n, "probe", probe_gap, line.text, reply_text, "", note])
        rec = next((r for r in recorded if r.turn == n), None)
        if rec is not None:
            rows.append([arm, call, n, "recording", rec.gap_ms, line.text, reply_text, "", note])
    with csv_path.open("a", newline="") as f:
        csv.writer(f).writerows(rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the probe caller places a real call through its own number")
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument(
        "--public-url", required=True, help="the probe server's public https host (its tunnel)"
    )
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--voice", default="Joanna", help="the probe's Polly voice; not Gus's")
    parser.add_argument("--arm", default="A")
    parser.add_argument("--csv", type=Path, default=None, help="append one row per turn to this bake-off CSV")
    parser.add_argument("--recordings", type=Path, default=Path("bakeoff/recordings"))
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    env = os.environ
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_LINE_NUMBER", "TWILIO_PROBE_NUMBER"):
        if not env.get(name):
            print(f"{name} is not set; store it with make secret NAME={name}", file=sys.stderr)
            return 2
    twilio = Twilio(env["TWILIO_ACCOUNT_SID"], env["TWILIO_AUTH_TOKEN"])
    settings = Settings.from_env()
    case = load_case(args.case)
    lines = [t.user for t in case.turns if t.user is not None]
    wss = args.public_url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)

    def make_session(send):
        return ProbeSession(
            send,
            TranscribeStreamingTranscriber(settings.aws_region),
            PollySpeaker(settings.aws_region, voice_id=args.voice),
            lines,
            stream_sid=f"probe-{case.id}",
            # Nova Sonic pauses longer between sentences than arm A's burst; 700 ms made the probe talk over it.
            silence_ms=1200,
            twilio_side=True,
        )

    async def run() -> tuple[ProbeTranscript, dict[str, int], str, str | None]:
        server = asyncio.create_task(serve_one_call(args.port, make_session))
        await asyncio.sleep(0.5)  # the server is listening before Twilio is asked to connect
        call_sid = await asyncio.to_thread(
            twilio.place_call, env["TWILIO_LINE_NUMBER"], env["TWILIO_PROBE_NUMBER"], wss
        )
        log.info("call placed: %s", call_sid)
        recording_sid: str | None = None
        if not args.no_record:
            if await asyncio.to_thread(wait_until, lambda: twilio.call_status(call_sid) == "in-progress", 40):
                recording_sid = await asyncio.to_thread(twilio.start_recording, call_sid)
                log.info("recording started: %s", recording_sid)
            else:
                log.warning("the call never reached in-progress; no recording")
        transcript, counts = await server
        if await asyncio.to_thread(lambda: twilio.call_status(call_sid)) == "in-progress":
            await asyncio.to_thread(twilio.hang_up, call_sid)
        return transcript, counts, call_sid, recording_sid

    transcript, counts, call_sid, recording_sid = asyncio.run(run())
    log.info("events %s", counts)
    for e in transcript.exchanges:
        gap = f" (gap {e.gap_ms} ms)" if e.gap_ms is not None else ""
        print(f"{e.at_ms:6d} ms {e.who:>5}: {e.text}{gap}")
    gaps = transcript.gaps_ms()
    if gaps:
        print(
            f"probe clock: median {statistics.median(gaps):.0f} ms, max {max(gaps)} ms over {len(gaps)} replies; clears {transcript.clears}"
        )

    recorded, note = [], "no recording"
    if recording_sid is not None:
        args.recordings.mkdir(parents=True, exist_ok=True)
        wav = args.recordings / f"{args.arm}-{case.id}-{call_sid}.wav"
        if wait_until(lambda: twilio.recording_ready(recording_sid), 60, 2.0):
            twilio.download_recording(recording_sid, wav)
            recorded, note = gaps_from_recording(wav)
            if not transcript.gus_lines():
                # The live ears failed on this call; the recording still says what Gus said (method of record).
                pcm, rate = line_channel(wav)
                heard = asyncio.run(transcribe_pcm16(pcm, rate, settings.aws_region))
                for n, text in enumerate(heard):
                    rec = next((r for r in recorded if r.turn == n), None)  # heard[0] is the greeting
                    transcript.exchanges.append(Exchange("gus", text, 0, rec.gap_ms if rec else None))
                note += f"; words from the recording ({len(heard)} finals), live ears failed"
            rec_gaps = [r.gap_ms for r in recorded]
            if rec_gaps:
                print(
                    f"recording:   median {statistics.median(rec_gaps):.0f} ms, max {max(rec_gaps)} ms over {len(rec_gaps)} turns; {note}"
                )
            else:
                print(f"recording:   {note}")
        else:
            note = "recording not ready in 60 s"
            print(f"recording:   {note}")

    failures = score(case, transcript)
    for f in failures:
        print("FAIL", f)
    print(f"{case.id} on arm {args.arm}: {'PASS' if not failures else f'{len(failures)} failed checks'}")
    if args.csv is not None:
        n = append_rows(args.csv, args.arm, f"{case.id}:{call_sid[-6:]}", transcript, recorded, note)
        print(f"{n} rows appended to {args.csv}")
        if recording_sid is not None and recorded:
            twilio.delete_recording(recording_sid)  # the CSV holds the turns; Twilio keeps nothing
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
