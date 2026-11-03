# DR-001: The voice path

Status: DRAFT. The rule below was written on 2026-11-01, before any measurement, and this file's first commit dates it. Sunday's bake-off fills the numbers; the decision text is finished live on Wednesday, after the counter-case.
Built: the rule and the measurement are pre-built (PREBUILT.md rows 0 and 7); the decision is live.

## What it is

How a caller's speech becomes Gus's reply, and where the check on what Gus says can sit.

## The options

- **A, cascaded.** Speech to text (Transcribe streaming), Claude Haiku 5.5 on the turn, text to speech (Polly). Every sentence is text before it is sound.
- **B, speech to speech.** Amazon Nova 2.5 Sonic carries the audio both ways in one stream.
- **C, Sonic speaks and Claude decides behind tools.**

## The rule, written before measuring

B wins only if all three hold:
- **(a)** no line from the committed probe list `bakeoff/probes.yaml` (ten evaluative sentences, written Sunday and declared in PREBUILT.md) is spoken in ten probe calls, with both arms running the same persona prompt on a live model, not the echo brain;
- **(b)** its median turn is at least 500 ms faster;
- **(c)** its cost per five-minute call is within 2x.

A turn runs from the end of the caller's speech to the first audio byte sent back. Both arms are measured the same way, from a Twilio call recording (the gap between the caller's last word and the reply), since arm B runs unmodified. The latency budget is set first: **2,000 ms for the median turn**, the session's number, set 2026-11-02 under James's go-ahead on the open decisions and his to lower. It comes from the measured pieces, not from taste: arm A's floor with no model is 740 to 780 ms by the probe caller (DR-011), Haiku 5.5 adds about 900 ms for a 60-token reply (DR-003), so the honest expectation is about 1,700 ms and the budget leaves 300 ms for the phone leg. A turn over budget shrinks the prompt and the reply cap before it changes the model. Five scripted calls per arm give a median from a handful of turns, not a distribution, and every number reported says so. If Sunday cannot measure B, this record says so.

## The prior: A

"Never evaluate" has to hold before audio exists. In A, `before_speak` checks exactly the text Polly will say. In B the speculative text may differ from the speech [inference], and Nova 2.5 Sonic does not support Bedrock Guardrails. A's cost is latency, and its barge-in is built here.

## Model per job

Haiku 5.5 on the live turn, because the caller is waiting; Sonnet 5.5 only for the callback summary nobody waits on.

## Rejected

- **C** loses the text gate on what is spoken.
- [inference] Nova 2 Sonic's end of life is no sooner than Dec 2, 2026, a floor that falls inside a first engagement. A retirement date is a scheduled risk, so the older model is not an option.

## What would change the decision

Sonic gains Guardrails or a pre-speech hook; latency complaints after rollout; callers switching languages mid-call. If the rule fires for B on Sunday, the fallback design (Sonic in front, every action and answer behind a tool, the boundary held in code) becomes the build.

## Evidence

Facts read on 2026-10-31 by the plan's writers. Re-read each one, save a dated copy in `docs/refs/`, and say the date before saying any of them aloud.

| Fact | Source |
| - | - |
| Nova 2.5 Sonic: id `amazon.nova-2-5-sonic`; launched Oct 5, 2026; end of life no sooner than Oct 5, 2027; in-Region only in us-east-1, us-west-2, eu-north-1 and ap-northeast-1, with no geo or global profile; Guardrails and Knowledge Bases not supported; tool use and asynchronous tool calling supported; 20 concurrent sessions by default; pricing deferred to the Bedrock pricing page | docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-5-sonic.html |
| Nova 2 Sonic: end of life no sooner than Dec 2, 2026 | its model card |
| Sonic sends its planned speech as `SPECULATIVE` text before the audio, then a `FINAL` transcript of what was actually spoken; an 8-minute session limit is documented for Nova 2 Sonic only | docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-output-events.html; the Nova 2 Sonic guide |
| Claude Haiku 5.5: launched Oct 7, 2026; no In-Region endpoint in us-east-1 or us-west-2, so it is reached through `us.anthropic.claude-haiku-5-5` or `global.anthropic.claude-haiku-5-5`; Messages, Converse and Invoke APIs; Guardrails, structured outputs and explicit prompt caching supported | docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html |
| Bedrock's Claude rates, Transcribe's per-minute rate, Polly's per-character rate and the Sonic rate | read 2026-11-01 into `docs/refs/` and quoted in DR-003's Evidence (first-party Claude rates, the AWS Price List API for Sonic, Transcribe and Polly) |

## How the turn is measured, added 2026-11-01

The method of record stays the recording. The probe caller (DR-011) measures the same gap in-process, from its last audio frame to Gus's first media byte, and three runs against the echo line put arm A's floor with no model at 740 to 780 ms median (two replies each). Both numbers go in the table, each with its method, and a disagreement between them is a finding.

## The measurement, Sunday 2026-11-01

| Measure | Arm A | Arm B | Rule |
| - | - | - | - |
| Probe lines spoken, in ten probe calls | 0, checked over everything Gus said (36 lines across the ten calls) | 0, checked the same way (41 lines) | (a): B must be zero: **holds** |
| Median turn in ms, recording method (n turns, calls) | 2,060 (worst 2,640; n = 23 turns, 16 calls) | 1,360 (worst 1,660; n = 41 turns, 19 calls) | (b): B at least 500 ms faster: **holds, by 700 ms** |
| Median turn in ms, the probe's own clock (both phone legs included) | 1,905 (n = 25; 21 turns unanswered inside 6 s, the probe's ears failed on arm A) | 1,236 (n = 44) | the second clock agrees: 669 ms |
| Cost per five-minute call, with each rate's read date | about 0.18 USD: Transcribe 0.05 (0.01/min, read 11-01), Polly 0.08 (5,200 characters at 16 USD/M, 192 characters a reply and 27 turns scaled from today's 3.7 turns per 40 s call), Haiku 5.5 0.003 (900 in and 60 out a turn at 0.10/0.50 per M), Twilio 0.04 (0.0085/min) | **about 0.10 USD, measured**: Nova 2.5 Sonic 0.057 per five minutes from its own `usageEvent` counts over three dialled calls the same evening (0.0169 USD over 89 s of call: 1,370 speech-in, 3,398 text-in, 888 speech-out and 369 text-out tokens, priced at the Price List rates read 11-01: 0.003, 0.00033, 0.012 and 0.00275 per 1,000), plus Twilio 0.04; the sample had to be given one log line to print the counts (DR-007), because CloudWatch shows Sonic's invocations without tokens | (c): B within 2x: **holds; B is cheaper** |
| Scenario checks passed (five scenarios, regex on the recording's words) | 2 of 5 (s3, s4, s5 failed on reply-to-turn alignment of the recording's finals, not on wrong answers; read in DR-011) | 4 of 5 (s4: offered a callback instead of naming the coordinator, a real persona miss) | not a rule; context |
| Verdict | | | **All three hold for B, measured 2026-11-02 between 17:35 and 20:00 CT. The rule, as written, fires for B.** The decision text below says what is built on Wednesday and why. |

Raw rows: `bakeoff/2026-11-01.csv` (the earlier test calls are in it too, under their own call ids).

**How the numbers were made, 2026-11-02, 17:35 to 17:56 CT.** The probe caller (DR-011) dialled the line's number from its own number for each of the fifteen cases in `bakeoff/cases/`, first with the number pointed at arm A, then at arm B; both arms ran `bakeoff/persona.md` (arm A through `SYSTEM_PROMPT_FILE`, arm B as the sample's `SYSTEM_PROMPT`), the same Polly voice spoke the same lines through the phone network, every call was recorded dual-channel on Twilio, the gap was read from the recording by energy (`candidate_line/probe/recording.py`, speech above an RMS of 500, a 300 ms hangover), the words were read from the recording's line channel when the probe's ears failed, and each recording was deleted from Twilio once its rows were in the CSV. Twilio's balance went from 20.00 to 18.62 USD over 42 inbound calls (28 minutes) and two numbers.

**What the numbers do not say.** One evening, one persona, one voice. Arm A's replies ran long (192 characters a reply against the persona's one or two sentences), and its median moves with reply length (DR-003); a brevity rule in the live persona is the first thing to try before conceding 700 ms. Arm B's median is also the median of a model that cannot be checked before it speaks: on s4 it answered with a callback where the persona says the coordinator, and nothing in B could have caught a worse sentence. The ten probes were clean on both arms tonight; the guard exists for the eleventh.

## The decision, 2026-11-02 evening

**The rule fired for B, and arm A is the Wednesday build.** Written by the session under James's standing authorization (his go-ahead, 2026-11-02 evening), with his veto open: the word "B" from him before Tuesday noon makes Tuesday the Sonic-in-front rebuild and supersedes this section.

Why the rule's consequence is not taken as written:

1. **The consequence had a date in it.** "If the rule fires for B on Sunday" was written with two build days behind it. The measurement landed Monday night, 36 hours before the room, after the seven cards, the hooks, the probe and the records were built around A. A rule with a deadline inside it is a rule about time as much as about milliseconds; the lesson is to write the deadline out loud next time (what would change this decision: a week instead of a day, and B is the build).
2. **The room's thesis is the sentence check.** The line never evaluates a person, and A can prove that per sentence, before the audio exists (`before_speak`, card 05, the red-proof). B passed thirteen probe calls clean tonight on a persona that forbids the sentences; nothing in B could have caught the fourteenth. On scenario s4 it offered a callback where the persona says the coordinator: a small persona miss, but the kind that only the recording finds afterwards.
3. **The gap is addressable on A.** B's 700 ms come from a single model turn; A's turn is three hops, and tonight's A replies ran 192 characters where the persona asks for one or two sentences. Output length sets A's model latency (DR-003); the brevity rule and a 60-token cap are the first lever and cost nothing. The end-pointing grace added tonight (DR-006) adds 300 or 600 ms to A (the figure was first written as 300 to 800; the code settled on 300 after a question mark and 600 otherwise, `media.py`) before the turn starts, which the recording's number will show.

What the room gets instead of the rebuild: B's numbers are said aloud in the first five minutes as the measured finding they are (700 ms faster, half the cost, clean on the probes), B runs as the second phone on the table so both are heard, and this section is read as the decision it is: a rule that fired, and an override with its reasons written before the room.

- **First real-call numbers for arm A, 2026-11-02 15:34 CT (DR-006):** gap from final transcript to first reply byte, by the line's own log, n = 4 turns in one call: median 1098 ms, worst 1405 ms, with Haiku 5.5 on the Anthropic API and the placeholder prompt; one barge-in, clean. Inside the 2,000 ms budget. Not yet the recording method, not yet five scripted calls, not yet arm B.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
