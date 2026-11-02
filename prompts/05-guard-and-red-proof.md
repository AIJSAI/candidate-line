# Prompt card 05: the guard, with its red-proof

Work item: the `before_speak` guard that checks exactly the text speech will say against the Never list and a lexicon, and the red-proof that shows it firing before anyone trusts it.
Record: `docs/decisions/DR-020-the-guard.md` (live). The hook exists and is empty (DR-008); the ten probe sentences exist (`bakeoff/probes.yaml`, DR-001).

## Paste this

> Read `AGENTS.md`, `spec.md`, `candidate_line/hooks.py`, `candidate_line/telephony/media.py` (the `speak` path) and `bakeoff/probes.yaml`. Implement `before_speak` as a guard over the exact text handed to speech: a lexicon of patterns from the Never list and the probe sentences, plus the rules in this card. When it fires, the line says the fallback line from `spec.md` instead, and the trace's `guard` field records the hit. First write the red-proof: a test that feeds each probe sentence through the guard and fails until the guard catches it; run it red, show me, then make it green. Touch only the files named below.

## The guard's rules

- It checks the text that will be spoken, after any tool result is folded in, never the model's draft; a guard that reads the wrong string proves nothing.
- A hit replaces the sentence, never the whole call; the caller hears the fallback line and the turn continues.
- It is deterministic and under 5 ms, because it sits inside the latency budget on every sentence (DR-001).
- Its lexicon is a file under `candidate_line/guard/`, read at start, with one line per pattern and the spec line it serves; James approves every change by diff.
- It never evaluates the caller's words, only Gus's.

## The red-proof

1. The test `tests/test_guard_red_proof.py` runs the ten probe sentences and twenty paraphrases through the guard and asserts every one is caught.
2. It is committed failing first, in its own commit, with the output in the commit message's body, so the trail shows the guard was built against a red test.
3. Then the guard lands and the test goes green in the next commit.
4. On Wednesday, a live call tries to make Gus say one; the trace shows the hit.

## Acceptance criteria

- All ten probe sentences and their paraphrases are caught; the happy-path cases in `evals/` still pass (the guard does not fire on a normal answer).
- The guard's own latency is measured in the test and is under 5 ms per sentence.
- The `guard` span is written on every sentence, `clean` or the pattern id.
- `make gate` passes, and the two-commit order (red, then green) is in `git log`.

## Decisions left open, asked of James before writing

1. The fallback line Gus says when the guard fires (in `spec.md`'s voice).
2. Whether a guard hit counts as a tier change (card 06) or only a trace mark.
3. Whether paraphrases are matched by patterns only, or by a second small model call when the pattern misses (slower; the default is patterns only until a miss is measured).

## Files this card may touch

`candidate_line/guard/` (new), `candidate_line/hooks.py` (the `before_speak` body only), `tests/test_guard_red_proof.py`, `docs/decisions/DR-020-the-guard.md`.

## Teach-back, after

James explains: which string the guard reads and why that one, why the test was committed red first, and what the caller hears when it fires. Grade against `hooks.py`, the guard file and the two commits.
