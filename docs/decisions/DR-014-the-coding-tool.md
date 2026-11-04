# DR-014: The coding tool

Status: DECIDED 2026-11-02
Built: pre-built (PREBUILT.md row 13)
Commit: 82928f1

## What it is

Which coding tool drives Wednesday's build on the shared screen, which one sits in the second pane as the fallback, and how that was decided.

## The decision

**Claude Code, approvals on, is the tool of record, by James's decision on 2026-11-02 (about 13:50 CT): the team running the session builds with Claude, so the line is built with the same tool, and the Codex comparison is closed.** The session's account of why the comparison could not have run anyway follows, kept because it happened. The fallback in the second pane is a second Claude Code session with a fresh context, used under the switch rule (three minutes with no diff, or one work item failing twice, said aloud). The two checks from the plan's section 3.3, read 2026-11-02: Claude Code reads `AGENTS.md` on its own at session start (it loaded this repository's draft in every session this week, including the one writing this record); its shell reaches Bedrock and the Anthropic API from this Mac (every measured call in DR-003 ran from inside it), so rule 8's hand-off to James's pane is the exception, not the path.

**The scratch task did not run as a comparison.** The plan's method was twenty minutes of `prompts/01` through Codex and through Claude Code, keeping the one whose approvals and trail read better. Codex was not available to run it: on 2026-11-01 at 18:35 CT the installed cask binary (Codex 0.128.0, unnotarized) was quarantined by macOS Gatekeeper when `codex --version` ran, and sits in the Trash; on 2026-11-02 the reinstall (`brew upgrade --cask codex`, 0.166.0) was refused to the build session by its command classifier as external code. The decision therefore rests on the two checks and on the week's trail, and it says so. With James's decision above the comparison is closed; a later wish to run it would be a new record that supersedes this one.

## The alternative rejected, and why

- **Codex CLI as the tool of record.** Not measurable this week (above). Its install hour and sandbox check drop from Monday, as the plan said they would if it lost.
- **Running the comparison through a non-interactive Claude Code call (`claude -p`) to stand in for a second tool.** It would produce a diff but no approvals and no trail, which are the two things the comparison was meant to judge.
- **No fallback pane.** A stalled work item on a shared screen with no second seat is the failure the switch rule exists for.

## What would change the decision

Codex installed and the twenty-minute scratch task run (then this record is superseded by the measured one, whichever way it goes). Claude Code losing the ability to read `AGENTS.md` at session start (then the file is pasted first, and rule 1's approvals still hold). A sandbox on the day that cannot reach a model provider (then rule 8: James runs `make eval` and `make gate` in his pane).

## Evidence

- `which codex` on 2026-11-01: `/opt/homebrew/bin/codex`, a symlink into the Homebrew Caskroom for 0.128.0; the binary was moved to the Trash by Gatekeeper at 18:35 CT with the "could not verify it is free of malware" dialog; `brew` lists 0.166.0 as current.
- 2026-11-02, about 13:08 CT: `brew upgrade --cask codex` refused by the build session's classifier ("Code from External"); nothing was downloaded.
- 2026-11-02, 13:40 and 13:48 CT: the same command refused twice more after James approved permissions; nothing was downloaded. James then closed the question: Claude Code, because the team running the session builds with Claude.
- Claude Code reading `AGENTS.md`: this session's own start loaded the draft (observed 2026-11-01 and 2026-11-02).
- Model reach from inside Claude Code: DR-003's measured calls to Bedrock (Haiku 4.5, 2026-11-01) and to the Anthropic API (Haiku 5.5, 2026-11-02).

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
