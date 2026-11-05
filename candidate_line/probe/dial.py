"""`make probe-dial CASE=... PUBLIC=https://probe-host ARM=A`: the probe places a real call through its own number.

The probe runs a small WebSocket server; Twilio dials the line's number from the probe's number and connects
that call leg's audio to the server, so both arms hear the same Polly voice through the phone network. The
call is recorded on Twilio (dual channel), the recording is downloaded, the turn gaps are read from it (DR-001's
method of record) and from the probe's own clock (DR-011), both are printed, rows go to the bake-off CSV, and
the recording is deleted from Twilio. Credentials and numbers come from the environment (scripts/env.sh).

The answer mode (`--answer`, card 08) runs the other way round: the probe posts a signed synthetic application
for its own number, points its number's voice URL at itself for the run, answers the line's outbound call with one
short hello, says the PIN and one answer per posted question, and does it twice, once with every requirement met
and once with one not met. Each call is recorded dual-channel and the recording is deleted from Twilio whatever
else happens. It rings a real phone line and spends real money, so it runs only with `--watched`, with James
watching (card 08, lane B).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import hmac
import json
import logging
import secrets
import statistics
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from candidate_line.outbound.intake import APPLICATIONS_PATH, ROLES_PATH, signed_headers
from candidate_line.probe.direct import load_case, score
from candidate_line.probe.recording import gaps_from_recording, line_channel, transcribe_pcm16
from candidate_line.probe.session import Exchange, ProbeSession, ProbeTranscript
from candidate_line.settings import Settings
from candidate_line.telephony.app import twilio_signature
from candidate_line.telephony.speech import PollySpeaker, TranscribeStreamingTranscriber
from candidate_line.telephony.twilio_rest import TwilioError, TwilioRest

log = logging.getLogger("candidate_line.probe")


def probe_stream_twiml(probe_wss: str) -> str:
    """The TwiML that connects the probe's call leg to its own WebSocket server."""
    return f'<Response><Connect><Stream url="{probe_wss}/probe-media" /></Connect></Response>'


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


# The answer mode.

# The first dial is two minutes after intake, the dialler ticks every 15 s and waits out its own first 120 s, and
# the phone rings for up to 30 s: seven minutes covers all of it with room.
ANSWER_WAIT_S = 420
PROBE_FIRST_NAME = "Probe"  # synthetic, and no person's name (AGENTS.md rule 10)
_DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
# What the line must say for each case (spec 9.9): the met line's offer, or the not-met line's posted words.
MET_PHRASE = "nearest open interview times"
NOT_MET_PHRASE = "the posting asks for"


@dataclass(frozen=True)
class AnswerCase:
    name: str  # "met" or "not_met"
    pin: str
    lines: list[str]
    expect: str


def _answer(question: Mapping[str, Any], meets: bool) -> str:
    """The probe's answer to one posted question, chosen from its closed rule to meet it or to miss it."""
    kind, rule = question["kind"], dict(question["rule"])
    if kind == "yes_no":
        wanted = str(rule["equals"])
        said = wanted if meets else ("no" if wanted == "yes" else "yes")
        return f"{said.capitalize()}."
    if kind == "choice":
        allowed = set(rule["one_of"])
        option = next(o for o in question["options"] if (o["id"] in allowed) == meets)
        return f"{str(option['say']).capitalize()}."
    low, high = int(question["range"]["min"]), int(question["range"]["max"])
    if "at_least" in rule:
        n = int(rule["at_least"])
        value = min(high, n + 5) if meets else max(low, n - 5)
    elif "at_most" in rule:
        n = int(rule["at_most"])
        value = max(low, n - 5) if meets else min(high, n + 5)
    else:
        a, b = (int(x) for x in rule["between"])
        value = (a + b) // 2 if meets else (a - 1 if a > low else b + 1)
    return f"{value}."


def answer_cases(role: Mapping[str, Any], pins: tuple[str, str] | None = None) -> list[AnswerCase]:
    """The two calls: every posted requirement met, then the first one not met. Each opens with one short hello,
    says its PIN digit by digit, answers every question in posted order, then picks the first time or says
    goodbye."""
    pins = pins or (f"{secrets.randbelow(10000):04d}", f"{secrets.randbelow(10000):04d}")
    cases: list[AnswerCase] = []
    for name, pin in zip(("met", "not_met"), pins, strict=True):
        answers = [_answer(q, meets=name == "met" or i > 0) for i, q in enumerate(role["questions"])]
        closing = "The first one, please." if name == "met" else "Thank you, goodbye."
        lines = ["Hello?", " ".join(_DIGIT_WORDS[int(d)] for d in pin) + ".", *answers, closing]
        cases.append(AnswerCase(name, pin, lines, MET_PHRASE if name == "met" else NOT_MET_PHRASE))
    return cases


def application_body(role_id: str, phone: str, zone: str, pin: str, now: datetime | None = None) -> bytes:
    """A synthetic application for the probe's own number, in intake's closed schema (DR-025 section 10)."""
    texts = (yaml.safe_load(APPLICATIONS_PATH.read_text(encoding="utf-8")) or {}).get("consent_texts") or {}
    version = max(texts)
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return json.dumps(
        {
            "first_name": PROBE_FIRST_NAME,
            "role": role_id,
            "phone": phone,
            "zone": zone,
            "pin": pin,
            "consent": {"version": version, "accepted": True, "at": at, "source": "operator"},
        },
        separators=(",", ":"),
    ).encode()


def post_application(
    line_url: str,
    key: str,
    body: bytes,
    opener: Callable[[urllib.request.Request, float], bytes] | None = None,
) -> dict[str, Any]:
    """Posts one signed application to the line's intake and returns its answer: the code and the status."""
    request = urllib.request.Request(
        line_url.rstrip("/") + "/applications", data=body, method="POST", headers=signed_headers(key, body)
    )

    def urlopen(req: urllib.request.Request, timeout: float) -> bytes:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()

    return json.loads((opener or urlopen)(request, 30.0))


@contextlib.contextmanager
def voice_url_pointed_at(twilio: TwilioRest, number: str, url: str) -> Iterator[None]:
    """Points the probe's number at the probe for the run and puts back what it was, even when the run fails."""
    before = twilio.incoming_number(number)
    twilio.set_voice_url(before["sid"], url, "POST")
    try:
        yield
    finally:
        twilio.set_voice_url(before["sid"], before["voice_url"], before["voice_method"])


def finish_recording(twilio: TwilioRest, recording_sid: str, wav: Path) -> tuple[list[Any], str]:
    """Downloads the dual-channel recording, reads the gaps from it, and deletes it from Twilio in every case,
    whether or not the download worked: Twilio keeps no audio of the line (spec section 5)."""
    try:
        if not wait_until(lambda: twilio.recording_ready(recording_sid), 60, 2.0):
            return [], "recording not ready in 60 s"
        twilio.download_recording(recording_sid, wav)
        return gaps_from_recording(wav)
    finally:
        try:
            twilio.delete_recording(recording_sid)
        except TwilioError as error:
            log.error("the recording could not be deleted from Twilio; delete it by hand: %s", error)


@dataclass
class AnswerCall:
    """What the probe's server saw of one call: its CallSid and the transcript."""

    call_sid: str | None = None
    transcript: ProbeTranscript | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def probe_app(
    auth_token: str,
    public_url: str,
    line_number: str,
    make_session: Callable[[Any], ProbeSession],
    call: AnswerCall,
) -> FastAPI:
    """The probe's own small server: `/probe-voice` answers the line's call to the probe's number, signature
    checked and only for a call from the line, and `/probe-media` runs the probe's session on that call's stream."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    base = public_url.rstrip("/")
    wss = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)

    @app.post("/probe-voice")
    async def voice(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        expected = twilio_signature(auth_token, base + "/probe-voice", form)
        if not hmac.compare_digest(expected, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403, detail="bad Twilio signature")
        if form.get("From") != line_number or call.call_sid is not None:
            # Only the line's one call is answered; anything else ringing the probe's number is hung up.
            return Response(content="<Response><Hangup/></Response>", media_type="text/xml")
        call.call_sid = form.get("CallSid")
        twiml = f'<Response><Connect><Stream url="{escape(wss)}/probe-media" /></Connect></Response>'
        return Response(content=twiml, media_type="text/xml")

    @app.websocket("/probe-media")
    async def media(ws: WebSocket) -> None:
        await ws.accept()
        if call.transcript is not None or call.call_sid is None:
            await ws.close(code=1008)
            return

        async def incoming() -> Any:
            while True:
                try:
                    message = await ws.receive_json()
                except WebSocketDisconnect:
                    return
                yield message
                if message.get("event") == "stop":
                    return

        session = make_session(ws.send_json)
        try:
            call.transcript = await asyncio.wait_for(session.run(incoming()), timeout=300)
        except TimeoutError:
            call.transcript = session.transcript
        finally:
            call.done.set()
        with contextlib.suppress(Exception):
            await ws.close()

    return app


def answer_main(args: argparse.Namespace, settings: Settings) -> int:
    """The answer mode's run: two applications, two calls answered, two recordings deleted."""
    import uvicorn

    wanted = {
        "TWILIO_ACCOUNT_SID": settings.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": settings.twilio_auth_token,
        "TWILIO_LINE_NUMBER": settings.twilio_line_number,
        "TWILIO_PROBE_NUMBER": settings.twilio_probe_number,
        "INTAKE_SIGNING_KEY": settings.intake_signing_key,
    }
    for name, value in wanted.items():
        if not value:
            print(f"{name} is not set; store it with make secret NAME={name}", file=sys.stderr)
            return 2
    line_url = args.line_url or settings.public_base_url
    if not line_url:
        print("the line's public URL is needed: --line-url or PUBLIC_BASE_URL", file=sys.stderr)
        return 2
    roles = {r["id"]: r for r in (yaml.safe_load(ROLES_PATH.read_text(encoding="utf-8")) or {})["roles"]}
    role = roles[args.role]
    twilio = TwilioRest(str(settings.twilio_account_sid), str(settings.twilio_auth_token))
    probe_number, line_number = str(settings.twilio_probe_number), str(settings.twilio_line_number)
    failures = 0
    with voice_url_pointed_at(twilio, probe_number, args.public_url.rstrip("/") + "/probe-voice"):
        for case in answer_cases(role):
            failures += asyncio.run(_answer_one(args, settings, twilio, case, line_url, line_number, uvicorn))
    return 1 if failures else 0


async def _answer_one(
    args: argparse.Namespace,
    settings: Settings,
    twilio: TwilioRest,
    case: AnswerCase,
    line_url: str,
    line_number: str,
    uvicorn: Any,
) -> int:
    call = AnswerCall()

    def make_session(send: Any) -> ProbeSession:
        return ProbeSession(
            send,
            TranscribeStreamingTranscriber(settings.aws_region),
            PollySpeaker(settings.aws_region, voice_id=args.voice),
            case.lines,
            stream_sid=f"probe-answer-{case.name}",
            silence_ms=1500,  # the opening and the PIN ask come as two utterances with the stream's start between
            reply_timeout_s=20.0,
            twilio_side=True,
        )

    app = probe_app(str(settings.twilio_auth_token), args.public_url, line_number, make_session, call)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    recording_sid: str | None = None
    try:
        body = application_body(args.role, str(settings.twilio_probe_number), args.zone, case.pin)
        answer = await asyncio.to_thread(post_application, line_url, str(settings.intake_signing_key), body)
        print(f"{case.name}: application {answer.get('code')} {answer.get('status')}")
        if answer.get("status") != "scheduled":
            print(f"{case.name}: the line will not dial this application ({answer.get('status')})")
            return 1
        if not await _wait_for(lambda: call.call_sid is not None, ANSWER_WAIT_S):
            print(f"{case.name}: the line did not call within {ANSWER_WAIT_S} s")
            return 1
        sid = str(call.call_sid)
        if await asyncio.to_thread(wait_until, lambda: twilio.call_status(sid) == "in-progress", 40):
            recording_sid = await asyncio.to_thread(twilio.start_recording, sid)
        await asyncio.wait_for(call.done.wait(), timeout=320)
        if await asyncio.to_thread(twilio.call_status, sid) == "in-progress":
            await asyncio.to_thread(twilio.hang_up, sid)
    finally:
        if recording_sid is not None:
            args.recordings.mkdir(parents=True, exist_ok=True)
            wav = args.recordings / f"answer-{case.name}-{call.call_sid}.wav"
            recorded, note = await asyncio.to_thread(finish_recording, twilio, recording_sid, wav)
            print(f"{case.name}: recording {note}; {len(recorded)} turn gaps read; deleted from Twilio")
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(serving, timeout=10)
    heard = " ".join(call.transcript.gus_lines() if call.transcript else [])
    for e in call.transcript.exchanges if call.transcript else []:
        print(f"{e.at_ms:6d} ms {e.who:>5}: {e.text}")
    ok = "automated hiring line" in heard.lower() and case.expect in heard.lower()
    print(f"{case.name}: {'PASS' if ok else 'FAIL'} (heard the opening and {case.expect!r})")
    return 0 if ok else 1


async def _wait_for(predicate: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.5)
    return predicate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the probe caller places a real call through its own number")
    parser.add_argument("--case", type=Path, help="the dial mode's case file")
    parser.add_argument(
        "--answer", action="store_true", help="apply for the probe's number and answer the line"
    )
    parser.add_argument(
        "--watched", action="store_true", help="the answer mode runs only with James watching"
    )
    parser.add_argument(
        "--line-url", default=None, help="the line's public https base (default PUBLIC_BASE_URL)"
    )
    parser.add_argument("--role", default="care-aide", help="the answer mode's role id")
    parser.add_argument("--zone", default="America/Chicago", help="the answer mode's applicant zone")
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

    settings = Settings.from_env()
    if args.answer:
        if not args.watched:
            print("the answer mode rings a real line and spends money: run it with --watched, James watching")
            return 2
        return answer_main(args, settings)
    if args.case is None:
        parser.error("--case is needed in the dial mode")
    wanted = {
        "TWILIO_ACCOUNT_SID": settings.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": settings.twilio_auth_token,
        "TWILIO_LINE_NUMBER": settings.twilio_line_number,
        "TWILIO_PROBE_NUMBER": settings.twilio_probe_number,
    }
    for name, value in wanted.items():
        if not value:
            print(f"{name} is not set; store it with make secret NAME={name}", file=sys.stderr)
            return 2
    twilio = TwilioRest(str(settings.twilio_account_sid), str(settings.twilio_auth_token))
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
            lambda: twilio.place_call(
                str(settings.twilio_line_number),
                str(settings.twilio_probe_number),
                twiml=probe_stream_twiml(wss),
            )
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
        twilio.delete_recording(recording_sid)  # the transcript holds the turns; Twilio keeps nothing
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
