# DR-018: The spans each path writes

Status: DRAFT
Built: live (rebuilt 2026-11-04 evening, after the session, from James's 16:26 CT test call)
Commit: this commit

## What it is

Every turn on every path writes its spans into the trace store through `ctx.store`, so the cockpit and `make trace last` show a call step by step. The writes live in `candidate_line/turn.py` (the loop, every path), `candidate_line/hooks.py` (the kill switch and the call-end write-up) and `candidate_line/telephony/media.py` (the ears and the mouth on a call).

## The decision

A turn writes, in order:

- `transcribe/heard` in text mode and the evals; on a call, `transcribe/final` from media.py, one per final transcript, with the transcriber's confidence and lag, and a dropped filler marked `dropped: filler`.
- `model/<model id>` per model call: ms, tokens in and out, the text; meta holds the provider, the stop reason, cache reads and writes, `cost_usd` from `rates.py`, and the tools it asked for.
- `tool/<name>` per tool: ms and one line built from named result fields; meta holds the arguments (the code as ACME-dddd, other free text digit-masked, a pin key masked by the store), the result's keys and `is_error`. `book_slot` adds `slot`, `slot_id` and `invited_at` for card 07.
- `escalation/<tier>` per hand-off, a repeat marked `duplicate`.
- `cite/<ids or none>` with `refused` in its meta, when the turn cited or refused; a refusal that had fetched sections keeps them under `returned`.
- `speech/spoken` in text mode and the evals; on a call, `speech/polly` after the audio is out, with the first audio gap.
- `hook/guard`: each sentence's label, or "clean".
- `tier/<1|2|3>`: the reason; meta holds `turn_ms`, `model_ms`, `tool_ms`, `model_calls` and the tools.

Outside a turn: `kill/switch` when the kill switch closes a call, `hook/superseded` when the caller's next words drop a turn and its tool effects are taken back (its tool and tier spans stay, so this one says they were never heard), and `escalation/3` once at the call's end when tier-3 reasons gathered. The span texts that carry the caller's or the model's words (transcribe, model, speech) have each run of three or more digits masked, written or spoken (`mask_spoken_digits`); the tool and escalation spans are built from named fields and keep the code and the slot ids, and the free text in a hand-off has its digit runs taken out at the tool (`_scrub` in `candidate_line/tools/actions.py`); the store masks any meta key containing "pin" (`candidate_line/traces/store.py`).

## The alternative rejected, and why

- One span per turn with everything in its meta: the cockpit reads steps, and a tool's time inside a model span cannot be read off.
- Masking the PIN by its value: the PIN is known only after a match, and a wrong PIN belongs to no record. A digit-run mask holds before any match.
- Writing the speech span before the audio: a slow store write would delay the caller's first byte.

## What would change the decision

The scorecard (card 07) needing a field the spans lack. A store write measured inside the latency budget.

## Evidence

- Every failure of the six live eval runs (DR-017) was diagnosed from `var/eval-traces.sqlite` alone, with no rerun: the `pin-03` hit inside CL-022's verify reply, the eight-heading sweep in CL-032 and its `cite` span carrying eight ids with `refused: false`.
- `tests/test_turn.py`, `tests/test_traces.py` and `tests/test_media.py` cover the order and the masking; `uv run pytest -q` gave 366 passed on 2026-11-04.
- The cost of the wide mask: the code is masked in the heard and model spans too (ACME-****), and stays readable only in the `verify_caller` tool span.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
