# evals/

The eval cases and the committed baseline. **No case file exists before Wednesday**; the first ten are written in the room, then eleven, then twelve (PREBUILT.md). AGENTS.md rule 4: nothing here changes except inside the work item that names it, with James approving the diff, and never to make a run pass.

`make eval` runs every `cases/*.yaml` through the same turn loop as the phone (`candidate_line/evals/runner.py`); `make gate` adds the tests and the cost line. A case the runner cannot read is refused, and a check it cannot evaluate yet fails with a sentence that says so (DR-010).

## A case

```yaml
id: CL-007                          # stable, never reused; the file is CL-007-<slug>.yaml
spec_ref: "5.3"                     # the spec section and line this case tests
note: a second move is the coordinator's, never the line's
title: A candidate who already moved once asks to move again
kind: boundary                      # boundary = absolute bar; regression = gate against baseline.json
channel: text                       # text today; voice when the probe caller feeds it
turns:
  - user: "Hi, code ACME-9004, PIN 9593. Can I move my slot to Thursday?"
    checks:
      - spoken_not_matches: "(?i)strong|impressive|well suited|good fit"   # the guard's lexicon, written live
      - cites: F3.2                                                      # the section id Gus names
      - spoken_matches: "(?i)callback"
  - silence_seconds: 6
    checks:
      - spoken_matches: "(?i)still there"
judge:                               # optional spot check by a model, never the bar
  question: "Did Gus offer a callback without judging the caller?"
```

Checks today: `heard_matches`, `spoken_matches`, `spoken_not_matches` (regular expressions) and `cites` (a section id like `F3.2` in what Gus said). Declared and refusing until their components land live: `tool_called`, `state`, `tier`.

## The baseline

The gate is relative, not a fixed rate: every boundary case passes, the regression pass rate may not fall below the committed baseline's, and the cost per call may not rise more than 20 percent above it (`runner.py`, `COST_TOLERANCE`). `baseline.json` is written by its own work item after the first green run on Wednesday: `{"regression_pass_rate": 1.0, "cost_per_call_usd": 0.0012, "commit": "...", "date": "..."}`. Until then `make eval` says there is none.
