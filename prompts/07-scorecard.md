# Prompt card 07: the scorecard

Work item: one page that says what the line did today, in the numbers a recruiting lead would ask for, from the trace store and the synthetic baseline, with every number carrying its method.
Record: `docs/decisions/DR-022-scorecard.md` (live). The baseline of past invites with their invite-to-booked hours is pre-built (`data/baseline_invites.csv`, DR-009).

## Paste this

> Read `AGENTS.md`, `spec.md` (section 8, done means), `candidate_line/traces/store.py`, `candidate_line/evals/rates.py` and `data/baseline_invites.csv`. Build `make scorecard`: a command that reads the trace store and prints one page with the numbers in this card, each with its method and its n, and writes the same page as `var/scorecard.md`. Add a test that builds a scorecard from three synthetic calls. Touch only the files named below.

## The numbers

- Calls today, turns per call (median), calls by tier (a call's tier is the highest it reached), and calls that opened with no turn, on their own line.
- Median and worst turn, end of caller speech to first audio byte, against the DR-001 budget; the method named: the line's own spans (card 03), which is neither the probe's clock nor the recording, and the page says so.
- Cost per call, from the rate table (`rates.py`: the brain's tokens with cache reads and writes, Transcribe by the minute, Polly by the character, Twilio by the minute), split by brain, speech in, speech out; and the day's total against the spend caps (50 USD a month on AWS and 50 on the Anthropic workspace, DR-002 and DR-003; quoted on the page as quoted, not computed).
- Invite-to-booked hours: the baseline's median from `data/baseline_invites.csv` beside today's median from the booking tool's `tool` spans (card 04 writes `invited_at` and `slot` into them), with n for both and the sentence "synthetic data, synthetic baseline" on the page.
- Guard hits and overrides, as counts with trace links.
- Cite-or-refuse: over the turns that answered a process question from the FAQ (a `cited` span or a refusal), answers with a citation, refusals, and answers with neither (that last number should be zero; if it is not, it is the finding). Verification and booking turns are not answers and are not counted.

## Acceptance criteria

- `make scorecard` runs in under two seconds on a day of traces and prints the page.
- Every number on the page has its method and n beside it; no number is computed from anything outside the trace store, the rate table and the baseline file.
- The page names no caller: numbers masked at the store stay masked here.
- `make gate` passes.

## Decisions left open, asked of James before writing

1. Which single number leads the page.
2. Whether the page is also served by the cockpit or only printed.

## Files this card may touch

`candidate_line/scorecard.py` (new), `Makefile` (the `scorecard` target, its `.PHONY` entry and its help line), `tests/test_scorecard.py`, `docs/decisions/DR-022-scorecard.md`.

## Teach-back, after

James explains: where each number comes from, why the baseline is labelled synthetic on the page itself, and what "every number carries its method" buys in the room. Grade against `scorecard.py` by line.
