# Candidate Line

![tests](https://github.com/AIJSAI/candidate-line/actions/workflows/ci.yml/badge.svg)

A phone line for the job candidates of ACME, a fictional firm, built on AWS: Amazon Transcribe for the ears, Amazon Polly for the voice, Claude for the conversation (Haiku 5.5 on the Anthropic API today, with Claude on Amazon Bedrock one environment variable away, `DR-003` says why), Twilio for the number, and IAM Identity Center for a sign-in with no long-lived key. A voice agent called Gus verifies a caller by application code and PIN, books a first-round interview slot, answers process questions from an FAQ and names the section he used, takes a callback request, hands a slot move to a person, and never evaluates anyone. The plumbing (the phone path, text mode, the tests, the eval runner, the trace store and the recruiter's cockpit) was built on 1 to 3 November 2026 and is declared in `PREBUILT.md`. The parts that decide what Gus says (the spec, the tools over the data, the persona, the guard, the tiers and the eval cases) were planned for a one-hour live session on 4 November that went to another topic, and were built the same evening after a test call with a valid code found the placeholder prompt refusing it; `spec.md` and the records from `DR-016` on say what was decided and why. On 5 November the line gained an outbound screening call, built from card 08 after James ruled its shape the same day (`spec.md` section 9, `DR-025`). All data is synthetic. No account, key or phone number is in this repository.

The author is James Shehan; "James" in the files is him. The tree was built with Claude Code from the numbered items in `KICKOFF.md`, with every decision written down as it was made; the seven cards in `prompts/` were written for the session and dry-run twice in scratch copies (`docs/decisions/DR-015`), and an eighth, card 08, was written on 5 November for the outbound call. The files call that live session "the room" or "the hour"; "the session" in this README means the same thing.

![The architecture: the phone path, the brain, the records, the cockpit and the outbound call](docs/showcase/architecture.png)

Grey boxes were built before the session, each with its commit in `PREBUILT.md`. Orange boxes were built on the evening of 4 November, each with its record. The blue band, the outbound call, was built on 5 November (`DR-025`).

## Five Minutes, in This Order

The records are long, so start here:

1. [`spec.md`](spec.md): what the line may do, what it must ask a person first, what it never does, and how each Never line is tested.
2. [`PREBUILT.md`](PREBUILT.md): what existed before the session, with the commit of each item, and what was built after.
3. [`docs/decisions/DR-001-voice-path.md`](docs/decisions/DR-001-voice-path.md): the rule written before measuring, the numbers, and why arm A was kept when the rule picked arm B.
4. [`docs/decisions/DR-019-tools-and-persona.md`](docs/decisions/DR-019-tools-and-persona.md): how a spoken request becomes a tool call over the data and comes back as speech, and the cite-or-refuse rule.
5. [`candidate_line/turn.py`](candidate_line/turn.py), [`candidate_line/tools/`](candidate_line/tools/) and [`tests/`](tests/): the one turn loop that the phone, text mode and the evals share, and the tools it runs.

`AGENTS.md` holds the rules every coding agent here follows; `.claude/settings.json` lists the commands it may run without asking. `KICKOFF.md` is the plan for the build days of 1 to 3 November, kept as it was written. Where it and a decision record disagree, the record is newer.

## The Outbound Call

An applicant who applied with consent is called back within minutes, inside the calling window. The call opens in Twilio's own voice, before the audio stream starts, and says first that the line is automated and transcribed. The applicant confirms the PIN they chose when they applied. Gus then reads the role's posted questions word for word, from `data/roles.yaml`, and after each answer says one fixed line, "Noted:" and the answer. When every posted requirement is met, Gus reads the recruiter's open interview times and books the one the applicant names. When one is not met, Gus says in fixed words what the posting asks for and when a recruiter will call, and the recruiter gets an email with a link to the answers on the cockpit, never the answers themselves. In this demo that email reaches the operator, who alone can open the cockpit (`prompts/08`, open decision 7).

The choice between those two endings is a gate, and the gate is code: one pure function, `candidate_line/tools/rules.py`, compares the applicant's own answer with the requirement the employer posted, one question at a time. It decides only whether the line offers an interview now or a recruiter calls back. It has no score, weight or ranking and never compares one applicant with another, and `book_slot` refuses in code until it says every requirement is met. It is never spoken as a judgment: every line after an answer is fixed and said by code, the same for every applicant, and no line says qualify, eligible, failed or passed. A person makes every hiring decision.

The dialler ships off (`OUTBOUND_ENABLED` is 0 by default). While the line is a demo it may call only the numbers on an allow-list, the probe's and the operator's, checked in code before every dial and again when the call is answered. It calls from 09:00 to 20:00, Monday to Saturday, in the applicant's own time zone, at most three times with one voicemail, at most 20 dials a day and one call at a time, and a "stop" on any call ends every later dial at once. The raw phone number lives in one file read only by the dialler and is deleted after 30 days, or at once on a stop or a deletion request; the answers are deleted after four years. The intake is signed with a timestamp and a nonce. Calling real applicants needs counsel's read and its own decision record first (`prompts/08`, open decision 2). The contracts, the spend and the security are in `docs/decisions/DR-025-outbound-screening.md`.

## Run It

With `uv` installed (`brew install uv` on a Mac, or the installer on uv's own site; the project pins Python 3.12):

```
make test                       # the test suite, no account needed (1,079 passed on 5 November)
make eval                       # the eval cases through the same turn loop the phone uses; needs ANTHROPIC_API_KEY
make text                       # text mode on Claude Haiku 5.5; needs ANTHROPIC_API_KEY in the environment
BRAIN_PROVIDER=echo make text   # text mode with no account: Gus says back what you type; /quit ends it
```

In text mode, try the synthetic candidates in `data/candidates.yaml`: "application code ACME-3233, PIN 9683" verifies as Hannah Haddad; then ask for a slot, ask how long the interview is, or ask Gus what he thinks of you. Or try an applicant of `data/applications.yaml` who calls in: "my code is ACME-2609 and my PIN is 7750" verifies as Ines, who applied for the warehouse role, and Gus goes on with that role's posted questions, as the outbound call would (spec 9.8). Bookings, callback requests, applications, answers and dials are written to `var/state.json` (`STATE_PATH`), beside the trace store, and never to `data/`; a raw phone number is written only to `var/contacts.json` (`CONTACTS_PATH`).

The phone path (`make up`, `make dev`, `make probe-dial`) needs an AWS account for transcription and speech, a Twilio number, and an Anthropic key. Since the evening of 4 November the line runs in a container on AWS: one Fargate task behind a load balancer and CloudFront, the store on EFS, the secrets in Secrets Manager, hand-offs by email through SES with SNS behind it (each note says who asked for what and when, what to do, and links the call on the cockpit; the confirmation email F3.1 promises a booked candidate is ACME's scheduling system's to send, outside this repository), and a budget action that fails the line closed past a spend threshold. The stack is `infra/aws/candidate-line-stack.yaml`, the steps are `scripts/deploy.sh` (`make deploy STEP=...`), the image is `make image` from the `Dockerfile`, the plan is `docs/deploy/PLAN.md` and the record is `docs/decisions/DR-023-the-line-in-a-container.md`. None of those is here, and `docs/decisions/DR-002` says how the account was set up without a long-lived key in any file. `make voice-regression URL=wss://<host>/media` plays every eval case through the deployed line's audio path, one case at a time, and scores each from the line's own trace store (`docs/decisions/DR-024-the-voice-regression.md`). The outbound call needs three more secrets in the login keychain (`make secret NAME=INTAKE_SIGNING_KEY`, then `OUTBOUND_ALLOWED_NUMBERS` and `TWILIO_LINE_NUMBER`); `make deploy STEP=secrets` copies them to Secrets Manager, and the stack step refuses to run until all three are there, because the task cannot start without them. Then:

```
make apply PIN=4321                    # a signed synthetic application to the line on this Mac (URL= for another); its fictional 555-01xx number is on no allow-list, so it is stored and never dialled
make apply PIN=4321 PHONE=probe        # the same for the probe's own number, which the allow-list holds
make probe-answer PUBLIC=https://<probe-host> WATCHED=1   # the probe applies for its own number and answers the line's call, a met screen and then a not-met one; it refuses to run without WATCHED=1
make dial-off                          # the dialler's own stop on the task; calls in go on
make dial-on                           # lifts it; OUTBOUND_ENABLED and the kill switch still decide
make forget CODE=ACME-dddd             # a deletion request: the application, its answers, its dials, its calls' traces and its number
```

The cockpit's `/applicants` lists the applications in the order they arrived, with no sort and no count by answer, and `/applicants/<code>` shows each posted question beside the answer the line recorded; `make scorecard` adds four outbound rows, each with its method and n (spec 9.14). The code, data and prose are under the MIT license (`LICENSE`); `docs/refs/` holds vendor material under its own terms.

## How It Was Built

![How the build runs: plan, build, review, verify as a user, record](docs/showcase/how-i-build.png)

The picture is how I run builds across my own repositories. Here only steps 1 and 8 show in full, my rulings and the real calls, with `AGENTS.md` rule 3 standing in for step 3; the pre-push hook, the AI review and the merge gate run in my other repositories; this one has CI for the linters and the tests since the evening of 4 November (`docs/decisions/DR-022`) and no pull requests. What this tree does show: each component landed with its tests and a decision record, and every fix after a live call is in a record's evidence; the pre-built list was declared and tagged before the session; the phone path was proven by real calls (`docs/decisions/DR-006`); the voice path was measured against a rule written first (`docs/decisions/DR-001`); and the guard was built against a test committed red (`docs/decisions/DR-020`). The pattern is close to the one the Claude Code team described for their own code review in October 2026 ([their write-up](https://claude.dev/blog/solving-code-review-at-anthropic/)), with one addition: a person walks the result the way a user would before it counts.

## The Pages

Everything made for the session is in [`docs/showcase/`](docs/showcase/README.md): the architecture above, [how I build](docs/showcase/README.md#how-i-build-one-change-from-plan-to-main), [the one-page version for a business lead](docs/showcase/README.md#the-candidate-line-for-the-business-lead) and [the cockpit redesigned for the recruiting lead](docs/showcase/README.md#the-cockpit-redesigned-for-the-recruiting-lead), each as a picture and as a page; three of the four have notes that trace every line on them to a file in this tree, at the commit the notes name. The pre-built list is [`PREBUILT.md`](PREBUILT.md); the decision records are in [`docs/decisions/`](docs/decisions/); the eight cards are in [`prompts/`](prompts/).

## The Session of 4 November 2026, and the Evening After

The tag `room-2026-11-04` marks the tree as it was when the session opened: the plumbing, the rules, the records and the cards, with a placeholder prompt that carried only the rule never to evaluate a person. The hour went to another topic, so nothing was built in it. At 16:26 CT a test call with a valid code and PIN showed the placeholder asking again for the code the caller had just given. The same evening the seven cards' work was done in order and is in this tree: `spec.md` (DR-016), the eval cases and the first baseline (DR-017), the spans from the turn loop into the store (DR-018), the tools over `data/` and the persona (DR-019), the guard with its red-proof (DR-020), and the tiers, the hand-offs and the kill switch (DR-021). The scorecard (card 07) and CI for the tests followed the same evening (DR-022), and then the line itself went into a container on AWS (DR-023). The decisions the cards left open for the room were taken by the author and are marked in `spec.md`. Measured that evening: 36 eval cases pass on the live brain with a median brain time of 1,438 ms over 64 model turns and 0.00023 USD a call, on the baseline written after the review's fixes (`DR-017`); a probe call through Transcribe and Polly on the live line ran a median turn gap of 2.6 s over four replies, over the 2,000 ms budget of `DR-001` (that run is not in a record; the probes through the container later that evening are in `DR-023`).

## The Build of 5 November 2026

James ruled the outbound call's shape on 5 November, with the gate in code, and at 09:21 CT ruled on the rewording of Never 1, the new Never 7 and the outbound lines under Never 3 and Never 5, which stand in `spec.md` section 5 (`DR-025`, "The decision"). Lane 0 wrote spec section 9, the record, card 08 and the synthetic roles and applications; three lanes built the tools and the gate, the intake and the dialler, and the ledger, the cockpit, the scorecard and the stack, and were merged the same day. At this commit the suite is 1,130 tests and all of them pass (`uv run pytest -q`). The sixteen outbound eval cases, CL-041 to CL-056, entered `evals/cases` under the rule 4 amendment in `AGENTS.md`. The line's first two outbound calls were placed the same afternoon to the probe's own number through the deployed container, one met and booked, one not met and handed off to a recruiter by email; `DR-025`'s evidence records both calls turn by turn, and the seven eval runs behind the baseline.

## What Gus Must Never Do

`spec.md` section 5, held by the persona, the guard and the eval set: no score, ranking, opinion, comparison between people or predicted outcome about anyone; no answer to a process question from anywhere but the FAQ; never pass for a person, and on the outbound call say it is automated before anything else; never say a PIN aloud; never act for an unverified caller, and on the outbound call say nothing from the record but the applicant's first name before the PIN matches; never move a slot himself; never tell an applicant they do not qualify, failed or are out, and never close an application. The line's one check is the outbound gate, code comparing an applicant's own answer with a requirement the employer posted, and it is never spoken as a judgment. A person makes every hiring decision; the line only books, answers, asks the posted questions and hands off.
