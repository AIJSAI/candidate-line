# DR-012: The trace store and the cockpit's list view

Status: DRAFT
Built: pre-built (PREBUILT.md row 11)
Commit: 99a7d58

## What it is

Where every call's record lands, and the one page that lists the calls for the recruiter. The spans themselves (transcription, model, tools, speech), the kill switch and the override log are written live on Wednesday; today the store, its schema, its masking and its pages exist and are tested.

## The decision

- **One SQLite file, `var/traces.sqlite`, ignored by git** (`TRACE_STORE_PATH` overrides it). Three tables: `calls` (one row per call: channel, start and end, the masked caller, provider and model, outcome), `spans` (numbered per call: kind, name, milliseconds, tokens in and out, characters, seconds, text, a JSON `meta`), and `escalations` (DR-013's rows with their reply). No server, one file to copy or delete, readable with any SQLite tool.
- **Text and metadata only, never audio.** A span that is handed bytes is refused with a `TypeError`; the kinds are a closed list (`transcribe`, `model`, `tool`, `speech`, `hook`, `escalation`).
- **Masking happens in the store, in the one function that accepts a caller's number.** `start_call(caller=...)` keeps the last four digits as `***-***-0142` before the row is written; nothing else in the code takes a number, so no span can carry one. Four digits are enough to tell two callers apart on a page and useless for calling anyone.
- **The cockpit is its own app on its own port** (`make cockpit`, loopback `127.0.0.1:8001`), never behind the tunnel and never for a candidate: a list of calls (started, channel, masked caller, brain, span count, model milliseconds, escalations, outcome), one page per call with its spans and escalations, and a reply box per escalation that logs who did what, which is how DR-013's loop closes. Two pages, every value escaped in one place, no template engine, no JavaScript.
- **`make trace last` prints the latest call's spans in the terminal**, for the projector when the cockpit is not open.

## The alternative rejected, and why

- **An OpenTelemetry collector or a hosted tracing product.** A new account, a new secret, and the recruiter's page would be a vendor's; the room needs a list of calls, not a span waterfall, and the export can be added as a span sink later without changing a writer.
- **JSON lines on disk.** Fine for spans, poor for the list view (one call's totals mean reading every line) and for the reply that must update a row.
- **Masking at the call edge (in the webhook) instead of the store.** Two writers would each have to remember; one chokepoint cannot forget.
- **A cockpit route inside the phone app.** The phone app is behind a public tunnel; a recruiter's page with transcripts on it is not.

## What would change the decision

The spans landing live (then `run_turn` writes `model` and `hook` spans and the media path writes `transcribe` and `speech` spans, each at the moment it finishes, and the kill switch and override log write `hook` spans with `meta`); a second machine (then the file becomes a Postgres table and the page stays); a recruiter wanting search or export (then one more query, not a product).

## Evidence

- `uv run pytest -q tests/test_traces.py`, 2026-11-01: masking keeps four digits and never leaks the number into a row; spans number in order; bytes and unknown kinds are refused; the cockpit lists, escapes a `<script>` in a transcript, logs a reply through the form, and answers 404 for an unknown call or escalation; `make trace last` prints the latest call.
- `make trace last` on the empty store: one line saying so, exit 0. `.gitignore` carries `var/`.

- **Amended 2026-11-02 evening, after the timed dry run of card 03.** Three things the room would have hit: every path ran its turns against one default store, so `make eval` wrote 39 calls into the store `make trace last` reads and the room's text call was no longer the last; the byte refusal caught `bytes` in `text` only (a `memoryview`, bytes as a span name, and bytes inside `meta` got through, the last refused only by `json.dumps` by accident); and nothing ever called `end_call`, so every outcome stayed empty. Now the turn context carries its store (`TurnContext.store`, `None` = no tracing), each path opens its own and starts and ends the call (the phone at `/voice` with the masked number and at the stream's stop with the turn counts; text mode at its start and `/quit`; the eval runner on `var/eval-traces.sqlite`, `EVAL_TRACE_STORE_PATH`, with the verdict as the outcome), and the refusal checks text, name and the whole of `meta`. The spans themselves are still card 03's.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
