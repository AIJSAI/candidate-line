# Prompt card 07: the scorecard

Work item: one page that says what the line did today, in the numbers a recruiting lead would ask for, from the trace store and the synthetic baseline, with every number carrying its method.
Record: `docs/decisions/DR-022-scorecard.md` (live). The baseline of past invites with their invite-to-booked hours is pre-built (`data/baseline_invites.csv`, DR-009).

## Paste this

> Read `AGENTS.md`, `spec.md` (section 8, done means), `candidate_line/traces/store.py`, `candidate_line/evals/rates.py` and `data/baseline_invites.csv`. Build `make scorecard`: a command that reads the trace store and prints one page with the numbers in this card, each with its method and its n, and writes the same page as `var/scorecard.md`. Add a test that builds a scorecard from three synthetic calls. Touch only the files named below.

## The numbers

- Calls today, turns per call (median), calls that ended in tier 1, 2 and 3.
- Median and worst turn, end of caller speech to first audio byte, against the DR-001 budget; the method named (probe caller or recording).
- Cost per call, from the rate table, split by brain, speech in, speech out; and the day's total against the spend caps.
- Invite-to-booked hours: the baseline's median from `data/baseline_invites.csv` beside today's median from the booking tool's spans, with n for both and the sentence "synthetic data, synthetic baseline" on the page.
- Guard hits and overrides, as counts with trace links.
- Cite-or-refuse: answers with a citation, refusals, and answers with neither (that last number should be zero; if it is not, it is the finding).

## Acceptance criteria

- `make scorecard` runs in under two seconds on a day of traces and prints the page.
- Every number on the page has its method and n beside it; no number is computed from anything outside the trace store, the rate table and the baseline file.
- The page names no caller: numbers masked at the store stay masked here.
- `make gate` passes.

## Decisions left open, asked of James before writing

1. Which single number leads the page.
2. Whether the page is also served by the cockpit or only printed.

## Files this card may touch

`candidate_line/scorecard.py` (new), `Makefile` (the `scorecard` target only), `tests/test_scorecard.py`, `docs/decisions/DR-022-scorecard.md`.

## Teach-back, after

James explains: where each number comes from, why the baseline is labelled synthetic on the page itself, and what "every number carries its method" buys in the room. Grade against `scorecard.py` by line.
