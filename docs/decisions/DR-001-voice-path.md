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

A turn runs from the end of the caller's speech to the first audio byte sent back. Both arms are measured the same way, from a Twilio call recording (the gap between the caller's last word and the reply), since arm B runs unmodified. The latency budget is set first, by James: ____ ms. Five scripted calls per arm give a median from a handful of turns, not a distribution, and every number reported says so. If Sunday cannot measure B, this record says so.

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
| Probe lines spoken, in ten probe calls | | | (a): B must be zero |
| Median turn in ms (n turns, from five scripted calls) | | | (b): B at least 500 ms faster |
| Cost per five-minute call, with each rate's read date | | | (c): B within 2x |
| Verdict | | | |

Raw rows: `bakeoff/2026-11-01.csv`.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
