# DR-000: How decisions are recorded

Status: DECIDED 2026-11-01
Built: pre-built (PREBUILT.md row 0)

## The rule

- **Every pre-built component gets a decision record** before the block that builds it closes (KICKOFF.md, Rule 1). So does every real choice made live on Wednesday, written as it lands.
- **One file per decision:** `docs/decisions/DR-NNN-<slug>.md`, numbered in the order the records land. A number is never reused. A changed decision gets a new record that supersedes the old one, and the old record's status says so; history is never rewritten.
- **Facts carry their source and read date**, and a page relied on is saved, dated, in `docs/refs/`. A measured number carries its method and its n. Judgment is labelled [inference]; a guess to test is labelled [hypothesis]. No rate, quota or model fact comes from memory.
- **A record never holds** a secret, an account id, a phone number, a real person's or firm's name, or anything from James's employer. ACME stands for the firm until James names it.
- **The "say it like this" line** is written by the session after James's teach-back, in his words as corrected: one line, first person, the design reason before the tech list.
- **Status is DRAFT** until the teach-back is graded, or, for a live decision, until the room has seen it.

## The template

Copy everything inside the block into a new file.

```markdown
# DR-NNN: <the decision, as a short title>

Status: DRAFT | DECIDED YYYY-MM-DD | SUPERSEDED by DR-NNN
Built: pre-built (PREBUILT.md row N) | live (minute NN)
Commit: <short sha where it landed>

## What it is
Two or three sentences: the component and the job it does.

## The decision
What was chosen, in one paragraph.

## The alternative rejected, and why
Each alternative considered, with the reason it lost.

## What would change the decision
The trigger that reopens it: a measurement, a vendor change, a new requirement.

## Evidence
Facts with their source and read date (and the docs/refs/ file); measured numbers with their method and n.

## Say it like this
> One line, first person, written after the teach-back.

## Teach-back
YYYY-MM-DD. Before (1 to 7): N. After (1 to 7): N.
Right: ... Partly: ... Wrong: ... (each with path:line, or the command)
Cards: candidate-line-NNNN, ...
```
