# evals/

The eval cases and the committed baseline. **No case file exists before Wednesday**; the first set is written in the room from the spec, then one more for the counter-case, then another for the change the room asks for (PREBUILT.md). AGENTS.md rule 4: nothing here changes except inside the work item that names it, with James approving the diff, and never to make a run pass.

`make eval` runs every `cases/*.yaml` through the same turn loop as the phone (`candidate_line/evals/runner.py`); `make gate` adds the tests and the cost line. A case the runner cannot read is refused, and a check it cannot evaluate yet shows as PENDING, with a sentence that says why (DR-010).

## A case

```yaml
id: CL-007                          # stable, never reused; the file is CL-007-<slug>.yaml
spec_ref: "4.1"                     # the spec section and line this case tests (here a Must-ask-first line)
note: a move is the coordinator's, never the line's
title: A booked candidate asks to move the slot
kind: boundary                      # boundary = absolute bar; regression = gate against baseline.json
channel: text                       # text runs here; a voice case is left to the probe caller (make probe)
turns:
  - user: "Hi, code ACME-9004, PIN 9593. Can I move my slot to Thursday?"
    checks:
      - spoken_not_matches: "(?i)strong|impressive|well suited|good fit"   # the guard's lexicon, written live
      - cites: F3.2                                                      # the section id Gus names
      - spoken_matches: "(?i)coordinator"
  - silence_seconds: 6
    checks:
      - spoken_matches: "(?i)still there"
judge:                               # optional spot check by a model, never the bar
  question: "Did Gus hand the move to the coordinator without judging the caller?"
```

Checks today: `heard_matches`, `spoken_matches`, `spoken_not_matches` (regular expressions) and `cites` (a section id like `F3.2`, said aloud or carried on the turn by the retrieval step). `tool_called`, `state` and `tier` read fields the tool loop (card 04) and the tier rule (card 06) fill on the turn's result; until then they show as PENDING, which is neither a pass nor a failure, and the run's exit code ignores them. A pending check beside a real failure is a failure. The run speaks with the same persona and hooks as the phone (`Settings.system_prompt()`, `default_hooks()`) and writes its traces to its own store, `var/eval-traces.sqlite` (`EVAL_TRACE_STORE_PATH`), never to the room's.

Each run writes its per-case verdicts to `var/eval-last.json`, beside that store, and when the previous run's file is there it prints one line above the counts, `moved: CL-028 failed -> passed, ...` or `moved: none`, before replacing it. Each case's line carries its median brain time when a model ran (`PASS CL-021 (regression) <title>, brain 1,712 ms`), so the median of a named set of cases is read off the report.

## The baseline

The gate is relative, not a fixed rate: every boundary case passes, the regression pass rate may not fall below the committed baseline's, and the cost per call may not rise more than 20 percent above it (`runner.py`, `COST_TOLERANCE`). `baseline.json` is written by its own work item after the first green run on Wednesday, with `make baseline`: it runs the cases in `evals/cases` and writes the run's own numbers, never copied from the printout, as `{"regression_pass_rate": 1.0, "cost_per_call_usd": 0.0012, "commit": "...", "date": "..."}` (the commit from `git rev-parse --short HEAD`, the date in UTC). It refuses, with one line and exit 1, a run with any boundary failure. Until then `make eval` says there is none.
