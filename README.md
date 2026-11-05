# Candidate Line

![tests](https://github.com/AIJSAI/candidate-line/actions/workflows/ci.yml/badge.svg)

A phone line for the job candidates of ACME, a fictional firm, built on AWS: Amazon Transcribe for the ears, Amazon Polly for the voice, Claude for the conversation (Haiku 5.5 on the Anthropic API today, with Claude on Amazon Bedrock one environment variable away, `DR-003` says why), Twilio for the number, and IAM Identity Center for a sign-in with no long-lived key. A voice agent called Gus verifies a caller by application code and PIN, books a first-round interview slot, answers process questions from an FAQ and names the section he used, takes a callback request, hands a slot move to a person, and never evaluates anyone. The plumbing (the phone path, text mode, the tests, the eval runner, the trace store and the recruiter's cockpit) was built on 1 to 3 November 2026 and is declared in `PREBUILT.md`. The parts that decide what Gus says (the spec, the tools over the data, the persona, the guard, the tiers and the eval cases) were planned for a one-hour live session on 4 November that went to another topic, and were built the same evening after a test call with a valid code found the placeholder prompt refusing it; `spec.md` and the records from `DR-016` on say what was decided and why. All data is synthetic. No account, key or phone number is in this repository.

The author is James Shehan; "James" in the files is him. The tree was built with Claude Code from the numbered items in `KICKOFF.md`, with every decision written down as it was made; the seven cards in `prompts/` were written for the session and dry-run twice in scratch copies (`docs/decisions/DR-015`). The files call that live session "the room" or "the hour"; "the session" in this README means the same thing.

![The architecture: the phone path, the brain, the records and the cockpit](docs/showcase/architecture.png)

Grey boxes were built before the session, each with its commit in `PREBUILT.md`. Orange boxes were built on the evening of 4 November, each with its record.

## Five Minutes, in This Order

The records are long, so start here:

1. [`spec.md`](spec.md): what the line may do, what it must ask a person first, what it never does, and how each Never line is tested.
2. [`PREBUILT.md`](PREBUILT.md): what existed before the session, with the commit of each item, and what was built after.
3. [`docs/decisions/DR-001-voice-path.md`](docs/decisions/DR-001-voice-path.md): the rule written before measuring, the numbers, and why arm A was kept when the rule picked arm B.
4. [`docs/decisions/DR-019-tools-and-persona.md`](docs/decisions/DR-019-tools-and-persona.md): how a spoken request becomes a tool call over the data and comes back as speech, and the cite-or-refuse rule.
5. [`candidate_line/turn.py`](candidate_line/turn.py), [`candidate_line/tools/`](candidate_line/tools/) and [`tests/`](tests/): the one turn loop that the phone, text mode and the evals share, and the tools it runs.

`AGENTS.md` holds the rules every coding agent here follows; `.claude/settings.json` lists the commands it may run without asking. `KICKOFF.md` is the plan for the build days of 1 to 3 November, kept as it was written. Where it and a decision record disagree, the record is newer.

## Run It

With `uv` installed (`brew install uv` on a Mac, or the installer on uv's own site; the project pins Python 3.12):

```
make test                       # the test suite, no account needed
make eval                       # the eval cases through the same turn loop the phone uses; needs ANTHROPIC_API_KEY
make text                       # text mode on Claude Haiku 5.5; needs ANTHROPIC_API_KEY in the environment
BRAIN_PROVIDER=echo make text   # text mode with no account: Gus says back what you type; /quit ends it
```

In text mode, try the synthetic candidates in `data/candidates.yaml`: "application code ACME-3233, PIN 9683" verifies as Hannah Haddad; then ask for a slot, ask how long the interview is, or ask Gus what he thinks of you. Bookings and callback requests are written to `var/state.json` (`STATE_PATH`), beside the trace store, and never to `data/`.

The phone path (`make up`, `make dev`, `make probe-dial`) needs an AWS account for transcription and speech, a Twilio number, and an Anthropic key. Since the evening of 4 November the line runs in a container on AWS: one Fargate task behind a load balancer and CloudFront, the store on EFS, the secrets in Secrets Manager, hand-offs by email through SNS, and a budget action that fails the line closed past a spend threshold. The stack is `infra/aws/candidate-line-stack.yaml`, the steps are `scripts/deploy.sh` (`make deploy STEP=...`), the image is `make image` from the `Dockerfile`, the plan is `docs/deploy/PLAN.md` and the record is `docs/decisions/DR-023-the-line-in-a-container.md`. None of those is here, and `docs/decisions/DR-002` says how the account was set up without a long-lived key in any file. `make voice-regression URL=wss://<host>/media` plays every eval case through the deployed line's audio path, one case at a time, and scores each from the line's own trace store (`docs/decisions/DR-024-the-voice-regression.md`). The code, data and prose are under the MIT license (`LICENSE`); `docs/refs/` holds vendor material under its own terms.

## How It Was Built

![How the build runs: plan, build, review, verify as a user, record](docs/showcase/how-i-build.png)

The picture is how I run builds across my own repositories. Here only steps 1 and 8 show in full, my rulings and the real calls, with `AGENTS.md` rule 3 standing in for step 3; the pre-push hook, the AI review and the merge gate run in my other repositories; this one has CI for the linters and the tests since the evening of 4 November (`docs/decisions/DR-022`) and no pull requests. What this tree does show: each component landed with its tests and a decision record, and every fix after a live call is in a record's evidence; the pre-built list was declared and tagged before the session; the phone path was proven by real calls (`docs/decisions/DR-006`); the voice path was measured against a rule written first (`docs/decisions/DR-001`); and the guard was built against a test committed red (`docs/decisions/DR-020`). The pattern is close to the one the Claude Code team described for their own code review in October 2026 ([their write-up](https://claude.dev/blog/solving-code-review-at-anthropic/)), with one addition: a person walks the result the way a user would before it counts.

## The Pages

Everything made for the session is in [`docs/showcase/`](docs/showcase/README.md): the architecture above, [how I build](docs/showcase/README.md#how-i-build-one-change-from-plan-to-main), [the one-page version for a business lead](docs/showcase/README.md#the-candidate-line-for-the-business-lead) and [the cockpit redesigned for the recruiting lead](docs/showcase/README.md#the-cockpit-redesigned-for-the-recruiting-lead), each as a picture and as a page; three of the four have notes that trace every line on them to a file in this tree, at the commit the notes name. The pre-built list is [`PREBUILT.md`](PREBUILT.md); the decision records are in [`docs/decisions/`](docs/decisions/); the seven cards are in [`prompts/`](prompts/).

## The Session of 4 November 2026, and the Evening After

The tag `room-2026-11-04` marks the tree as it was when the session opened: the plumbing, the rules, the records and the cards, with a placeholder prompt that carried only the rule never to evaluate a person. The hour went to another topic, so nothing was built in it. At 16:26 CT a test call with a valid code and PIN showed the placeholder asking again for the code the caller had just given. The same evening the seven cards' work was done in order and is in this tree: `spec.md` (DR-016), the eval cases and the first baseline (DR-017), the spans from the turn loop into the store (DR-018), the tools over `data/` and the persona (DR-019), the guard with its red-proof (DR-020), and the tiers, the hand-offs and the kill switch (DR-021). The scorecard (card 07) and CI for the tests followed the same evening (DR-022), and then the line itself went into a container on AWS (DR-023). The decisions the cards left open for the room were taken by the author and are marked in `spec.md`. Measured that evening: 36 eval cases pass on the live brain with a median brain time of 1,438 ms over 64 model turns and 0.00023 USD a call, on the baseline written after the review's fixes (`DR-017`); a probe call through Transcribe and Polly on the live line ran a median turn gap of 2.6 s over four replies, over the 2,000 ms budget of `DR-001` (that run is not in a record; the probes through the container later that evening are in `DR-023`).

## What Gus Must Never Do

`spec.md` section 5, held by the persona, the guard and the eval set: no score, ranking, opinion, comparison or predicted outcome about a caller; no answer to a process question from anywhere but the FAQ; never pass for a person; never say a PIN aloud; never act for an unverified caller; never move a slot himself. A person makes every judgment about a candidate; the line only books, answers and hands off.
