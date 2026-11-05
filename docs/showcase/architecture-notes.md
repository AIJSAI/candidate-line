# Architecture page: where each box comes from

The page is `architecture.html` beside this file, drawn from this repository at commit 3919773 on 2026-11-03 (the cockpit's pages restyled in that commit).Line numbers in this file are as of that commit; a few lines moved on main afterwards, so open a file at that commit to match them exactly) and relaid on the same evening (titles in Title Case, one caption and at most two lines per box, a "Two Timing Rules" callout, a "Live" pill on a pre-built box whose live part is named after the colon). Each box below names the code or record that proves it. Paths are relative to that repository.

## Top row: the call coming in

- **Caller; The Phone Number (Twilio).** Twilio owns the number and calls the line's `/voice` webhook: `candidate_line/telephony/app.py:123-143`. The answer tells Twilio to open a two-way audio stream: `app.py:55-61`. Record: DR-005.
- **Front Address (CloudFront, WAF, a load balancer).** Since the evening of 4 November the line runs in a container on AWS: `infra/aws/candidate-line-stack.yaml` (the distribution, the web ACL, the load balancer open only to CloudFront's addresses), record DR-023. Before that it ran on a Mac behind a quick tunnel (`scripts/up.sh`, DR-005), which the page showed until this row was rewritten.
- **Front Door.** The signature check that proves a request came from Twilio: `app.py:41-45` and `app.py:126-132`. The audio WebSocket: `app.py:145-190`.
- **Speech to Text (Amazon Transcribe, streaming).** `candidate_line/telephony/speech.py:84-161`, `start_stream_transcription` at `speech.py:109`; built per call at `app.py:84`.
- **Two Timing Rules, first line (Gus waits a beat after the caller stops).** The grace window and the superseded turn: `candidate_line/telephony/media.py:36-46`. Record: DR-006.
- **Two Timing Rules, second line (if the caller talks over Gus, Gus stops).** Barge-in sends Twilio a `clear`: `media.py:316-322`, triggered at `media.py:190-191`.
- **Before Gus Thinks (live; "reads the off switch, fixes misheard words").** The `on_turn` hook: `candidate_line/hooks.py:19-20`, empty in `LineHooks` at `hooks.py:62-63`. Card 04 fills it with the misheard-word fixes (`prompts/04-tools-and-persona.md:15`), card 06 with the kill switch (`prompts/06-tiers-and-observer.md:8`).
- **Gus's Brain.** One turn: `candidate_line/turn.py:59-77`, called by the phone at `media.py:251`. The provider switch: `candidate_line/brain/provider.py:295-301`. Haiku 5.5 on the Anthropic API is the default: `candidate_line/settings.py:49` and `settings.py:65`. The Bedrock spare, Haiku 4.5: `settings.py:64`, `provider.py:109-170`. Record: DR-003.
- **Call Record and Recruiter's Cockpit captions.** The store is one SQLite file on the container's volume (EFS, DR-023) and the cockpit runs on the container's loopback, reached through the operator's SSM port-forward (`make cockpit-forward`).
- **Persona (the tag inside Gus's Brain).** Built the evening of 4 November: `candidate_line/persona.py` holds the brief, the fixed lines and the FAQ index. Record: DR-019.
- **Gus's Tools (live; the six list items are the six tool names, in plain words: Verify the caller, List open slots, Book a slot, Answer from the FAQ, Hand off a move, Take a callback).** Built the evening of 4 November: `candidate_line/tools/actions.py` holds the six tools plus `end_call`, and the loop in `candidate_line/turn.py` runs them (DR-019); the brain's tool channel is `provider.py:21-46`. The six tool names come from `prompts/02-eval-cases.md:17`: verify_caller, list_open_slots, book_slot, move_slot, answer_question, request_callback. At one hour a move is a hand-off to the coordinator (the session's run plan (not in this tree), "At 60").
- **Synthetic Data (the inner box).** `data/candidates.yaml` (8 candidates), `data/slots.yaml`, `data/faq.md`. Record: DR-009; `PREBUILT.md` row 6.

## Bottom row: Gus's answer going out

- **Safety Filter (live).** The `before_speak` hook: `hooks.py:22-23`; what the caller hears is the hook's result: `turn.py:70-74`. Card 05 writes it: `prompts/05-guard-and-red-proof.md:3-12`.
- **Text to Speech (Amazon Polly).** `speech.py:164-185`; spoken one sentence at a time at `media.py:278-285`; built per call at `app.py:85`.

## Beside the call

- **Call Record (pill: Live, the wiring).** One SQLite file, text only, never audio: `candidate_line/traces/store.py:1-7`, path `store.py:22-24`. Numbers masked at `store.py:91`, a meta key named pin masked at `store.py:73-81`. The call row starts at `app.py:139-142` and ends at `media.py:150`. The per-turn spans are card 03's live wiring (`media.py:6-7`).
- **Recruiter's Cockpit (pill: Live, tiers, off switch).** Loopback only, 127.0.0.1:8001: `candidate_line/traces/cockpit.py:1-5`, `Makefile:44-45`. The list of calls: `cockpit.py:148-165`; one call: `cockpit.py:167-204`; the reply box: `cockpit.py:132-137` and its handler `cockpit.py:206-212`. The tier column and the kill switch are card 06; the override spoken on the next turn is built only at 90 minutes (the session's run plan (not in this tree), "At 60": no override typed from the cockpit, planned as DR-021, which was not written), so the pill no longer names it.
- **Hand-Off to a Person (pill: Live, when it posts).** A bounded queue with one worker thread: `candidate_line/escalation.py:109-115`. Slack when its webhook is set, else the on-screen `[hand-off]` log: `escalation.py:156-158`, `escalation.py:93-106`. The message template with caller and trace link: `escalation.py:27-34`, `escalation.py:60`. When it posts is card 06's tier rule.
- **Tests Without a Phone (pill: Live, the test cases).** The eval runner uses the same turn loop, persona and hooks: `candidate_line/evals/runner.py:1-10`, `runner.py:131`. Text mode: `candidate_line/text_mode.py:1-5`. The scripted test caller that dials in: `candidate_line/probe/dial.py:1-7`. The cases are card 02.
- **Sign-In and Keys.** IAM Identity Center with short-lived credentials and no long-lived key: `docs/decisions/DR-002-aws-sign-in-and-spend.md:9-18`. The line runs on the `candidate-line` profile: `scripts/up.sh:15`. API keys and the Twilio token come from the login keychain: `scripts/env.sh:4-5`.

## Built before the session, and planned for it

From `PREBUILT.md`: rows 1 to 12 and the list after the tag are pre-built; its last section lists what is built live (the spec, the cases, tracing, the tools and the persona, the guard, the tiers and the hand-off rule, the kill switch and the override log, the scorecard). At one hour, the session's run plan (not in this tree) lands card 06 (the tiers, the hand-off rule and the kill switch) only if card 05 is green by minute 50; otherwise it is described, so those three dashed parts may be said rather than shown.

- **Why the captions read this way.** "Before Gus Thinks" and "Safety Filter" carry the caption "Hook, filled live": the four hooks are pre-built shells (`PREBUILT.md` row 5, `candidate_line/hooks.py`) and only their bodies are built live (cards 04 and 05), so the orange box names the live part. The "Two Timing Rules" callout takes the grey fill because both rules are pre-built (`PREBUILT.md` row 3; `candidate_line/telephony/media.py:36-46` the grace window, `:316-322` the clear on barge-in). The footer makes card 06 conditional on the clock, as the session's run plan (not in this tree) "At 60" says.
