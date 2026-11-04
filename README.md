# Candidate Line

A phone line for the job candidates of ACME, a fictional firm, designed so that a voice agent called Gus books a first-round interview, answers process questions from an FAQ and names the section, takes a callback request, and never evaluates a person. What runs today is the plumbing: a real phone path, a text mode, the tests, an eval runner, a trace store and a recruiter's page. Gus himself (the spec, the persona, the tools, the guard and the eval cases) was to be built live in a one-hour session on 4 November 2026 and was not, so text mode only repeats what you type and `make eval` finds no cases. All data is synthetic. No account, key or phone number is in this repository.

The author is James Shehan; "James" in the files is him. It was built with Claude Code from prompt cards, with every decision written down as it was made.

![The architecture: the phone path, the brain, the records and the cockpit](docs/showcase/architecture.png)

Grey boxes were built before the session, each with its commit in `PREBUILT.md`. Orange boxes are what the session's cards build, and they are the part that does not exist yet.

## Five Minutes, In This Order

The records are long, so start here:

1. `PREBUILT.md`: what existed before the session, with the commit of each item, and what landed after the tag `prebuilt-2026-11-03`.
2. `docs/decisions/DR-001-voice-path.md`: the rule written before measuring, the numbers, and why arm A was kept when the rule picked arm B.
3. `AGENTS.md`: the rules every coding agent here follows. `.claude/settings.json` lists the read-only commands it may run without asking.
4. `prompts/01-spec-from-problem-card.md`: one of the seven cards. Each names its files, its acceptance criteria and the questions it asks before it writes anything.
5. `candidate_line/turn.py` and `tests/`: the one turn loop that the phone, text mode and the evals share.

`KICKOFF.md` is the plan for the build days of 1 to 3 November, kept as it was written. Where it and a decision record disagree, the record is newer. The records are drafts until their teach-back is graded, which happens after the session, so their Status lines say DRAFT and their "say it like this" lines are empty.

## Run It

With `uv` installed (`brew install uv` on a Mac, or the installer on uv's own site; the project pins Python 3.12):

```
make test                       # the test suite, no account needed
BRAIN_PROVIDER=echo make text   # text mode with no account: Gus says back what you type; /quit ends it
make text                       # text mode on Claude Haiku 5.5; needs ANTHROPIC_API_KEY in the environment
make eval                       # the eval cases through the same turn loop the phone uses; none exist yet, so it reports 0 cases
```

The phone path (`make up`, `make dev`, `make probe-dial`) needs an AWS account for transcription and speech, a Twilio number, and an Anthropic key. None of those is here, and `docs/decisions/DR-002` says how the account was set up without a long-lived key in any file.

## How It Was Built

![How the build runs: plan, build, review, verify as a user, record](docs/showcase/how-i-build.png)

The picture is how I run builds across my own repositories. This one shows part of it: each change landed with its tests and a decision record; the pre-built list was declared and tagged before the session; the phone path was proven by real calls (`docs/decisions/DR-006`); and the voice path was measured against a rule written first (`docs/decisions/DR-001`). The pre-push hook, the CI, the AI review and the merge gate in steps 4 to 6, 9 and 10 run in my other repositories, not here: this one has no CI. The pattern is close to the one the Claude Code team described for their own code review in October 2026 ([their write-up](https://claude.dev/blog/solving-code-review-at-anthropic/)), with one addition: a person walks the result the way a user would before it counts.

## The Pages

Everything made for the session is in [`docs/showcase/`](docs/showcase/README.md): the architecture above, [how I build](docs/showcase/README.md#how-i-build-one-change-from-plan-to-main), [the one-page version for a business lead](docs/showcase/README.md#the-candidate-line-for-the-business-lead) and [the recruiting lead's screen](docs/showcase/README.md#the-recruiting-leads-screen), each as a picture, a page and the notes that trace every line on it to a file in this tree. The pre-built list is [`PREBUILT.md`](PREBUILT.md); the decision records are in [`docs/decisions/`](docs/decisions/); the seven cards are in [`prompts/`](prompts/); the plan for the hour, minute by minute, is [`docs/room.md`](docs/room.md).

## The Session Of 4 November 2026

The tag `room-2026-11-04` marks the tree as it stood when the session opened. The hour went to a different question than the one this line was built for (a strategy question about a different business), so the files the cards write in the session (`spec.md`, the eval cases, `DR-016` onward, the persona, the guard) are not here: `candidate_line/persona.py` still holds the placeholder text mode runs on, and `evals/cases/` is empty. What you are reading is the setup as it stood at the door: the plumbing, the rules, the records and the cards.

## What Gus Must Never Do

The problem card in `prompts/01` sets the lines the session builds into the persona, the guard and the eval set: no score, ranking, opinion, comparison or predicted outcome about a caller; no answer to a process question from anywhere but the FAQ; never pass for a person. A person makes every judgment about a candidate; the line only books, answers and hands off.
