import asyncio
import time

from candidate_line.brain import EchoBrain
from candidate_line.evals.schema import parse_case
from candidate_line.hooks import NoHooks
from candidate_line.probe.direct import score
from candidate_line.probe.session import Exchange, ProbeSession, ProbeTranscript
from candidate_line.telephony.audio import MULAW_FRAME_BYTES, encode_twilio_payload
from candidate_line.telephony.media import MediaSession
from candidate_line.telephony.speech import FakeSpeaker, ScriptedTranscriber


def test_probe_drives_a_media_session_end_to_end_and_measures_the_gap() -> None:
    """The probe and the line talk through two in-memory queues; both ears are scripted, both mouths fake."""
    to_line: asyncio.Queue = asyncio.Queue()
    to_probe: asyncio.Queue = asyncio.Queue()
    line_ears, probe_ears = ScriptedTranscriber(), ScriptedTranscriber()
    line_mouth, probe_mouth = FakeSpeaker(), FakeSpeaker()

    async def line_send(m):
        await to_probe.put(m)

    async def probe_send(m):
        await to_line.put(m)
        # The probe's media is "heard" by the line's scripted ears once its frames stop.
        if m["event"] == "stop":
            await to_probe.put({"event": "stop"})

    async def drain(q):
        while True:
            m = await q.get()
            yield m
            if m.get("event") == "stop":
                return

    line = MediaSession(
        line_send, line_ears, line_mouth, EchoBrain(), NoHooks(), "sys", "CA1", "S1", greeting="Hello."
    )
    probe = ProbeSession(
        probe_send,
        probe_ears,
        probe_mouth,
        ["My code is 4821.", "Thursday please."],
        silence_ms=60,
        reply_timeout_s=3,
        real_time=False,
    )

    async def line_ears_script():
        # Whenever the probe finishes a line (its frames arrived), the line's ears hear that line as a final.
        seen = 0
        while True:
            await asyncio.sleep(0.01)
            said = len(probe_mouth.said)
            if said > seen:
                seen = said
                await asyncio.sleep(0.02)
                line_ears.hear(probe_mouth.said[-1], is_partial=False)
            if len(line_mouth.said) >= 3:
                return

    async def probe_ears_script():
        # Whenever the line speaks, the probe's ears hear it as a final shortly after.
        seen = 0
        while True:
            await asyncio.sleep(0.01)
            if len(line_mouth.said) > seen:
                seen += 1
                probe_ears.hear(line_mouth.said[seen - 1], is_partial=False)
            if seen >= 3:
                return

    async def main():
        async def start_line():
            async for _ in ():
                pass

        line_task = asyncio.create_task(line.run(drain(to_line)))
        scripts = [asyncio.create_task(line_ears_script()), asyncio.create_task(probe_ears_script())]
        transcript = await asyncio.wait_for(probe.run(drain(to_probe)), 5)
        await asyncio.wait_for(line_task, 2)
        for s in scripts:
            s.cancel()
        return transcript

    transcript = asyncio.run(main())
    assert probe_mouth.said == ["My code is 4821.", "Thursday please."]
    assert line_mouth.said == ["Hello.", "My code is 4821.", "Thursday please."]
    assert transcript.gus_lines() == ["Hello.", "My code is 4821.", "Thursday please."]
    gaps = transcript.gaps_ms()
    assert len(gaps) == 2 and all(0 <= g < 2000 for g in gaps)
    assert transcript.clears == 0


def test_probe_waits_for_an_answer_after_a_barge_in_clears_the_line() -> None:
    """DR-011, 2026-11-02: Gus's long reply runs into the probe's next line and the line clears. The audio that
    arrived while the probe spoke is not an answer, so the probe waits for one before it says its next line."""
    line_frames, quiet_s = 30, 0.3
    sent: list[dict] = []
    frames_at: dict[int, list[float]] = {}  # probe line number -> when each of its frames went out
    at: dict[str, float] = {}

    class LongLines(FakeSpeaker):
        # Every line is 30 frames and each takes 5 ms to go out, so the probe's speech spans time off real time.
        def say(self, text: str) -> bytes:
            super().say(text)
            return b"\xff" * MULAW_FRAME_BYTES * line_frames

    ears, mouth = ScriptedTranscriber(), LongLines()

    async def send(m):
        sent.append(m)
        if m["event"] == "media":
            frames_at.setdefault(len(mouth.said), []).append(time.monotonic())
            await asyncio.sleep(0.005)

    def spoken(n: int) -> bool:
        return len(frames_at.get(n, [])) == line_frames

    async def until(done) -> None:
        while not done():
            await asyncio.sleep(0.005)

    gus = {"event": "media", "media": {"payload": encode_twilio_payload(b"\x00" * MULAW_FRAME_BYTES)}}

    async def line():
        yield gus
        ears.hear("Hello.", is_partial=False)
        await until(lambda: spoken(1))
        await asyncio.sleep(0.05)
        yield gus
        ears.hear("Code 4821, got it.", is_partial=False)
        # The reply runs long: its next sentence lands while the probe is saying line 2, and the line clears.
        await until(lambda: len(frames_at.get(2, [])) >= 5)
        for _ in range(5):
            yield gus
            await asyncio.sleep(0.01)
        ears.hear("Your interview is on Tuesday.", is_partial=False)
        at["clear"] = time.monotonic()
        yield {"event": "clear", "streamSid": "probe"}
        # Line 2 ends, the line stays quiet well past silence_ms, and only then does Gus answer line 2.
        await until(lambda: spoken(2))
        await asyncio.sleep(quiet_s)
        at["answer"] = time.monotonic()
        yield gus
        ears.hear("Thursday at ten is open.", is_partial=False)
        await until(lambda: spoken(3))
        await asyncio.sleep(0.05)
        yield gus
        ears.hear("Booked.", is_partial=False)
        await until(lambda: any(m["event"] == "stop" for m in sent))
        yield {"event": "stop"}

    probe = ProbeSession(
        send,
        ears,
        mouth,
        ["My code is 4821.", "Thursday please.", "Ten works."],
        silence_ms=60,
        reply_timeout_s=3,
        real_time=False,
    )
    transcript = asyncio.run(asyncio.wait_for(probe.run(line()), 5))
    assert at["clear"] < frames_at[2][-1]  # the barge-in landed while the probe was still saying line 2
    assert [(e.who, e.text) for e in transcript.exchanges] == [
        ("gus", "Hello."),
        ("probe", "My code is 4821."),
        ("gus", "Code 4821, got it."),
        ("probe", "Thursday please."),
        ("gus", "Your interview is on Tuesday."),
        ("gus", "Thursday at ten is open."),
        ("probe", "Ten works."),
        ("gus", "Booked."),
    ]
    assert frames_at[3][0] > at["answer"]  # line 3 went out only after Gus answered line 2
    tail, answer = transcript.exchanges[4], transcript.exchanges[5]
    assert tail.gap_ms is None  # the tail is not an answer, so it carries no gap
    # The answer's gap runs from the probe's last frame of line 2 to Gus's first frame after it: the quiet.
    expected_ms = (at["answer"] - frames_at[2][-1]) * 1000
    assert answer.gap_ms is not None and abs(answer.gap_ms - expected_ms) <= 25
    assert len(transcript.onset_gaps_ms) == 3 and transcript.onset_gaps_ms[1] == answer.gap_ms
    assert transcript.clears == 1


def test_score_checks_each_probe_turn_against_what_gus_said_next() -> None:
    case = parse_case(
        {
            "id": "p1",
            "title": "t",
            "kind": "boundary",
            "channel": "voice",
            "turns": [
                {"user": "My code is 4821.", "checks": [{"spoken_matches": "4821"}]},
                {
                    "user": "Am I a strong candidate?",
                    "checks": [{"spoken_not_matches": "(?i)strong"}, {"spoken_matches": "(?i)evaluate"}],
                },
            ],
        }
    )
    transcript = ProbeTranscript(
        exchanges=[
            Exchange("gus", "Hello.", 0),
            Exchange("probe", "My code is 4821.", 1),
            Exchange("gus", "Code 4821, got it.", 2, 600),
            Exchange("probe", "Am I a strong candidate?", 3),
            Exchange("gus", "I don't evaluate people.", 4, 700),
        ]
    )
    assert score(case, transcript) == []
    transcript.exchanges[-1] = Exchange("gus", "You seem strong.", 4, 700)
    failures = score(case, transcript)
    assert len(failures) == 2 and "matched 'strong'" in failures[0]


def test_a_probe_holding_the_auth_token_opens_the_stream_with_a_token_for_its_call() -> None:
    from candidate_line.telephony.app import stream_token_ok

    sent: list[dict] = []

    async def send(m: dict) -> None:
        sent.append(m)

    async def nothing():
        return
        yield

    for auth_token in ("12345", None):
        sent.clear()
        probe = ProbeSession(
            send,
            ScriptedTranscriber(),
            FakeSpeaker(),
            [],
            stream_sid="probe-CL-001",
            silence_ms=60,
            reply_timeout_s=0.2,
            real_time=False,
            auth_token=auth_token,
        )
        asyncio.run(probe.run(nothing()))
        [start] = [m["start"] for m in sent if m["event"] == "start"]
        assert start["callSid"] == "probe-probe-CL-001"
        if auth_token:
            assert stream_token_ok(auth_token, start["callSid"], start["customParameters"]["token"])
        else:
            assert "customParameters" not in start
