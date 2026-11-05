# DR-024: The voice regression

Status: DRAFT
Built: after the session (2026-11-05), not pre-built
Commit: this commit

## What it is

`make voice-regression URL=wss://<host>/media [CASES=...]` plays every eval case through the deployed line's audio path with the direct probe, one case at a time, and scores each case's checks from the line's own trace store in the container, not from what the probe heard. Before each case it puts the live ledger back to a snapshot taken at the start, and at the end it restores that snapshot. The runner is `candidate_line/probe/regression.py`; what runs inside the task is `candidate_line/probe/in_container.py`; the report goes to `var/voice-regression.md`, with the probe's log beside it.

## The decision

- **Each check is read where its truth is.** spoken_matches and spoken_not_matches are read against the speech spans, the words the line handed to Polly. tool_called, tier and cites are read against the tool, tier and cite spans. All of them go through the eval's own `checks.evaluate` on a `TurnResult` built from the store, so a check means the same by voice as in text mode. state comes from the container's ledger after the call, or, for a line before the call's last booking or callback, is replayed from the snapshot and the call's tool spans. heard_matches is read against the transcribe spans.
- **Three verdicts, each with its reason.** PASS, FAIL or UNOBSERVABLE. UNOBSERVABLE is what the store cannot settle: a heard_matches pattern that holds a digit, because the store masks digits (spec section 5, Never 4); a spoken check whose digits a masked run could hide, found by rewriting the pattern so each digit also matches the mask and asking whether only the rewritten one matches; and a silence turn, because the probe holds no silence. A case fails only on a check the line could have passed. The probe's own hearing of that line is printed beside every unobservable spoken check, so a person can still read it.
- **One case at a time, each from the same ledger.** The snapshot is taken once, through `aws ecs execute-command` under the admin profile with the names `scripts/deploy.sh` uses for line-off. Before each case the ledger is put back to it; after each case the call's spans and every candidate's state are read. The run refuses to start when the kill switch is on, when a call row with no end started in the last ten minutes, or when a snapshot from an earlier run is still there. It stops, and leaves the ledger alone, the moment a real call row appears.
- **A store turn sits under the probe line it answers by time:** the last line the probe began before the turn's first final. The probe records its wall clock at its zero for this (`ProbeTranscript.started_unix`). A turn the line superseded lends its words to the next one and none of its tools, as on the phone (`media.py`). A line the phone answered in two turns is read as one: words joined, tools together, the highest tier.
- **The audio side stays the probe's.** The turn gap (the probe's last frame to the first frame of Gus's reply reaching it) and the time the greeting was heard are the probe's measurements, in the report beside the table.
- **The container code is shipped as source.** The image on the task predates this work, so the runner sends `in_container.py` as a compressed program to `python -c`. It opens the store read-only, writes the ledger beside and renames it in, and gives the file to var/'s owner, because the session runs as root and the line does not.
- **Two fixes on the way.** The probe's call id in the store is now `probe-<case id>`; the prefix was applied twice (`direct.py` passed `probe-<id>` as the stream sid and the session adds `probe-`). And the normaliser reads a comma-grouped digit run, the one line defect the first run found (CL-021; `candidate_line/tools/codes.py`).

## The alternative rejected, and why

- **Scoring from the probe's transcription**, as this morning's first run and DR-011 did. The probe cannot hear a tool, a tier or a citation, so those checks ended "pending" on every case. It mis-hears Gus ("Section F 2.1" for F2.1, "2 p.m." for 2 PM, "Bing" for Booking), so a spoken check failed on the probe's ears. And heard_matches compared the probe's hearing of its own words, which says nothing about the line. DR-011 rejected scoring from the line's own record because the line would be grading itself with the text it meant to say. That still holds for what the caller hears, which is why the probe's transcript and its gaps stay in the report. For whether the line decided and said the right thing, the store is the record, and the probe's ears add only noise. [inference]
- **Running cases in parallel**, two at a time as this morning. Two calls share one live ledger, so one case's booking or callback can change what another case reads, and two calls' hand-offs interleave in the operator's mail. It more than halves the wall time (10.3 minutes this morning against 22.7 for one at a time, both measured below); a result that depends on which case ran beside it is not worth the 12 minutes.

## What would change the decision

- Polly or Transcribe changing what a caller hears against what the line meant, such as a section id said wrong: then the probe's hearing becomes a check of its own, beside the store's.
- A field that keeps the code the line read back, unmasked because a code is not a secret: then the code read-back checks become observable.
- The probe learning to hold a silence: then CL-040's holding lines become observable.
- A test tenant in the container with its own ledger, or a per-run ledger file: then cases can run in parallel safely.
- This Mac's clock and the task's disagreeing by more than about a second: then turns are placed under lines by their words instead of by time.

## Evidence

- **The first run, 2026-11-05, 15:18:57 to 15:29:13 UTC (09:18 to 09:29 CT):** a shell script ran every case through the deployed line with the direct probe, two at a time, scored by the probe's own transcription. 18 of 36 cases passed and 18 reported failed checks, and the triage counted no line defect among them: four causes sit in the probe and the way it was run, and the fifth is a transcript shape the normaliser did not yet read. The five: (a) tool_called, state, tier and cites always fail by voice ("pending: the tool loop has not landed", "the tier rule has not landed", "cited nothing"), because the probe only hears audio; (b) spoken_matches failed on the probe's own transcription of Gus ("Section F 2.1" for F2.1, "2 p.m." for 2 PM, "Bing" for Booking); (c) heard_matches compared against the probe's transcription of its own speech; (d) two cases ran at once against one live ledger; (e) CL-021's words "I'm calling about application 3233 PI 9683" reached the line through Transcribe as one comma-grouped number (the store's final reads "application *,****,***." at confidence 0.971), which the normaliser did not split into a code and a PIN, so Gus asked for the code again. This commit's `codes.py` change reads that shape: eight comma-grouped digits with no code are the code and the PIN, and four right after a code are its PIN (tests in `tests/test_tools.py`). With the change, the proposed CL-041 (the same words as heard, in text mode) passed on one run (2026-11-05, Haiku 5.5, one model turn, 2,083 ms on the brain's clock, 0.00014 USD by `rates.py`); before it, the normaliser left "application 3,2339,683." as it was.
- **This work item's run, 2026-11-05, 15:59:17 to 16:22:01 UTC (09:59 to 10:22 CT), wall time 22.7 minutes:** `make voice-regression` against the deployed line, all 36 cases one at a time, scored from the container's store as above, the runner at commit 496ae3f plus this work item uncommitted. The image on the task predates this commit, so the line ran without the normaliser change. The ledger was put back to the snapshot at the end (no real call row appeared). n = 36 calls and 111 checks:

| Case | Verdict | Pass | Fail | Unobservable | Turn gap median |
| - | - | - | - | - | - |
| CL-001 | PASS | 3 | 0 | 0 | 2,639 ms |
| CL-002 | PASS | 5 | 0 | 0 | 3,044 ms |
| CL-003 | PASS | 2 | 0 | 0 | 2,507 ms |
| CL-004 | PASS | 4 | 0 | 0 | 2,900 ms |
| CL-005 | PASS | 6 | 0 | 0 | 2,764 ms |
| CL-006 | PASS | 3 | 0 | 0 | 3,906 ms |
| CL-011 | PASS | 1 | 0 | 0 | 2,956 ms |
| CL-012 | PASS | 1 | 0 | 0 | 3,518 ms |
| CL-013 | PASS | 1 | 0 | 0 | 2,984 ms |
| CL-014 | PASS | 1 | 0 | 0 | 2,974 ms |
| CL-015 | PASS | 1 | 0 | 0 | 2,994 ms |
| CL-016 | PASS | 1 | 0 | 0 | 2,900 ms |
| CL-017 | PASS | 1 | 0 | 0 | 3,030 ms |
| CL-018 | PASS | 1 | 0 | 0 | 3,898 ms |
| CL-019 | PASS | 1 | 0 | 0 | 3,008 ms |
| CL-020 | PASS | 1 | 0 | 0 | 3,226 ms |
| CL-021 | FAIL | 3 | 2 | 2 | 2,800 ms |
| CL-022 | PASS | 2 | 0 | 2 | 3,525 ms |
| CL-023 | PASS | 2 | 0 | 4 | 3,568 ms |
| CL-024 | FAIL | 4 | 3 | 0 | 2,860 ms |
| CL-025 | PASS | 8 | 0 | 0 | 3,527 ms |
| CL-026 | PASS | 7 | 0 | 0 | 3,435 ms |
| CL-027 | PASS | 3 | 0 | 0 | 3,226 ms |
| CL-028 | PASS | 3 | 0 | 0 | 3,487 ms |
| CL-029 | PASS | 3 | 0 | 0 | 3,326 ms |
| CL-030 | PASS | 3 | 0 | 0 | 3,925 ms |
| CL-031 | PASS | 3 | 0 | 0 | 3,464 ms |
| CL-032 | PASS | 1 | 0 | 0 | 2,814 ms |
| CL-033 | FAIL | 3 | 1 | 0 | 3,906 ms |
| CL-034 | PASS | 5 | 0 | 0 | 3,456 ms |
| CL-035 | PASS | 2 | 0 | 0 | 2,568 ms |
| CL-036 | PASS | 1 | 0 | 0 | 2,353 ms |
| CL-037 | PASS | 3 | 0 | 0 | 3,844 ms |
| CL-038 | PASS | 3 | 0 | 0 | 3,183 ms |
| CL-039 | PASS | 3 | 0 | 0 | 3,470 ms |
| CL-040 | UNOBSERVED | 0 | 0 | 2 | 2,436 ms |

  32 cases pass, 3 fail, 1 has no observable check (CL-040, two silence turns), 0 probe errors; of 111 checks, 95 pass, 6 fail and 10 are unobservable: 4 heard_matches patterns with digits (CL-021, CL-023), 4 spoken checks behind a masked code read-back (CL-022, CL-023), and CL-040's 2 silence turns. On the probe's clock: turn gap median 3,467 ms, worst 4,646 ms, over 66 replies in 36 calls; greeting heard at a median of 2,185 ms, worst 2,658 ms, over 36 calls; 1 clear. The turn gap runs from the probe's last frame to the first frame of Gus's reply reaching it, through CloudFront, so it is not DR-001's dialled number.
- **The three FAILs, each read from its spans (2026-11-05, after the run). All three are line defects or gaps; none was fixed in this work item beyond the normaliser already in it.**
  - CL-021 (tool_called and the code read-back): the line heard "I'm calling about an application *,****,***." (confidence 0.868), the same shape as this morning, and asked for the code again. Polly's Joanna saying the case's words, put through Transcribe on this Mac the same way, comes back as "I'm calling about application 3,2339,683.", which this commit's normaliser turns into "application code ACME-3233 PIN 9683". It needs a deploy to reach the line.
  - CL-024 (the second miss: tool_called, the callback offer, tier 3): the line heard "Sorry, PIN 2222." as "Sorry, ******." (confidence 0.583), in this run and this morning's alike. Put through Transcribe here, the same audio comes back as "Sorry, 102222.": the word PIN is heard as "10". With no PIN in the words, the model asked for the code again instead of checking the second pair. A gap in the line's hearing, the same class as CL-021; open.
  - CL-033 (spoken_matches "one business day"): the model wrote "I've asked the coordinator to call you back tomorrow after 3 p.m. about your notice period. They'll call within one business day." The two-sentence cap (`_spoken_cap` in `turn.py`, over `split_sentences` in `telephony/audio.py`) counts "p.m." as the end of a sentence, so it kept "...after 3 p.m." and "about your notice period." and cut the promise spec 7.2 requires. It shows only by voice, because Transcribe writes "p.m." and the model echoes it; text mode writes "PM". Open.
- **Found while reading the spans, not by a check:** a superseded turn's hand-off is posted and not taken back. In CL-033 and CL-034 the line answered the caller's first final, posted the callback or move hand-off, was superseded when the caller went on, and posted a second hand-off from the whole sentence; the duplicate check in `turn._hand_off` matches on the reason text, and the second reason carries more words. The operator got two emails for one request in 2 of the 7 hand-off cases, and the superseded hook recorded 0 effects undone. Superseded turns are common by voice: 16 lines in 12 of the 36 calls had one, because Transcribe splits a probe line into two finals. Open.
- `uv run pytest -q`: 489 passed on 2026-11-05 (462 before this work item, plus 19 for the regression in `tests/test_voice_regression.py` and 8 for the normaliser); `uv run ruff check .` and `uv run ruff format --check .` clean.
- **The three line defects fixed, 2026-11-05, in this commit** (`fix: the sentence splitter keeps abbreviations, one hand-off per request per call, and the PIN word heard as ten (DR-024)`). The image on the task predates it, so the line by voice is unchanged until a deploy and a rerun, and whether the model then checks CL-024's second pair is for that rerun. (1) CL-033: `split_sentences` in `candidate_line/telephony/audio.py` no longer ends a sentence at "a.m.", "p.m.", "e.g.", "i.e.", "vs." or a single capital initial, so `_spoken_cap` in `turn.py` keeps "They'll call within one business day." of the exact reply above, and Polly's by-sentence path in `media.py` and the guard read the same splitter. (2) The double hand-off: `turn._hand_off` keys its duplicate check on the call, the tool and the verified candidate, not the reason's words, so CL-033's ask and its carried ask post one hand-off, and a move and a callback on one call still post two. (3) CL-024: `normalise_transcript` in `candidate_line/tools/codes.py` reads a run of exactly six digits that starts with 10, or "ten" and four digits, as PIN and the last four when the words hold no code and no PIN word, so "Sorry, 102222." reaches the brain as "Sorry, PIN 2222."; an eight-digit comma-grouped run still goes to the code-and-PIN rule first. 16 tests added: the 13 that pin the defects failed on the code at 0accfd6 and pass now, and the 3 that pin what must not change pass on both. `uv run pytest -q`: 505 passed on 2026-11-05; `uv run ruff check .` and `uv run ruff format --check .` clean.
- 2026-11-05 10:48 to 10:51 CT: after the three fixes were deployed (image a5d0db1, stack updated 10:47), CL-021, CL-024, CL-033 and CL-034 were rerun by voice through `make voice-regression` on the deployed line: 4 of 4 pass, 23 checks with 19 pass, 0 fail and 4 unobservable (digit patterns behind the store's masking), turn gaps 3,584 to 4,210 ms median, 2.7 minutes wall, the ledger put back.

## Say it like this

> (a draft, until the teach-back) I score the phone regression from the line's own trace store, because the probe's ears mis-hear Gus and cannot see a tool or a tier, and I run the cases one at a time because they share one live ledger.

## Teach-back

(not yet)
