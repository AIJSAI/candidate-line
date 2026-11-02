# AGENTS.md

Finished 2026-11-02 from the 2026-11-01 draft (DR-015); frozen at the tag `prebuilt-2026-11-03`. It is function-neutral on purpose: what this line does and must never do lives in `spec.md`, which is written live, after the room confirms it (`prompts/01`).

These rules bind every coding tool and every agent working in this repository, the chosen tool and its fallback alike.

## Rules

1. **The learning rule comes first.** Every pre-built component gets a decision record, `docs/decisions/DR-NNN-<slug>.md`, from the template in DR-000: what it is, the alternative rejected, why, what would change the decision, and the one-line "say it like this". Every build block ends with James's teach-back: he explains the component in his own words; you grade each point right, partly or wrong against the code with file and line references, write the "say it like this" line into the record, and log every miss as a card in `docs/learn/cards.yaml` for the next day's grill. Before each command or diff, say what it does and why, and wait for approval. In Wednesday's live session, records are written as decisions land, and teach-backs wait until afterward. (KICKOFF.md, section 2; the format is in `docs/learn/README.md`.)
2. **Spec first.** No code for a work item until `spec.md` holds the line it serves. A change arrives as a spec line, then an eval case, then code, in that order.
3. **One work item and its files only.** Each card in `prompts/` names its work item, its files and its acceptance criteria. Touch nothing else; if the work needs another file, stop and ask.
4. **Never edit `evals/` or the baseline.** The eval cases and the committed baseline change only inside the work item that names them as its files, which is `prompts/02` and no other, with James approving the diff. Never change a case, a threshold or the baseline to make a run pass.
5. **The spec's Never list binds every tool.** It holds for the coding tool, the fallback, every agent and every script, not only for the line at runtime.
6. **Cite or refuse.** Every answer the line gives from the knowledge pack cites a retrieved section id, or the line refuses. No answer comes from the model's own memory.
7. **Secrets from the environment or 1Password.** Never in a file, a commit, a log, a trace, a prompt or a message. On this Mac the machine copy lives in the login keychain: `make secret NAME=<VAR>` stores the clipboard and clears it, and `scripts/env.sh` exports it for a shell (`. scripts/env.sh`). No account id, phone number, start URL or credential is written into this repository.
8. **`make gate` before "done".** A work item is done when `make gate` passes. If your sandbox cannot reach Bedrock or the Anthropic API, ask James to run `make eval` and `make gate` in his own pane and read the result back.
9. **Approvals on, never bypassed.** No flag or mode that turns approvals off. The approvals are part of the trail.
10. **Synthetic data only.** No real person, firm or record. The firm is ACME until James names it (`prompts/01`, open decision 1).
11. **Pre-built is declared.** Anything committed before the tag is a row in `PREBUILT.md` with its commit date, and is never presented as built live.
12. **One commit per work item**, with a conventional message (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), so the one-line log reads as the decision trail. Never force-push and never `git reset --hard`; to return to the last green commit, `git stash`.
13. **Measured, with the method.** A number said aloud or written down carries how it was measured and its n (DR-000). A latency is named by its endpoints; a cost by its rate table (`candidate_line/evals/rates.py`).

## The work items

Seven prompt cards in `prompts/`, one work item each, in order. Each card holds the text to paste, the shape of the output, the acceptance criteria, the decisions left open for James, the files it may touch, and the teach-back. The function's specifics live only in `spec.md`, so a new function changes the spec and not the cards.

| Card | Work item | Record |
| - | - | - |
| `prompts/01-spec-from-problem-card.md` | `spec.md` from a five-line problem card | DR-016 |
| `prompts/02-eval-cases.md` | the eval cases and the first baseline | DR-017 |
| `prompts/03-tracing.md` | the spans from the turn loop into the store | DR-018 |
| `prompts/04-tools-and-persona.md` | the tools over `data/` and Gus's prompt | DR-019 |
| `prompts/05-guard-and-red-proof.md` | `before_speak`, red first, then green | DR-020 |
| `prompts/06-tiers-and-observer.md` | the tier rule, the hand-off, the override, the kill switch | DR-021 |
| `prompts/07-scorecard.md` | `make scorecard` | DR-022 |

The switch rule (KICKOFF.md, section 6): three minutes with no diff, or one work item failing twice, and the same card goes to the other tool, said aloud.

## Stack

Each choice has its decision record.
- Python 3.12 under uv; FastAPI and uvicorn for the webhook and the media-stream WebSocket; pytest and ruff. (DR-004)
- AWS CLI v2; region us-east-1, with us-west-2 the spare. Sign-in through IAM Identity Center, no long-lived key in a file. (DR-002)
- The brain behind one interface, chosen by `BRAIN_PROVIDER`: Claude Haiku 5.5 on the Anthropic API for the live turn, Claude Haiku 4.5 on Bedrock as the drill and the fallback, thinking off and effort low; Sonnet 5.5 for the summary nobody waits on. (DR-003)
- Twilio Programmable Voice: the webhook with its signature check, the media stream, the tunnel. (DR-005)
- Arm A: Transcribe streaming, the brain, Polly mu-law by sentence, barge-in by `clear`. Arm B: the AWS Nova Sonic sample, as-is, beside the repository. (DR-006, DR-007)
- Text mode and the four hooks `on_turn`, `before_speak`, `on_silence`, `on_tool`. (DR-008)
- Synthetic data from one seed, with its generating prompt. (DR-009)
- The eval runner, the probe caller, the trace store and cockpit, the escalation queue. (DR-010 to DR-013)
- `make dev`, `make tunnel`, `make webhook`, `make cockpit`, `make probe`, `make test`, `make eval`, `make gate`, `make trace last`, `make text`, `make secret`. (`Makefile`)

## The coding tool

Claude Code, with its approvals on, is the tool of record for the build days and Wednesday (DR-014). It reads this file on its own at the start of a session. The second pane holds the fallback named in DR-014. Whether a sandbox can reach the model providers is checked once per tool and recorded there; rule 8 says what happens when it cannot.

## Style

- Comments explain why, not what. Python signatures are typed.
- Prose in this repository is written English: plain words, short sentences, no em-dashes.
- A reply Gus speaks is one or two sentences, because a caller is waiting and output tokens set the latency (DR-003).

## Still open at the tag

- The function-specific lines, which go into `spec.md` live, after the room confirms them (`prompts/01`).
- Each card's "decisions left open" list, asked of James at the card's start, never answered by the tool.
