# DR-010: The eval runner

Status: DRAFT
Built: pre-built (PREBUILT.md row 9)
Commit: (filled when the item lands)

## What it is

`make eval` and `make gate`: the harness that runs case files through the same turn loop as the phone and says pass or fail in a way no one can argue with. Today it has zero cases, on purpose.

## The decision

- **Zero cases before Wednesday.** `evals/cases/` holds a `.gitkeep`; the runner prints `0 cases` and exits 0. The first ten cases are written in the room from the spec, then eleven, then twelve. The runner being pre-built and the cases not is the line between tooling and judgment (PREBUILT.md).
- **Deterministic checks are the bar; a model judge is a spot check.** A case is turns, and each turn carries checks the runner evaluates with no model in the loop: `heard_matches` and `spoken_matches` (regular expressions over what the brain heard and what the caller heard), `spoken_not_matches` (the guard's lexicon), `cites` (a section id like `F3.2` in Gus's words). Three more are declared in the schema and refuse until their components land live: `tool_called`, `state` and `tier`. A case may carry a `judge` block with a question for a model; it is never what passes or fails a case.
- **A check the runner cannot evaluate yet is pending, loudly.** It says which check and which card lands its component, so a case never passes because a check was skipped; and it is not a failure either, so the gate can be read between card 02 and card 06. (Amended 2026-11-02 evening after a timed dry run of card 02: as first written, these checks failed, and with them `make gate` could not be green from card 02 until card 06, which contradicted AGENTS.md rule 8. Now `tool_called`, `state` and `tier` read fields on `TurnResult` that the tool loop and the tier rule fill, `None` meaning not landed; `cites` also accepts the id carried on the turn, so Gus can say the section's title aloud. The same dry run found the runner always spoke with the placeholder prompt and empty hooks, so card 04's persona and card 05's guard would never have reached an eval: the runner, text mode and the phone now read `Settings.system_prompt()` and `default_hooks()`.)
- **Strict loading.** An unknown key, an unknown check, a turn with both or neither of `user` and `silence_seconds`, or two cases with one id are refused with the file name. AGENTS.md rule 4 forbids bending a case to make a run pass; a case the runner silently misreads is the quietest bend.
- **Two kinds of case.** `boundary` is an absolute bar: one failure fails the run. `regression` is a gate against `evals/baseline.json`: the pass rate may not fall below the committed one, and the cost per call may not rise more than 20 percent above it. The baseline file is written by its own work item after the first green run and changes only inside a work item that names it.
- **The cost line is computed from tokens and the saved rates**, never from a bill: `candidate_line/evals/rates.py` holds USD per million tokens for the three models in play, read from the pricing pages saved on 2026-11-01 (DR-003), and a model with no row makes the line say "no priced model turns" rather than guess.
- **`make gate` is the tests, then the evals, then the cost line.** A work item is done when it passes (AGENTS.md rule 8).

## The alternative rejected, and why

- **A model as the judge of record.** It is the thing being tested; a judge that shares its blind spots passes them. Spot checks are fine, bars are not.
- **A runner that skips checks it does not understand.** The quiet green. Refusal is the only safe default when the cases carry the rules.
- **pytest parametrized over YAML.** Pytest is already the test runner; the eval runner needs a baseline comparison, a cost line and a report a recruiter can read, and it needs to run the same loop as the phone, not a fixture of it.
- **A cost line from Cost Explorer.** Hours of lag and Marketplace line items; tokens times a dated rate is instant and auditable to a saved page.

## What would change the decision

Tools landing (then `tool_called` and `state` evaluate against the tool log and the fixtures, and `on_tool` is where the log comes from); tiers landing (then `tier` evaluates against the escalation rule); the probe caller (then `channel: voice` cases run against a transcript of a real call, scored by the same checks); a baseline with enough regression cases that a 20 percent cost band is too loose or too tight (then the band is a measured change to this record).

## Evidence

- `make eval`, 2026-11-01: `0 cases in evals/cases; nothing to run`, exit 0. `make gate`: 33 tests passed, then the same eval line.
- `tests/test_evals.py`: zero cases exit 0; a good case passes on the echo brain; a failing boundary case fails the run and names the match; checks that need live components fail with the sentence; unknown keys, unknown checks, malformed turns and duplicate ids are refused; the baseline gates on pass rate.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
