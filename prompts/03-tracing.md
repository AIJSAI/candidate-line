# Prompt card 03: tracing the turn

Work item: write the spans from the turn loop into the trace store, so every call in the cockpit shows what was heard, what was said, which section was cited, how long each hop took and what it cost.
Record: `docs/decisions/DR-018-tracing.md` (live). The store and the cockpit are pre-built (DR-012); the spans are not.

## Paste this

> Read `AGENTS.md`, `spec.md`, `candidate_line/turn.py`, `candidate_line/traces/store.py` and `candidate_line/traces/cockpit.py`. Wire the turn loop so that each turn writes one span per hop, through the store's own functions only, with the fields listed in this card. Add a test that runs one turn against the echo brain and reads the spans back. Then run `make text`, speak three turns, run `make trace last`, and show me the output. Touch only the files named below.

## The spans, per turn

- `heard`: the final transcript, its confidence if the transcriber gives one, and the milliseconds from end of speech to the final.
- `brain`: provider, model, input and output tokens, model latency, and the cost from the rate table in `candidate_line/evals/rates.py`.
- `cited`: the section ids the reply cites, or `none` with the refusal flag set.
- `spoken`: the text handed to speech, the bytes synthesised, the milliseconds to first byte.
- `guard` (card 05 fills it): the lexicon hit or `clean`.
- `tier` (card 06 fills it): the tier assigned and why.

A span never holds audio bytes (the store refuses them: `store.py`), never a full phone number (the store masks at `start_call`), never a secret.

## Acceptance criteria

- One turn in text mode produces exactly the spans above, in order, under one call id.
- `make trace last` shows the turn with its hop latencies adding up to the measured turn within 50 ms.
- A span carrying bytes is refused by the store and the test proves it.
- `make test` passes, and `make eval`'s red is exactly the list DR-017 named (rule 8: the gate turns green at card 04).

## Decisions left open, asked of James before writing

1. Whether the cockpit's reply form (the recruiter override) writes its own span in this card or waits for card 06.
2. The retention of `var/traces.sqlite` between build days: keep, or wipe at the start of each day.

## Files this card may touch

`candidate_line/turn.py`, `candidate_line/traces/store.py` (new span types only, never the masking or the refusal), `tests/test_traces.py`, `docs/decisions/DR-018-tracing.md`.

## Teach-back, after

James explains: what a span is, where the caller's number is masked and why there, and how the hop latencies become the latency table in DR-001. Grade against `store.py` and `turn.py` by line.
