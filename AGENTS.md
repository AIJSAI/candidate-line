# AGENTS.md (DRAFT)

**DRAFT, 2026-11-01.** A first draft from the build plan's section 3.3, to be finished on Monday and Tuesday (KICKOFF.md, section 5) and frozen at the tag `prebuilt-2026-11-03`. It is function-neutral on purpose: what this line does and must never do lives in `spec.md`, which is written live, after the room confirms it.

These rules bind every coding tool and every agent working in this repository, the chosen tool and its fallback alike.

## Rules

1. **The learning rule comes first.** Every pre-built component gets a decision record, `docs/decisions/DR-NNN-<slug>.md`, from the template in DR-000: what it is, the alternative rejected, why, what would change the decision, and the one-line "say it like this". Every build block ends with James's teach-back: he explains the component in his own words; you grade each point right, partly or wrong against the code with file and line references, write the "say it like this" line into the record, and log every miss as a card in `docs/learn/cards.yaml` for the next day's grill. Before each command or diff, say what it does and why, and wait for approval. In Wednesday's live session, records are written as decisions land, and teach-backs wait until afterward. (KICKOFF.md, section 2; the format is in `docs/learn/README.md`.)
2. **Spec first.** No code for a work item until `spec.md` holds the line it serves. A change arrives as a spec line, then an eval case, then code, in that order.
3. **One work item and its files only.** Each card in `prompts/` names its work item, its files and its acceptance criteria. Touch nothing else; if the work needs another file, stop and ask.
4. **Never edit `evals/` or the baseline.** The eval cases and the committed baseline change only inside the work item that names them as its files, with James approving the diff. Never change a case, a threshold or the baseline to make a run pass.
5. **The spec's Never list binds every tool.** It holds for the coding tool, the fallback, every agent and every script, not only for the line at runtime.
6. **Cite or refuse.** Every answer the line gives from the knowledge pack cites a retrieved section id, or the line refuses. No answer comes from the model's own memory.
7. **Secrets from the environment or 1Password.** Never in a file, a commit, a log, a trace, a prompt or a message. No account id, phone number or credential is written into this repository.
8. **`make gate` before "done".** A work item is done when `make gate` passes. If your sandbox cannot reach Bedrock, ask James to run `make eval` and `make gate` in his own pane and read the result back.
9. **Approvals on, never bypassed.** No flag or mode that turns approvals off. The approvals are part of the trail.
10. **Synthetic data only.** No real person, firm or record. The firm is ACME until James names it.
11. **Pre-built is declared.** Anything committed before the tag is a row in `PREBUILT.md` with its commit date.
12. **One commit per work item**, with a conventional message (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), so the one-line log reads as the decision trail. Never force-push and never `git reset --hard`; to return to the last green commit, `git stash`.

## Stack

Each choice has its decision record once Sunday lands it.
- Python 3.12 under uv; FastAPI and uvicorn for the webhook and the media-stream WebSocket; pytest. (DR-004)
- AWS CLI v2; region us-east-1, with us-west-2 the spare. (DR-002, DR-003)
- `make eval`, `make gate`, `make trace last`, `make text`. (`Makefile`; stubs until Sunday's items land)

## Style

- Comments explain why, not what. Python signatures are typed.
- Prose in this repository is written English: plain words, short sentences, no em-dashes.

## Open until Monday and Tuesday

- Whether the chosen coding tool reads this file on its own. If not, it is pasted at the start of the session.
- Whether its sandbox lets a command reach Bedrock (rule 8).
- Rule 4's exception for the work item that writes the cases: confirm the wording before the tag.
- The function-specific lines, which go into `spec.md` live, after the room confirms them.
