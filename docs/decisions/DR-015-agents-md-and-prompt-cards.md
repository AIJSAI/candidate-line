# DR-015: AGENTS.md finished, and the seven prompt cards

Status: DRAFT
Built: pre-built (PREBUILT.md row 14)
Commit: (filled when the item lands)

## What it is

The rules every coding tool follows in this repository, finished from Sunday's draft, and the seven prompt cards in `prompts/`, one work item each for Wednesday: the text to paste, the shape of the output, the acceptance criteria, the decisions left open for James, the files the tool may touch, and the teach-back that closes the block.

## The decision

The cards are **function-neutral**: none of them says what the line does for a caller. That lives in `spec.md`, which card 01 writes from a five-line problem card the room confirms, so a different function on Wednesday changes one file and not seven. Each card is a **closed scope**: it names its files (rule 3), and the tool stops when the work wants another. Each card **asks before it writes**: its open decisions are James's, put to him one at a time at the card's start, so the room hears the choice made. Each card **ends in a teach-back** (rule 1). The order is the dependency order of the build: spec, cases, traces, tools, guard, tiers, scorecard; cards 03 to 07 fill pre-built shells (the hooks, the store, the queue, the baseline) rather than create new surfaces, which is what keeps seven items inside ninety minutes.

`AGENTS.md` gained what the week taught: the keychain path for secrets (rule 7), the Anthropic API beside Bedrock in rule 8, rule 4 naming card 02 as its only exception, a rule 13 on measured numbers, the card table, the switch rule, and the coding-tool section pointing at DR-014.

## The alternative rejected, and why

- **One long prompt for the whole build.** Fewer pastes, but no stopping points, so no teach-backs, no per-item approvals and no clean switch to the fallback tool when one item stalls.
- **Function-specific cards.** Faster to write, since the acceptance criteria could name the FAQ and the slots. Rejected because the room confirms the function on Wednesday, and a card that assumes it would have to be rewritten on the shared screen.
- **Cards that decide the open questions themselves.** Quicker, but the open questions (the firm's name, the retrieval shape, the hold limit, the channel) are exactly the decisions the session is meant to show James making.
- **Leaving `AGENTS.md` as the Sunday draft.** The draft did not know the keychain path, the Anthropic provider or which card may touch `evals/`; a tool reading it would have asked, or guessed.

## What would change the decision

A coding tool that cannot read `AGENTS.md` on its own (then the file is pasted at the session start, DR-014). A card that takes more than fifteen minutes in the Tuesday dry run (then it splits, and the table here gains a row). A spec that needs a surface no card fills (then a card 08 is written live and declared as live).

## Evidence

- KICKOFF.md section 3.8 names the seven cards; the plan's section 3.3 names the two tool checks; both read 2026-11-02.
- `prompts/01` to `prompts/07` written 2026-11-02, 13:10 to 13:30 CT; `AGENTS.md` finished the same sitting.
- The pre-built shells each card fills: `candidate_line/hooks.py` (DR-008), `candidate_line/traces/store.py` and `cockpit.py` (DR-012), `candidate_line/escalation.py` (DR-013), `candidate_line/evals/` (DR-010), `data/baseline_invites.csv` (DR-009), `bakeoff/probes.yaml` (DR-001).
- The brevity rule in card 04 comes from the measured turns in DR-003 (output tokens set the latency; adaptive thinking spent a 120-token budget on three of five turns).
- The Transcribe findings card 04 writes into the persona ("code" heard as "coat", digits as "4,821") are from DR-006's live run.

## The timed dry run, 2026-11-02 evening

Each card was pasted, as the room will paste it, into a fresh coding agent (Claude Code's agent runtime, Opus 5.5) in a detached scratch worktree of this repository, with the session's draft answers standing in for James's and no pauses for approval. The worktree was discarded; only the defect list came into the repository, and every fix is a commit named in the table. The times are tool time alone: the room adds the questions asked one at a time, the reading aloud, and the approvals.

| Card | Wall clock | Result | What the room would have hit, and what changed |
| - | - | - | - |
| 01, the spec | 3.2 min, 24 tool calls | spec written, 396 words, gate green | the card named a record it could not write, a 400-word limit that took two trims, "no real firm" that read as no vendor names, and asked for a teach-back mid-session; fixed in c872d82 |
| 02, the eval cases (first pass) | 6 min, 20 calls | 32 cases loaded; no green possible | `spec_ref` and `note` refused by the schema; the README's id format disagreed; **the gate could not be green until card 06** because a check on an unbuilt component counted as a failure; the echo brain can never be green; a baseline from it meant nothing; the runner always spoke with the placeholder prompt and empty hooks, so **card 04's persona and card 05's guard would never have reached an eval**; fixed in bc4fb79 and e3228f2 (PENDING verdicts, `LineHooks` and `default_hooks`, `SYSTEM_PROMPT` through `Settings.system_prompt()`, rule 8's expected red) |
| 02, second pass | 9.9 min, 27 calls | 39 cases; live run 15 passed, 21 red by design, 3 pending, named in DR-017 | a bare `make eval` went to Bedrock where Haiku 5.5 has no quota (the default provider now follows DR-003); the gate's message when red; a probe pattern matched a refusal that quoted it; `title` missing from the card's list; fixed in a99765d |
| 03, tracing | 8 min, 33 calls | six spans a turn, hops add up within 1 ms, gate red by design | **`make eval` wrote 39 calls into the store `make trace last` reads** and the room's call was no longer the last; the store's byte refusal had three holes; nothing ever closed a call; the card named fields only the voice path knows; fixed in b197b15 (`TurnContext.store`, a store per path, the eval runner on its own file) |
| 04, tools and persona (first pass) | 23 min, 47 calls | tools built; two criteria failed | **the brain had no tool channel**, so a `TOOL name JSON` line inside the reply stood in for one and once read a caller's PIN aloud when the parser missed; two to four model calls a tool turn; two pre-built tests broke the moment the card landed; no latency line to read; fixed in 10bd218 (native tools on both providers, the cache mark, `REPLY_MAX_TOKENS`, `ctx.data`, the latency line, the two tests rebuilt) |
| 04, second pass | 14.7 min, 40 calls | zero boundary failures; median brain time 1,165 ms over 52 model turns | a test fake without the new argument; cached tokens unpriced and unprinted; the cap cut a tool call's arguments at 100 and fit two calls at 250; fixed in 8ba64a0 |
| 05, the guard | 9.3 min, 30 calls | red then green in two commits; 0.015 ms a sentence; zero hits on 52 eval answers | a pre-built test expected a forbidden word to come through unguarded; curly apostrophes slipped past the eval's checks where the guard straightened them; the spec had no fallback line; `before_speak` runs per turn, not per sentence; fixed in 73725e3 |
| 06, tiers and observer | (running at the time of writing) | | |
| 07, the scorecard | (not yet run) | | |

What the times say: with the plumbing fixed, a card is 3 to 15 minutes of tool time; the room's seven cards need the 90 minutes the plan gives them only if the questions and approvals are kept short, and card 04 is the one to protect. The findings that mattered were all in the pre-built plumbing, not in the cards' decisions, which is the division of labour KICKOFF asked for.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
