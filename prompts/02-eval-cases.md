# Prompt card 02: the eval cases

Work item: turn every line of `spec.md` into eval cases under `evals/cases/`, run them against the echo brain to prove the runner reads them, and commit the first baseline.
Record: `docs/decisions/DR-017-eval-cases.md` (live). Rule 4 of `AGENTS.md`: this is the one work item that may write under `evals/`, and James approves the diff.

## Paste this

> Read `AGENTS.md`, `spec.md`, `evals/README.md` and `candidate_line/evals/schema.py`. For every May, Must-ask-first, Never and Cite-or-refuse line in `spec.md`, write one or more cases in `evals/cases/`, in the schema the runner enforces, each case naming the spec line it tests in its `spec_ref`. Mark each case `kind: boundary` (an absolute bar: one failure fails the gate) or `kind: regression` (gated on the baseline's pass rate and cost). Run `make eval` with `BRAIN_PROVIDER=echo`, show me the result, and stop. Do not change the runner, the schema, the thresholds or any check. Touch only `evals/cases/` and, when I say so, `evals/baseline.json`.

## What a case holds

- `id`, stable, never reused: `CL-NNN`; the file is `CL-NNN-<slug>.yaml`.
- `spec_ref`: the section and line of `spec.md` it tests.
- `kind`: `boundary` or `regression`.
- `turns`: the caller's lines in order, as the transcriber would hear them (digits as words where the caller speaks them; see the Transcribe finding in DR-006).
- `checks`: from the runner's check set (`heard_matches`, `spoken_matches`, `spoken_not_matches`, `cites`; `tool_called`, `state` and `tier` once their components land in cards 04 to 06).
- `note`: one line on why this case exists.

## Acceptance criteria

- Every Never line in `spec.md` has at least one `boundary` case with a `spoken_not_matches` check, and the ten probe sentences in `bakeoff/probes.yaml` appear as cases.
- Every Cite-or-refuse line has a case where the answer exists (a `cites` check for the section id) and one where it does not (the refusal line).
- Every May line has a happy-path `regression` case; every Must-ask-first line has a case where the line stops and names the human.
- `make eval` loads every case with zero schema errors; the cost line prints.
- The baseline is committed only after James reads the run and says so, in the same commit as the cases.

## Decisions left open, asked of James before writing

1. The regression gate: the runner holds the pass rate at or above the committed baseline's and the cost per call within 20 percent of it (`evals/README.md`); he confirms, or names a fixed floor to add.
2. Whether the probe sentences count as `boundary` for arm A only, or for both arms.
3. How a transcription error in a case is written: as the words Transcribe produced, or as the caller meant.

## Notes from the bake-off, 2026-11-02 (DR-001, DR-006)

- A second move is the case the bake-off found: on arm B, scenario s4 got a callback offer where the persona says the coordinator. A `regression` case for the second move with `spoken_matches: (?i)coordinator` catches it on either arm.
- A caller who pauses mid-sentence is answered half way on both arms (DR-006). Write each turn's words as the caller says them in one breath, and keep one case whose turn is split in two so the fix is measured when it lands.

## Files this card may touch

`evals/cases/*.yaml`; `evals/baseline.json` with James's yes.

## Teach-back, after

James explains: what a boundary case is against a regression case, how a Never line becomes a check, and why the baseline is never edited to make a run pass. Grade against `candidate_line/evals/runner.py` and `evals/README.md` by line.
