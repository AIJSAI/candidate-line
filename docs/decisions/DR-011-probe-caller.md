# DR-011: The probe caller

Status: DRAFT
Built: pre-built (PREBUILT.md row 10); the cases it plays are written live
Commit: (filled when the item lands)

## What it is

A scripted synthetic candidate that talks to the line as speech, brings back a transcript of both sides with the turn gaps, and scores Gus's words with the same checks as the eval runner. An edge case is tested as audio through the whole path, not only as text.

## The decision

- **The probe plays Twilio's side of the media stream** (`candidate_line/probe/session.py`): it opens the stream, waits for Gus's greeting to end, speaks each scripted line as 20 ms mu-law frames of a Polly voice in real time (Joanna, so the two voices are never confused on a recording), returns each `mark` after "playing" the audio it closes, honours `clear`, and transcribes Gus with the same Transcribe adapter the line uses. "Gus has finished" means audio arrived since the probe last spoke and then nothing for 700 ms.
- **It measures the turn gap in-process:** the silence between the probe's last frame and Gus's first media byte, per reply, which is DR-001's measurement without a recording; the recording method stays for the bake-off's cross-check of this number.
- **Two ways to connect, one session class.** `direct` (`make probe CASE=... URL=ws://127.0.0.1:8000/media`) opens the line's `/media` WebSocket on the loopback or the tunnel: no phone number, no cost, runs on Wednesday's laptop in seconds, and is how the eval loop will play voice cases. `dial` (`scripts/twilio-dial-probe.sh`) places a real call from a second Twilio number to the line's number with TwiML that connects the call's media to the probe's own WebSocket, so the PSTN leg is in the measurement; it needs that second number, which is James's money call, and a public host for the probe.
- **Scoring reuses the eval checks.** A voice case is an ordinary case file with `channel: voice`; each turn's checks run against what Gus was heard to say after that line (`score` in `probe/direct.py`), with the same regular expressions and the same refusals for checks that are not evaluable yet (DR-010).
- **The cases it plays are written live.** None is committed today; the two tests drive it with scripted ears and fake mouths on both sides.

## The alternative rejected, and why

- **Playing recorded audio files through Twilio's `<Play>`.** No turn-taking: the probe must wait for Gus before each line, or the test measures nothing.
- **Dial-only.** Every run would cost two legs of a call and need two numbers and a tunnel before the first voice case could be played; direct mode costs nothing and exercises everything but the carrier.
- **Scoring Gus from the line's own transcript.** The line would be grading itself with the text it meant to say; the probe hears what Polly actually said and what Transcribe actually understood, which is what the candidate hears.
- **A separate scoring language for voice cases.** One case schema, one set of checks, one runner report.

## What would change the decision

The second number arriving (then `dial` runs the same cases and the two gap numbers, direct and dialled, are compared once); the direct probe's transcript disagreeing with the line's history on a case (then the mis-hearing is the finding, and a custom vocabulary or the `on_turn` normalizer is measured against it); the eval runner growing a `channel: voice` route (then `make eval` plays those cases through the probe automatically, with the line started for it).

## Evidence

- `uv run pytest -q tests/test_probe.py`, 2026-11-01: the probe drives a real `MediaSession` through two in-memory queues with scripted ears and fake mouths on both sides, two lines, two replies, two measured gaps and no `clear`; `score` passes a clean transcript and names the matched word on a dirty one.
- **First direct run against the local line, 2026-11-01 about 18:47 CT, real Transcribe and Polly on both sides, the line on the echo brain:** the probe heard the greeting at 1.28 s ("Acme candidate line. This is Gus."), spoke its first line at 3.47 s and heard the echo at 8.44 s with a turn gap of 775 ms; spoke its second line at 11.58 s and heard the echo at 15.85 s with a gap of 767 ms. Median gap 771 ms over two replies, no `clear`. That is the cascaded path's floor with no model in it: Transcribe's final, Polly, and the transport. The probe sent 927 media frames (its two lines plus silence) and received 18 (the line's three sentences in half-second chunks) and 3 marks.
- **The finding from that run:** the line's Transcribe heard "Hi, my code is ACME four eight two one" as "Hi, my coat is Acme 4,821", and the probe's Transcribe heard the echo the same way, so the smoke check for `4821|four eight two one` failed on the comma. Digits come back formatted ("4,821", "9:30"), and "code" at 8 kHz is fragile; the `on_turn` normalizer and the code-reading tool are written live with that in hand, and voice checks for codes normalize digits before matching.
- **Two more runs right after, same setup, 2026-11-01 18:49 CT:** median gaps 740 ms (797 and 682) and 780 ms (832 and 729), the stream closed with a close frame both times, no error in the line's log. The echo path transcribes the same words twice (the line hears the probe, the probe hears the echo), which is why the code degraded to "acne 48,821" on one run; a real reply is transcribed once.
- Earlier the same evening, three runs failed before the first good one, each a fact now built in: the probe spoke over the greeting because it judged "Gus finished" by arrival time instead of playback time (the line sends a sentence in a burst); both Transcribe streams closed after 15 s without audio, because a loopback stream carries no silence unless something sends it; and the stream ended with a reset instead of a close frame once the probe's keepalive kept sending after `stop`.
- First dialled run: (filled when the second number exists)

- **The probe's live ears, still open (2026-11-02 evening).** On some dialled calls (arm B's s1 at 17:30 CT, others earlier) the probe's own Transcribe stream dies about 13 s in: two feed timeouts 150 ms apart, then `BadRequestException: The request signature we calculated does not match`. The recording fallback supplies Gus's words, so the bake-off was unaffected. Two readings of the log, not yet decided by an experiment: the server rejected a frame (two senders interleaved on one event stream, which the two overlapping timeouts suggest) and the sends then blocked on a completed stream; or a timed-out send was cancelled mid-frame by `wait_for`, leaving a half frame, and the next frame failed its signature. Both are now instrumented in `speech.py`: the send is shielded so a timeout never cancels a CRT write, and an overlap counter logs a warning when two sends are in flight. The next dialled run with `LOG_LEVEL=DEBUG` says which it was. The starvation reading (Transcribe's 15 s silence limit) is ruled out: in Twilio-side mode the probe feeds every frame, silence included (`session.py`, the `has_speech` branch feeds before it `continue`s).

- **After a barge-in the probe mistakes the cleared line for an answer (2026-11-02, 21:50 CT, p02 on the committed head).** Gus's first reply ran long, the probe's question barged in, the line cleared, and the probe's wait-for-Gus-to-finish saw 1,200 ms of quiet and said its next line before Gus had answered the question at all; the line's superseded-turn rule then folded three probe lines into one turn and answered them together (PASS, 2,890 ms by the recording). The probe should wait for a new onset after a barge-in before it counts a reply as finished; one condition in `session.py`, for Tuesday. The ears stayed up for the whole call again.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
