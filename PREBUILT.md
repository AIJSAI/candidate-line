# PREBUILT

Everything committed before the tag `prebuilt-2026-11-03` is listed here with its commit date, and this list is shown at minute 2. No hidden finished branch exists. Nothing on this list decides anything about a caller: the spec, the eval cases, the guard, the tiers, the persona and the tools are built live.

Fill each row as its item lands: the commit date and short sha, its decision record, and the date of James's teach-back (KICKOFF.md, Rule 1).

## Pre-built and declared

| # | Item | Landed (date, sha) | Record | Teach-back |
| - | - | - | - | - |
| 0 | The repository skeleton: `KICKOFF.md`, `AGENTS.md` (draft), DR-000, DR-001 with its rule (draft), `docs/learn/`, this file, the `Makefile` stub, `.gitignore` | 2026-11-01, the first commit | DR-000, DR-001 | |
| 1 | AWS account, CLI profile with no long-lived key in a file, budget alarm, model access | 2026-11-02, 462381a (Identity Center live 15:40 CT, old key inactive 15:46 CT; budget 11-01; model access: Haiku 4.5 on Bedrock, Haiku 5.5 on the Anthropic API) | DR-002, DR-003 | |
| 2 | Twilio number (upgraded), tunnel, webhook | 2026-11-02, c45159b (number, webhook and tunnel live 15:16 CT; account and identity check by James) | DR-004, DR-005 | |
| 3 | Arm A's audio path and turn loop, with a brain that only echoes; barge-in; the grace window after a final transcript | 2026-11-02, first real call 15:17 CT (code 09eccfb, 2026-11-01); the grace window the same evening | DR-006 | |
| 4 | Arm B: the AWS sample, as-is | 2026-11-02 (built 13:40 CT, first call 16:05 CT; settings patch `bakeoff/arm-b-settings.patch`) | DR-007 | |
| 5 | Text-mode REPL; four empty hooks (`on_turn`, `before_speak`, `on_silence`, `on_tool`) | 2026-11-01, 7d236e3 | DR-008 | |
| 6 | Synthetic data: eight candidates with codes and PINs, two weeks of slots, a three-page FAQ with section ids, and a labelled baseline of past invites with their invite-to-booked hours for the scorecard; the generating prompt committed | 2026-11-01, e39dde6 | DR-009 | |
| 7 | `bakeoff/2026-11-01.csv`, its probe list `bakeoff/probes.yaml`, the bake-off's test persona prompt, and the rule written before it; the measurement | 2026-11-01, 2704a73; measured 2026-11-02, 5587692 | DR-001 | |
| 8 | `docs/refs/`: dated saved copies of the Nova 2.5 Sonic and Claude model cards, the pricing pages and the two statute pages | 2026-11-01, b847815 | cited by each record | |
| 9 | An eval runner with zero cases | 2026-11-01, a96ebad | DR-010 | |
| 10 | The probe caller: a scripted synthetic candidate that dials the line and is scored against the case file; the cases it plays are written live | 2026-11-01, b8d9623 | DR-011 | |
| 11 | The trace store and the cockpit's list view; the spans from the turn loop, the kill switch and the override log are written live | 2026-11-01, 000102a | DR-012 | |
| 12 | The escalation webhook and its message template; the rule for when it posts is written live, with the tiers | 2026-11-01, 93ad659 | DR-013 | |
| 13 | The coding tool: Claude Code, with the comparison that could not run (Codex quarantined by Gatekeeper, its reinstall refused to the session) | 2026-11-02, 82928f1 | DR-014 | |
| 14 | `AGENTS.md`, finished; `prompts/01` to `07`, one work item each with acceptance criteria and its decisions left open; the five-line problem card drafted in `prompts/01`; `docs/room.md` | 2026-11-02, 507f3e0; the draft, the room notes and the dry-run amendments the same evening (c872d82, bc4fb79); the hour sized to sixty minutes on 2026-11-03 (`docs/room.md`, the 60-minute line in cards 01 and 06) and `make restart` the same day, so a card's code reaches the phone without touching the tunnel or the webhook | DR-015 | |
| 15 | The tag `prebuilt-2026-11-03` | 2026-11-02, 8ad137b (22:00 CT); what came after it is listed below the table | | |

## After the tag, 2026-11-03

The tag marks what the dry run of 2026-11-02 left; Tuesday changed the shape of the session and a second dry run of the cards followed (DR-015). Everything after the tag is pre-built plumbing or a record, never a decision about a caller, and it is listed here so minute 2 shows it with the table:

- the hour sized to sixty minutes and the 60-minute problem card (8e7ca89, 8ce9d6a); `data/faq.md` F3.2 and F8.1 say the line hands a move to the coordinator, to agree with that card (8ce9d6a);
- `make restart`, so a card's code reaches the phone without touching the tunnel or the webhook (b630c30);
- the eval runner leaves a `channel: voice` case to the probe caller (3aae326);
- the probe caller counts only audio after its own last frame as Gus's reply (e5b3c5e, DR-011's open quirk);
- the phone drains its hand-off queue when it stops (d2ec46f);
- every test traces in memory and never in the room's store, the transcriber's finals carry a confidence and a lag from the end of speech, the cost carries no float noise (8f0c745), and the phone app is built when uvicorn asks for it rather than at import (7d4a0c3);
- two records corrected to the code, DR-001's grace figure and DR-003's cached-read sentence (26710c9);
- no module but settings reads the environment, as DR-004 says: the store's default path is a constant, the Slack poster takes its URL from settings, the probe caller's Twilio identifiers are typed settings (299fa06);
- the eval runner prints the cases that moved between runs and each case's brain time, `make baseline` writes the baseline from a green run, and a trace meta key named pin is stored masked (2c948e5); the direct probe target runs on the line's profile (1804dc8);
- the quote-straightening table in its own module, `candidate_line/text.py`, so the guard and the eval checks share it without a circular import;
- the hand-off message names the caller, the store looks up one call, the trace link has a setting (`COCKPIT_BASE_URL`), the log poster shows `[hand-off]` on screen, a hook fires when a call ends, and the silence path and a turn hook can ask for the hang-up through the context (43d8f07, 6cc3ff1);
- the amendments to the cards after each card's second dry run, named in DR-015's second table.
- the afternoon's drill on the committed head (`docs/room.md`, "The line, the hour before"): `make down` waits for the port before it lists what is left (01609e1); the room notes say who types the tunnel commands and give the morning line (ed91c33); the read-only commands are allowlisted for the room's tool in `.claude/settings.json` (59dbf04); DR-011's live note closes with the direct and dialled probe runs of 15:01 and 15:03 CT, both PASS (3923b01); the Bedrock fallback's default model id is the dated Haiku 4.5 profile, found when the first fallback turn was refused, and Haiku 5.5 on Bedrock is still closed to the account (ac7597c); the Identity Center session raised to 7 days so no sign-in stands between the room and the phone (443014f). The evening of 2026-11-03: `make text`, `make eval`, `make baseline` and `make gate` run on the line's AWS profile like the phone and the probe targets, so the Bedrock spare answers a text turn with nothing set in the shell (proven with one Haiku 4.5 turn); the minute-2 line in `docs/room.md` states the problem as the plan (7a40bdb). Late that night the cockpit's two pages were restyled so a recruiter can read them, rendering only, with the routes, the reply form and the store untouched (117bad0); a turn that raises now speaks one fixed recovery line instead of leaving the caller in silence, the exception still logged (2026-11-03 night, the readiness check).

## A dry run of the cards, and what came of it

On the evening of 2026-11-02 all seven cards were run one at a time, in order, by a coding agent in a detached scratch worktree, against a clock, with the session's draft answers standing in for James's (cards 02 and 04 twice, after the fixes their first pass forced). The worktree was discarded and pruned; nothing it built exists in this repository or on any branch. What entered the repository is its defect list, as pre-built plumbing fixed before the tag and named commit by commit in DR-015's table: the eval schema's keys and the runner's pending verdicts; one persona and one hooks object for every path; a trace store per path and the span kinds; the brain's native tool channel with the prompt cache mark; the escalation queue on the turn context, the phone's silence hook and hang-up; the rate table's speech rows; and the cards' own wording wherever it said something the code could not do. The decisions the cards leave open are still open: no spec, case, tool, persona, guard, tier or scorecard from the dry run exists here. The per-card times are in DR-015: about 68 minutes of tool time end to end.

## Built live on Wednesday, never before the tag

- `spec.md`, from a five-line problem card and the room's answers, with the Never list confirmed by the room
- The eval cases: the first set from the spec, then one more for the counter-case, then another for the change the room asks for
- Tracing, before the first tool
- DR-001's decision text, after the counter-case
- The tools and the persona
- The guard, its red-proof, the tiers and the observer
- The escalation rule, with the tiers
- The kill switch and the override log
- The probe caller's cases
- The scorecard
- The change the room asks for
