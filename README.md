# Candidate Line

A phone line for the job candidates of ACME, a fictional firm. A voice agent called Gus books a first-round interview, answers process questions from an FAQ and names the section, takes a callback request, and never evaluates a person. It was built with Claude Code from prompt cards, with every decision written down as it was made. All data is synthetic. No account, key or phone number is in this repository.

![The architecture: the phone path, the brain, the records and the cockpit](docs/showcase/architecture.png)

Grey boxes were built before the session, each with its commit date in `PREBUILT.md`. Orange boxes are what the session's cards build.

## Five Minutes, In This Order

1. `KICKOFF.md`: the brief, and the first message typed into Claude Code.
2. `AGENTS.md`: the rules every agent in this tree follows. `.claude/settings.json` lists the commands it may run without asking.
3. `PREBUILT.md`: what was built before the session, with the commit of each item and the tag `prebuilt-2026-11-03`.
4. `prompts/`: the seven cards, one per step, pasted into the session in order. Each ends with the open decisions it asks before it writes anything.
5. `docs/decisions/`: one record per decision, in the shape `DR-000` sets.
6. `candidate_line/` and `tests/`: the code and its tests.

## Run It

With `uv` installed (`brew install uv`; the project pins Python 3.12):

```
make test                       # the test suite, no account needed
BRAIN_PROVIDER=echo make text   # text mode with no account: Gus says back what you type; /quit ends it
make text                       # text mode on Claude Haiku 5.5; needs ANTHROPIC_API_KEY in the environment
make eval                       # the eval cases through the same turn loop the phone uses
```

The phone path (`make up`, `make dev`, `make probe-dial`) needs an AWS account for transcription and speech, a Twilio number, and an Anthropic key. None of those is here, and `docs/decisions/DR-002` says how the account was set up without a long-lived key in any file.

## How It Was Built

![How the build runs: plan, build, review, verify as a user, record](docs/showcase/how-i-build.png)

The picture is the system every build of mine runs under. In this repository it shows as: each change landed with its tests and its decision record; the pre-built list was declared before the session and tagged; the phone path was proven by a real call before anything was called done (`docs/decisions/DR-006`); and the choice of coding tool was itself a recorded decision (`docs/decisions/DR-014`). The pattern is close to the one the Claude Code team described for their own code review in October 2026, with one addition: a person walks the result the way a user would before it counts.

## The Pages

Everything made for the session is in [`docs/showcase/`](docs/showcase/README.md): the architecture above, [how I build](docs/showcase/README.md#how-i-build-one-change-from-plan-to-main), [the one-page version for a business lead](docs/showcase/README.md#the-candidate-line-for-the-business-lead) and [the recruiting lead's screen](docs/showcase/README.md#the-recruiting-leads-screen), each as a picture, a page and the notes that trace every line on it to a file in this tree. The pre-built list is [`PREBUILT.md`](PREBUILT.md); the decision records are in [`docs/decisions/`](docs/decisions/); the seven cards are in [`prompts/`](prompts/); the plan for the hour, minute by minute, is [`docs/room.md`](docs/room.md).

## The Session Of 4 November 2026

The tag `room-2026-11-04` marks the tree as it stood when the session opened. The hour went to a different question than the one this line was built for, so the files the cards write in the session (`spec.md`, the eval cases, `DR-016` onward, the persona, the guard) are not here: `candidate_line/persona.py` still holds the placeholder text mode runs on, and `evals/cases/` is empty. What you are reading is the setup as it stood at the door: the plumbing, the rules, the records and the cards.

## What Gus Must Never Do

The problem card in `prompts/01` sets the lines the session builds into the persona, the guard and the eval set: no score, ranking, opinion, comparison or predicted outcome about a caller; no answer to a process question from anywhere but the FAQ; never pass for a person. A person makes every judgment about a candidate; the line only books, answers and hands off.
