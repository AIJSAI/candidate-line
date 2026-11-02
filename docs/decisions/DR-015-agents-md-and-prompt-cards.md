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

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
