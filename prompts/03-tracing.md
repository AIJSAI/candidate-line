# Prompt card 03: tracing the turn

Work item: write the spans from the turn loop into the trace store, so every call in the cockpit shows what was heard, what was said, which section was cited, how long each hop took and what it cost.
Record: `docs/decisions/DR-018-tracing.md` (live). The store and the cockpit are pre-built (DR-012); the spans are not.

## Paste this

> Read `AGENTS.md`, `spec.md`, `candidate_line/turn.py`, `candidate_line/traces/store.py` and `candidate_line/traces/cockpit.py`. Wire the turn loop so that each turn writes one span per hop through `ctx.store` (the `TraceStore` every path already opens and hands to the turn context: the phone and text mode on the room's store, the eval runner on its own file, `None` in a unit test, which writes nothing), using the store's own functions only, with the fields listed in this card; `start_call` and `end_call` are the path's job and already happen. Add a test that runs one turn against the echo brain with a `TraceStore(":memory:")` and reads the spans back. Then run `make text`, speak three turns, run `make trace last`, and show me the output. Touch only the files named below.

## The spans, per turn

In reading order, not clock order (the guard's verdict is known before the words are spoken). The fields only the voice path knows (the transcriber's confidence and its end-of-speech-to-final time, the bytes synthesised and the time to the first byte) are filled by `media.py` on a call and are null in text mode. Each span's `name` is the word below and its `kind` is the store's (`SPAN_KINDS` in `store.py`: heard is `transcribe`, brain `model`, cited `cite`, spoken `speech`, guard `hook`, tier `tier`); the store inserts and never updates. On a call the heard and spoken spans are written by `media.py` once it knows the voice fields (the final's `confidence` and `final_lag_ms` ride on `Heard` from `speech.py`; the bytes and the first-byte time are known in `speak`), so on a voice channel the turn loop parks what it knows in `ctx.data` and writes those two itself only in text mode. The turn's total and the sum of its hops go in the last span's meta, and `make trace last` prints the meta column. The `tool` span is card 04's: its loop writes one through `ctx.store` per call, never `on_tool`.

- `heard`: the final transcript, its confidence if the transcriber gives one, and the milliseconds from end of speech to the final.
- `brain`: provider, model, input and output tokens, model latency, and the cost from the rate table in `candidate_line/evals/rates.py`.
- `cited`: the section ids the reply cites, or `none`; the refusal flag is true when the reply is the spec's refusal line and null until card 04 makes refusals explicit.
- `spoken`: the text handed to speech, the bytes synthesised, the milliseconds to first byte.
- `guard` (card 05 fills it; written now as `clean`): the lexicon hit or `clean`.
- `tier` (card 06 fills it; written now with a null tier and reason): the tier assigned and why.

A span never holds audio bytes (the store refuses them: `store.py`), never a full phone number (the store masks at `start_call`), never a secret.

## Acceptance criteria

- One turn in text mode produces exactly the spans above, in order, under one call id (guard and tier as placeholders until cards 05 and 06).
- `make trace last` shows the turn with its hop latencies adding up to the measured turn within 50 ms.
- A span carrying bytes is refused by the store and the test proves it.
- `make test` passes, and `make eval`'s red is exactly the list DR-017 named (rule 8: the gate turns green at card 04). A case outside that list that is red on one run and green on the next is a pattern that lets a quoted phrase through on some replies ("I can't tell you that you're a strong candidate" in the dry run): note it for card 02's re-entry and run once more; it is not this card's stop.

## Decisions left open, asked of James before writing

1. Whether the cockpit's reply form (the recruiter override) writes its own span in this card or waits for card 06.
2. The retention of `var/traces.sqlite` between build days: keep, or wipe at the start of each day (`make eval` writes to `var/eval-traces.sqlite`, so the room's store holds only the room's calls).
3. Whether the `heard` span masks a spoken PIN (four digits after the word PIN) before it is stored; the store masks the caller's number at `start_call` and nothing else. The default is yes.

## Files this card may touch

`candidate_line/turn.py`, `candidate_line/traces/store.py` (new span kinds only, never the masking or the refusal), `candidate_line/telephony/media.py` (the heard and spoken spans on a call, after the first byte), `candidate_line/traces/cli.py` (printed columns only), `tests/test_traces.py`, `docs/decisions/DR-018-tracing.md`.

## Teach-back, after

James explains: what a span is, where the caller's number is masked and why there, and how the hop latencies become the latency table in DR-001. Grade against `store.py` and `turn.py` by line.
