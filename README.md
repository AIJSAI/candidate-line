# Candidate Line

## If You Are Reading This Cold

Candidate Line is a phone line for the job candidates of ACME, a fictional firm: a voice agent, Gus, that books a first-round interview, answers process questions from an FAQ, and never evaluates a person. This tree holds the plumbing James built with Claude Code from 2026-11-01 to 2026-11-03 for a live build session on 2026-11-04; everything that decides anything about a caller is built in that session. All data is synthetic.

Read in this order: `KICKOFF.md` (the brief, and the first message typed into Claude Code), `AGENTS.md` (the rules every agent here follows; `.claude/settings.json` lists the commands it may run without asking), `PREBUILT.md` (what was built before the session, with commit dates and the tag `prebuilt-2026-11-03`), `prompts/` (the seven cards pasted in the session), `docs/decisions/` (one record per decision), then the code in `candidate_line/` and `tests/`.

The files the cards write in the session (`spec.md`, the eval cases, DR-016 to DR-022) are not in this tree; the tag `room-2026-11-04` marks it as it stood when the session opened.

With `uv` installed (the project pins Python 3.12): `make test` runs the tests with no account. `BRAIN_PROVIDER=echo make text` runs text mode with no account, and Gus says back what you type (`/quit` ends it). A plain `make text` speaks with Claude Haiku 5.5 and needs `ANTHROPIC_API_KEY` in the environment.

The phone path (`make up`, `make dev`, `make probe-dial`) needs an AWS account, a Twilio number and an Anthropic API key. None of those accounts, keys or numbers is in this repository.
