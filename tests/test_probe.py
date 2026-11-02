import asyncio

from candidate_line.brain import EchoBrain
from candidate_line.evals.schema import parse_case
from candidate_line.hooks import NoHooks
from candidate_line.probe.direct import score
from candidate_line.probe.session import Exchange, ProbeSession, ProbeTranscript
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
