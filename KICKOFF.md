# Candidate Line: kickoff

Written Sunday 2026-11-01, 12:17 PM CT (18:17 UTC), so a fresh Claude Code or Codex session can start the build today. Read it in full before the first command. The plan it comes from is James's own (section 8 says where it lives); this file carries only what the repository needs, in neutral words.

## 1. What this is

Candidate Line is a phone line for the job candidates of ACME, a fictional engineering-services firm of about 400 people hiring about 30 roles at once. Its voice is Gus: dry, unhurried, and automated, which he says in his first sentence. He verifies a caller by application code and PIN, books or moves a first-round interview, answers process questions from the firm's FAQ and names the section he used, takes a callback, and hands everything else to a person. The line never evaluates a person: no score, ranking, opinion or predicted outcome, ever. The function is real; the humor is in the persona, always at Gus's own expense ("I do calendars. Opinions about people are above my pay grade, and I don't have a pay grade."). It runs on AWS Bedrock (the live turn later moved to the Anthropic API, DR-003). It is built for a one-hour live build session on 2026-11-04, in which the people in the room may change the requirements mid-way. What exists before that session is plumbing and one measurement, declared in `PREBUILT.md`; everything that decides anything about a caller is built in the room. ACME is a placeholder until James names the firm and checks the name against real firms, and Gus's name and lines are his to change. All data is synthetic.

## 2. Rule 1: the learning rule

James must be able to explain every pre-built component, and every engineering, prompting and guardrail decision inside it, in his own words and under questioning. Building it is not enough: this rule is how the build teaches him. It is the first rule of this repository, it binds every session and every coding tool working here, and it outranks speed.

**Pace (his ruling of 2026-11-01):** the session runs the mechanical commands itself and narrates each in one line; it stops to ask James only at a real decision (anything that earns a decision record), at anything that spends money or touches one of his accounts (AWS, Twilio, model access, a subscription), and at anything that could not be undone. The rule is that James understands every decision. He does not have to approve every command.

1. **A decision record for every pre-built component.** `docs/decisions/DR-NNN-<slug>.md`, from the template in `docs/decisions/DR-000-how-decisions-are-recorded.md`: what it is, the alternative rejected, why, what would change the decision, and the one-line "say it like this". It is written inside the block that builds the component, before the block closes.
2. **A teach-back at the end of every build block.** James explains the component closed book, in his own words, as if to a reviewer, in about two minutes; the session interrupts once or twice ("Wait, who decides that?"). The session grades each point right, partly or wrong against the code, with file and line references (or the exact command, for account and CLI work), writes the "say it like this" line into the record in his words as corrected, and logs every miss as a card in `docs/learn/cards.yaml` for the next day's review. The format is in `docs/learn/README.md`.
3. **Teach while doing.** Before each command or diff, the session says in a sentence or two what it does and why, and waits for James's approval. At each real choice it first asks which option James would pick and why, then gives its own view and the alternative it rejects. A persona line, a refusal, a lexicon entry or a tier boundary is explained the way a module is.
4. **Each day starts with a review** of the previous day's cards: one question at a time, no hint, his confidence from 1 to 3.
5. **Before the session, the review covers the whole `PREBUILT.md` list**: at least one question per row, whatever a card's box.
6. **Each build day ends with a receipt**: the tutor skill's receipt mode writes it into the private notebook (section 8), and its three questions join `docs/learn/cards.yaml`, so one deck holds the build.
7. **Scope.** The rule governs the build days, Sunday to Tuesday. In Wednesday's live session, records are written as decisions land, and teach-backs and cards wait until afterward.

## 3. Decided, and the one open decision

**Decided** (James's rulings of 2026-10-31 and the plan's standing choices):
- **AWS Bedrock is the platform.** Claude Haiku 5.5 on the live turn, because the caller is waiting; Claude Sonnet 5.5 only for the callback summary nobody waits on; Amazon Nova 2.5 Sonic as the speech-to-speech arm. Region us-east-1, with us-west-2 the spare.
- **A voice agent with a story**, which callers in the room call from their own phones. The story runs: the problem, the setup, the execution, the prompts pasted, the output, they talk to it, and a little observability.
- **The CLI, not the consoles**, wherever the CLI can do the job. Any console step taken (model access, turning on IAM Identity Center) is declared.
- **Synthetic data only.** Nothing from James's employer, in any form.
- **The voice path has a prior, not a verdict**: cascaded (arm A), tested in Sunday's bake-off against a rule written before measuring (`docs/decisions/DR-001-voice-path.md`).

**Open: the coding tool, Codex CLI or Claude Code.** James reopened it on 2026-10-31. The method, from the plan's section 9, exactly: "Monday's scratch task decides it: run `prompts/01` through Codex and through Claude Code for twenty minutes each and keep the one whose approvals and trail read better on a shared screen; the other stays open in a second pane as the fallback. If Codex loses, its install hour and the sandbox check drop from Monday. Either way, say the why out loud at the start of Wednesday."
- `prompts/01` has to exist first, so Monday drafts it before the scratch task, function-neutral.
- The scratch task runs in a throwaway repository on a different function, so no `spec.md` lands here before Wednesday.
- For the tool that wins, two checks (plan section 3.3): whether it reads `AGENTS.md` on its own (if not, it is pasted at the start), and whether its sandbox lets a command reach Bedrock (if not, James runs `make eval` and `make gate` in his own pane, and `AGENTS.md` tells the tool to ask him).
- Codex runs in its git-folder default, workspace-write with on-request approvals; Claude Code runs with approvals on. Neither ever runs with approvals off.
- Whichever loses, Claude Code or Codex, stays open in a second pane as the fallback. The record is `docs/decisions/DR-014-the-coding-tool.md`.

## 4. Today, Sunday 2026-11-01

Clocks fell back at 2 AM today: Central is UTC-6 and Pacific UTC-8. As listed, the day is about 12.8 hours: Saturday's 1.3 carried over (skip any item already done), the plan's 7.5 for Sunday (section 7) and the 4.0 its section 3.9 added. If it runs long, cut in the order at the end of this section, never from the never-cut list. Seen on this Mac on 2026-11-01: `uv`, `python3.12`, `aws`, `codex`, `claude` and `cloudflared` are on the PATH; no sign-in state was checked.

The facts below were read on 2026-10-31 by the plan's writers. Re-read any fact before saying it aloud, save the page dated in `docs/refs/`, and say the date.

Each item names the decision it forces and where its record goes. Each block ends with a teach-back (Rule 1).

### Block 1: accounts and the first Bedrock call (1.0, carried from Saturday)

- [ ] **1. AWS CLI sign-in with no long-lived key in a file** (0.4 with item 2). IAM Identity Center through `aws configure sso` and `aws sso login`, so the CLI holds only short-lived session credentials; anything that must be stored lives in 1Password. If Identity Center is not on yet, turning it on is a console step: take it and declare it. The sign-in's permissions include the AWS Marketplace subscribe actions, since Claude on Bedrock is billed through AWS Marketplace (the Haiku 5.5 model card; [inference], check it on the page). Done when `aws sts get-caller-identity` succeeds on the named profile.
  *Forces:* the sign-in method against the rejected alternative (an access key in `~/.aws/credentials`), the profile name, the permission set.
  *Record:* `docs/decisions/DR-002-aws-sign-in-and-spend.md`. No account id, start URL or credential is ever copied into this repository.
- [ ] **2. Budget alarm.** An AWS Budgets alarm, set from the CLI (`aws budgets create-budget` with a notification).
  *Forces:* the cap, which is James's money call, and where the alarm alerts.
  *Record:* DR-002, with the cap and the alert channel, never an address.
- [ ] **3. Model access for Claude Haiku 5.5 and Amazon Nova 2.5 Sonic**, and Claude Sonnet 5.5 for the summary (0.5 with item 4). `aws bedrock list-foundation-models` for Anthropic and Amazon; access requested for the three (one console step if access needs it, declared); `aws bedrock list-inference-profiles` for the exact Claude ids. To confirm: Haiku 5.5 has no In-Region endpoint in us-east-1 or us-west-2 and is reached through the US geo profile `us.anthropic.claude-haiku-5-5` (routing to us-east-1, us-east-2 and us-west-2) or `global.anthropic.claude-haiku-5-5`; Nova 2.5 Sonic is `amazon.nova-2-5-sonic`, in-Region only (us-east-1, us-west-2, eu-north-1, ap-northeast-1), with no geo or global profile. Open check: whether Sonnet 5.5 is on Bedrock in us-east-1.
  *Forces:* the model id per job, the region, and the fallback profile for a throttle.
  *Record:* `docs/decisions/DR-003-models-and-regions.md`; dated copies of both model cards in `docs/refs/`.
- [ ] **4. The first Bedrock call from the CLI.** One `aws bedrock-runtime converse` call to Haiku 5.5 through the US geo profile, then the same with thinking off and with effort low (Haiku 5.5 thinks by default with effort medium; the AWS model card says Bedrock can turn thinking off and set effort from low to max). If Converse does not pass the setting, try the Messages API on bedrock-runtime, which the card also lists. Then one Polly clip from the CLI (0.1), never committed.
  *Forces:* Converse or the Messages API for the live turn; thinking off or effort low.
  *Record:* DR-003, with the command and the latency seen.
- [ ] **Teach-back:** DR-002 and DR-003.

### Block 2: the phone (1.0)

- [ ] **5. Twilio upgraded, a number, a tunnel, and a webhook to a hello line.** The upgrade is James's money call. A cloudflared tunnel to a FastAPI webhook that answers with one spoken line. Facts to confirm: the stream verb opens a bidirectional stream of base64 `audio/x-mulaw` at 8000 Hz, and a `clear` message empties buffered audio. The one-bidirectional-stream-per-call limit and the trial account's verified-numbers limit are not on that page: read them on Twilio's `<Stream>` TwiML page and its free-trial page, and save both dated, before saying either. In the room it is "the stream verb".
  *Forces:* the stack (Python 3.12 under uv, because `audioop`, the simplest mu-law codec, left the standard library in 3.13; FastAPI and uvicorn for the webhook and the media-stream WebSocket); a quick tunnel or a named tunnel whose hostname never changes, which decides Tuesday's re-point drill; where the Twilio credentials live (1Password and the environment).
  *Record:* `docs/decisions/DR-004-stack.md` and `docs/decisions/DR-005-telephony-and-tunnel.md`. The phone number and account ids stay out of every file.
- [ ] **Teach-back:** DR-004 and DR-005.

### Block 3: arm A, cascaded (2.5)

- [ ] **6. Arm A end to end, with an echo brain.** The media stream in; mu-law to PCM (Transcribe streaming takes PCM, FLAC or Ogg Opus, not mu-law); Transcribe streaming; an echo brain on Haiku 5.5 through Converse, streamed by sentence; Polly back as `mulaw` at 8000 Hz; barge-in sends `clear` when the caller speaks over Gus. The brain only echoes, so nothing that decides about a caller exists before Wednesday. Done when James calls from his phone, speaks, hears the echo, and cuts it off by talking.
  *Forces:* which Python client streams to Transcribe (an open check), how sentences are cut for Polly, and what counts as barge-in.
  *Record:* `docs/decisions/DR-006-arm-a-cascaded-audio-path.md`. Switch rule 2 (plan section 4.2): if arm A still cannot carry a whole phone call by Monday 6 PM CT, the plan's fallback in section 4.1 starts.
- [ ] **Teach-back:** DR-006.

### Block 4: arm B, speech to speech (1.5)

- [ ] **7. Arm B from the AWS sample, as-is.** Clone `aws-samples/sample-amazon-nova-sonic-twilio-integration` (MIT-0), read its README, run it unmodified as its own process, and make the first call from James's phone. Only its persona and settings change, and pointing the webhook at it selects the arm. It is never rewritten in Python this week, because AWS's Python example for the bidirectional stream uses the experimental `aws_sdk_bedrock_runtime` client, not boto3. Sonic sends its planned speech as `SPECULATIVE` text before the audio, then a `FINAL` transcript of what was actually spoken. Open checks: the sample's runtime, how its persona is set, and whether the 8-minute session limit documented for Nova 2 Sonic applies to Nova 2.5 Sonic.
  *Forces:* where the sample lives (beside this repository at a pinned commit, or vendored into it) and how the webhook switches arms.
  *Record:* `docs/decisions/DR-007-arm-b-sample-as-is.md`, with the sample's commit.
- [ ] **Teach-back:** DR-007.

### Block 5: the bake-off (1.5)

- [ ] **8. The rates and pages, read and dated** (0.5). Bedrock's Claude rates (Haiku 5.5 and Sonnet 5.5), Transcribe's per-minute rate, Polly's per-character rate and Nova 2.5 Sonic's rate, from the Bedrock pricing page and the service pages. Each page read is saved, dated, into `docs/refs/` with the two model cards and the two statute pages: New York City's automated employment decision tools page (nyc.gov, the DCWP), and 820 ILCS 42 (Illinois), whose official page failed to load on 2026-10-31. This weekend, also read the quota pages: Transcribe's concurrent streams, Polly's requests per second, and Bedrock's per-model, per-region token quotas. Open check: whether Illinois Public Act 103-0804 puts a notice duty on a line that never scores (unread).
  *Forces:* nothing new, but without the Sonic rate, rule (c) of DR-001 cannot be scored, and DR-001 says so.
  *Record:* `docs/refs/`, one file per page with its read date in the name, and an index of read dates in `docs/refs/README.md`.
- [ ] **9. The rule first, then the measurement** (1.0). Before the first measured call, commit: DR-001's rule as James confirms it, the latency budget (James sets it), the probe list `bakeoff/probes.yaml` (ten evaluative sentences Gus must never say), and the test persona prompt `bakeoff/persona.md`, which both arms run on a live model, not the echo brain. The commit's timestamp is the proof the rule came first. Then five scripted calls per arm and the ten probe calls, each turn measured from the Twilio call recording (the gap between the caller's last word and the reply), into `bakeoff/2026-11-01.csv`. Recordings stay local (git ignores them) and are deleted from Twilio once measured. [Suggestion] If item 13 is ready first, let the probe caller place the scripted calls, so both arms hear the same audio.
  *Forces:* B wins or A holds. Switch rule 1 (plan section 4.2): if the rule fires for B tonight, the plan's section 4.1 becomes the build.
  *Record:* DR-001's measurement table, filled; `bakeoff/`.
- [ ] **Teach-back:** DR-001: the rule, the method and the result.

### Block 6: text mode, synthetic data and the eval runner (1.0)

- [ ] **10. The text-mode REPL and four empty hooks.** A REPL over the same brain and tools (`make text`), and four hooks that do nothing yet: `on_turn`, `before_speak`, `on_silence`, `on_tool`.
  *Forces:* what each hook receives and returns, and whether `before_speak` can replace the text about to be spoken, since the guard and the observer plug in live on Wednesday.
  *Record:* `docs/decisions/DR-008-text-mode-and-hooks.md`.
- [ ] **11. Synthetic data, with its generating prompt committed.** Eight candidates with application codes and PINs (`data/candidates.yaml`), two weeks of interview slots, a three-page FAQ with section ids (`data/faq.md`), and a labelled baseline of past invites with their invite-to-booked hours, for the scorecard. Choose the firm's name now (0.1) and check it against real firms; until then it is ACME.
  *Forces:* the firm's name (James's call), the seed, the file shapes, and how the baseline is marked as synthetic.
  *Record:* `docs/decisions/DR-009-synthetic-data.md`; the prompt beside the data.
- [ ] **12. The eval runner with zero cases.** `make eval` prints 0 cases. Checks are deterministic (state, tool calls, cited section ids, the guard's lexicon, ticket tiers); a model judge is a spot check only. Boundary cases are an absolute bar; the rest are a regression gate against the committed baseline. `make gate` adds the tests and a cost line: cost per call within 20% of baseline. No case file exists before Wednesday.
  *Forces:* the case schema and what a check can assert.
  *Record:* `docs/decisions/DR-010-eval-runner.md`.
- [ ] **Teach-back:** DR-008, DR-009 and DR-010.

### Block 7: the probe caller (2.0, plan section 3.9)

- [ ] **13. A scripted synthetic candidate that calls the line.** A Polly voice reading a case script dials the Twilio number from a second process, and its transcript is scored against the same case file, so an edge case is tested as speech, not only as text. Pre-built and declared; the cases it plays are written live.
  *Forces:* which number it calls from and what that costs (a second number is a money call), where its transcript comes from, and how it feeds the eval runner.
  *Record:* `docs/decisions/DR-011-probe-caller.md`.
- [ ] **Teach-back:** DR-011.

### Block 8: the trace store and the cockpit's list view (1.5, plan section 3.9)

- [ ] **14. Where every call's record lands, and one page that lists the calls.** The store holds, per call, spans for transcription, model, tools and speech, with milliseconds, tokens, characters and seconds: text and metadata only, never audio, with caller numbers masked before they are written. The list view is one page over the store: the recruiter's cockpit, never a dashboard for candidates. Built live, not today: the spans written from the turn loop (tracing goes in before the first tool), the kill switch and the override log.
  *Forces:* the store and its schema, where masking happens, and how the page is served.
  *Record:* `docs/decisions/DR-012-trace-store-and-cockpit.md`; the store's path goes into `.gitignore`.
- [ ] **Teach-back:** DR-012.

### Block 9: the escalation webhook (0.5, plan section 3.9)

- [ ] **15. One line to a channel the recruiter already uses.** A Slack incoming webhook, or a text to the coordinator through the same number, carrying the trace link and the suggested next action; the recruiter's reply is logged back against the call, which closes the loop. Pre-build the webhook and the message template; the rule for which tier crossing posts is written live with the tiers.
  *Forces:* the channel; the webhook URL handled as a secret (1Password and the environment, never a file); a queue between the turn and the post, so a slow downstream never slows a turn.
  *Record:* `docs/decisions/DR-013-escalation-webhook.md`.
- [ ] **Teach-back:** DR-013.

### Block 10: ready for Monday (0.2)

- [ ] **16. Both coding tools signed in.** Codex (`brew install --cask codex` if missing, `codex login`, `codex login status`; a ChatGPT plan or an API key is James's call) and Claude Code.
  *Forces:* nothing today; Monday's scratch task decides the tool.
  *Record:* DR-014, on Monday.
- [ ] **17. Close the day.** The tutor's receipt for Sunday into the private notebook (section 8), with its three questions in `docs/learn/cards.yaml`; each landed row of `PREBUILT.md` filled with its commit date; switch rule 1 checked.

**If the day runs long, cut in this order** (plan section 7):
1. Barge-in polish past a basic `clear` on new speech (0.5).
2. The bake-off shrinks to three calls per arm and five probes, with the n written into DR-001 (0.5).
3. Arm B's measurement: DR-001 then stands on documented facts and arm A's numbers, said plainly (1.5). Per section 3.9, arm B's measurement shrinks before the probe caller goes.

**Never cut:** the first Bedrock call, arm A on a real phone, text mode, synthetic data, the Twilio upgrade, and (on Tuesday) the screen setup.

## 5. Monday and Tuesday, in brief

**Monday 2026-11-02** (about 4.5 hours; plan section 7)
- [ ] The review of Sunday's cards, before anything else.
- [ ] The architecture study in the plan's section 7 (outside this repository).
- [ ] `prompts/01`, drafted function-neutral, then **the scratch task that decides the coding tool** (section 3 above; plan sections 9 and 3.3). Record: DR-014.
- [ ] **`AGENTS.md` and the seven prompt cards** drafted: one work item each, with acceptance criteria and its decisions left open; the function's specifics live only in `spec.md`, so a new function changes the spec, not the work items. The seven (plan section 3.8): 01 the spec from a five-line problem card; 02 the eval cases; 03 tracing; 04 the tools and the persona; 05 and 06 the guard with its red-proof, the tiers and the observer; 07 the scorecard. Record: `docs/decisions/DR-015-agents-md-and-prompt-cards.md`.
- [ ] Switch rule 2 at 6 PM CT (plan section 4.2). Teach-backs; the day's receipt.

**Tuesday 2026-11-03** (about 3.0 hours; plan section 7)
- [ ] The review of Monday's cards.
- [ ] Finish `AGENTS.md` and `prompts/01` to `07`; complete **`PREBUILT.md`** with every commit date; **tag `prebuilt-2026-11-03`** (plan section 3.4).
- [ ] **The failure drills**, once each (plan sections 7 and 4.3): kill the tunnel and go to text mode, then bring the tunnel back and re-point the Twilio webhook with one command (`make webhook`) or a named tunnel; switch Sonic to us-west-2 and Haiku to the global profile; switch from the chosen coding tool to the other.
- [ ] James's open answers (plan section 9) and the screen setup.
- [ ] Switch rule 3 at noon CT: if neither arm completes a phone call, text mode is the build (plan section 4.2). Teach-backs; the day's receipt.

**Wednesday 2026-11-04, morning:** the review of the whole `PREBUILT.md` list (Rule 1), then the hour before, as the plan's section 8 sets it out.

## 6. The rules of the room

From the plan's sections 3.4, 3.8 and 4.3.
1. **Pre-built is declared in `PREBUILT.md` and never presented as live.** It is shown at minute 2 with its commit dates. No hidden finished branch exists, and no spec, case, guard or persona file exists before Wednesday: "I planned the shape and drafted the decisions; the build, the tests and every change happen here."
2. **The spec's Never list binds every tool**: the chosen coding tool, the fallback, every agent and every script.
3. **Approvals on, never bypassed.** The approvals are part of the trail.
4. **The method is said out loud at the start**: why this coding tool; problem first; the spec, then evals before code; tracing before the first tool; a guard seen failing before it is trusted; a person can stop the line.
5. **A change arrives as a spec line first, then the eval case, then the code.**
6. **The switch is planned**: three minutes with no diff, or one work item failing twice, and the same prompt goes to the other tool, said aloud.
7. **Cut scope, never the proof**: rescheduling first, then the observer as a spoken design with its case left red, then the scorecard by hand. Never the eval, the guard, the trace or the handoff to a person.
8. **Every fact said aloud carries its read date.** No rate from memory.

## 7. The first message to type

Open a fresh session (Claude Code or Codex) in the repository root and type this, verbatim:

```
Read KICKOFF.md, AGENTS.md and docs/decisions/DR-000-how-decisions-are-recorded.md in full. Then start TODAY at item 1, the AWS CLI sign-in with no long-lived key in a file. Follow Rule 1: run the mechanical commands yourself and narrate each in one line; stop and ask me only at a real decision, at anything that spends money or touches one of my accounts, and at anything that could not be undone; at each real decision, ask me which option I would pick before you give yours. If aws sts get-caller-identity already succeeds on a named profile, tell me and move to the next unchecked item. When block 1 is done, write DR-002 and DR-003 from the DR-000 template, then run my teach-back: I explain closed book, you interrupt once or twice, grade each point right, partly or wrong against the commands we ran, write the say-it-like-this line into each record, and log my misses as cards in docs/learn/cards.yaml. Never copy an account id, a start URL or a credential into this repository.
```

## 8. Sources

The plan this build followed and the coding-tool notes live outside this repository, on James's own machine. Neither was opened in the session, and nothing from them is copied here beyond what the build needs. The learning side (teach-backs, reviews, receipts) runs from a private notebook, also outside this tree.
