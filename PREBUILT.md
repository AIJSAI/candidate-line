# PREBUILT

Everything committed before the tag `prebuilt-2026-11-03` is listed here with its commit date, and this list is shown at minute 2. No hidden finished branch exists. Nothing on this list decides anything about a caller: the spec, the eval cases, the guard, the tiers, the persona and the tools are built live.

Fill each row as its item lands: the commit date and short sha, its decision record, and the date of James's teach-back (KICKOFF.md, Rule 1).

## Pre-built and declared

| # | Item | Landed (date, sha) | Record | Teach-back |
| - | - | - | - | - |
| 0 | The repository skeleton: `KICKOFF.md`, `AGENTS.md` (draft), DR-000, DR-001 with its rule (draft), `docs/learn/`, this file, the `Makefile` stub, `.gitignore` | 2026-11-01, the first commit | DR-000, DR-001 | |
| 1 | AWS account, CLI profile with no long-lived key in a file, budget alarm, model access | 2026-11-02, 462381a (Identity Center live 15:40 CT, old key inactive 15:46 CT; budget 11-01; model access: Haiku 4.5 on Bedrock, Haiku 5.5 on the Anthropic API) | DR-002, DR-003 | |
| 2 | Twilio number (upgraded), tunnel, webhook | 2026-11-02, c45159b (number, webhook and tunnel live 15:16 CT; account and identity check by James) | DR-004, DR-005 | |
| 3 | Arm A's audio path and turn loop, with a brain that only echoes; barge-in | 2026-11-02, first real call 15:17 CT (code 09eccfb, 2026-11-01) | DR-006 | |
| 4 | Arm B: the AWS sample, as-is | | DR-007 | |
| 5 | Text-mode REPL; four empty hooks (`on_turn`, `before_speak`, `on_silence`, `on_tool`) | 2026-11-01, 7d236e3 | DR-008 | |
| 6 | Synthetic data: eight candidates with codes and PINs, two weeks of slots, a three-page FAQ with section ids, and a labelled baseline of past invites with their invite-to-booked hours for the scorecard; the generating prompt committed | 2026-11-01, e39dde6 | DR-009 | |
| 7 | `bakeoff/2026-11-01.csv`, its probe list `bakeoff/probes.yaml`, the bake-off's test persona prompt, and the rule written before it | 2026-11-01, 2704a73 | DR-001 | |
| 8 | `docs/refs/`: dated saved copies of the Nova 2.5 Sonic and Claude model cards, the pricing pages and the two statute pages | 2026-11-01, b847815 | cited by each record | |
| 9 | An eval runner with zero cases | 2026-11-01, a96ebad | DR-010 | |
| 10 | The probe caller: a scripted synthetic candidate that dials the line and is scored against the case file; the cases it plays are written live | 2026-11-01, b8d9623 | DR-011 | |
| 11 | The trace store and the cockpit's list view; the spans from the turn loop, the kill switch and the override log are written live | 2026-11-01, 000102a | DR-012 | |
| 12 | The escalation webhook and its message template; the rule for when it posts is written live, with the tiers | 2026-11-01, 93ad659 | DR-013 | |
| 13 | The coding tool: Claude Code, with the comparison that could not run (Codex quarantined by Gatekeeper, its reinstall refused to the session) | 2026-11-02, 82928f1 | DR-014 | |
| 14 | `AGENTS.md`, finished; `prompts/01` to `07`, one work item each with acceptance criteria and its decisions left open | 2026-11-02, 507f3e0 | DR-015 | |
| 15 | The tag `prebuilt-2026-11-03` | | | |

## Built live on Wednesday, never before the tag

- `spec.md`, from a five-line problem card and the room's answers, with the Never list confirmed by the room
- The eval cases: ten, then eleven, then twelve
- Tracing, before the first tool
- DR-001's decision text, after the counter-case
- The tools and the persona
- The guard, its red-proof, the tiers and the observer
- The escalation rule, with the tiers
- The kill switch and the override log
- The probe caller's cases
- The scorecard
- The change the room asks for
