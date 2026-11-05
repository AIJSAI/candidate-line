# DR-019: The tools, the native tool channel and Gus's brief

Status: DRAFT
Built: live (rebuilt 2026-11-04 evening, after the session, from James's 16:26 CT test call)
Commit: this commit

## What it is

Seven tools over `data/` and the ledger (`candidate_line/tools/`), one per May and Must-ask-first line of the spec, and Gus's brief with the FAQ's index (`candidate_line/persona.py`). The turn loop runs the tools on the model's own tool channel.

## The decision

- **The tools:** `verify_caller(code, pin)`, `list_open_slots(day?)`, `book_slot(slot_id)`, `move_slot(preferred?)`, `answer_question(section_ids)`, `request_callback(best_time?, reason?)`, `end_call()`. Each returns a `ToolOutcome`; `run_tool` never raises, so a bad argument is one sentence the model recovers from. `move_slot` and `request_callback` change nothing a person must decide and return the hand-off.
- **The native channel:** `Brain.reply(tools=TOOL_SPECS)`, at most five model calls a turn, folded into one Reply so the latency and cost lines count the whole turn. A booking said in one breath is verify, list, book and a reply, four calls, so the fifth is the margin; a turn that reaches the cap takes back what its tools did and says the recovery line.
- **The ledger:** the data files plus an overlay in `var/state.json`, written through under a lock. `STATE_PATH=:memory:` keeps the evals and the walks off it.
- **The normaliser** in `on_turn` (`candidate_line/tools/codes.py`): "acne 3,233 PI 96 83" reaches the model as "ACME-3233 PIN 9683", and since this work item "application 3233" as "application code ACME-3233".
- **The whole-FAQ-index decision:** the brief carries the FAQ's index (each heading with its section ids and titles), never its text; `answer_question` returns the sections. Every answer then carries the ids it came from (spec 6), and the prompt stays one cacheable block of about 2,140 tokens with the tool specs.
- **The fixed lines are said by code:** refusal, fallback, stop, kill, holding, hold limit and recovery.
- **What the eval runs changed (DR-017):** the brief says "application 4821" is the code (an example that is no record's code); it no longer says "your PIN was received", which the guard's `pin-03` rule caught; it names the section in a model sentence; it tells the model to book a named day and time at once and to read any other pick back first (the review walk saw a read-back on 2 of 2 named picks); it tells the model to send every process question through the tool, pay and other candidates named, with an empty list when no section fits or the sections returned do not answer, so the loop says the refusal line and cites nothing; it takes a callback at once. The review walk of 2026-11-04 found the model refusing out-of-FAQ questions in its own words after the first turn (5 of 5), so the loop also says the refusal line itself when a reply with no other tool's result refuses in its own words, cuts a reply to two sentences plus the one naming a section, and names aloud any section `answer_question` returned that the reply left out (an eval run after the review named F5.1 and dropped F2.1). `verify_caller` refuses a second candidate's code once a caller is verified, keeps the PINs given on the call for the guard, and on the second miss says to offer a callback; `book_slot` returns F3.1's confirmation and cites it; `list_open_slots` takes the caller's time zone (F3.4). `answer_question` no longer offers a heading "for all of it", and `request_callback` says never to ask for a reason or a time first. The brief is 299 words by `split()`, under card 04's 300.
- **Two misses stop the checking** (2026-11-04 evening, proposed to James with the list he answered; spec 3.1 changed first). `MAX_VERIFY_ATTEMPTS` is 2, down from 3: the second miss says to offer a callback and that no other code or PIN is checked on the call, and a third `verify_caller` on that call answers with the same note and checks nothing, the right pair included. Every further try would be one more guess at someone's PIN. The PIN a caller insists on is still kept in the call's scratch, so the guard's `pin-heard` check catches it if Gus says it back. The brief already said "Second miss: offer a callback", so it did not change. `tests/test_tools.py` holds it.

## The alternative rejected, and why

- The whole FAQ in the prompt, card 04's default: its dry run measured about 3,000 input tokens a call and a 2,316 ms median, with nothing to show which section an answer came from.
- A text protocol for tools: its dry run once spoke a PIN when the parser missed.
- Asking the model to say the refusal line: it reworded it in five runs of five (CL-032). The empty list makes the loop say it.

## What would change the decision

A cite to the wrong section, measured; the FAQ outgrowing an index; the brain's median leaving DR-001's budget.

## Evidence

- Happy paths on the first baseline run (2026-11-04 23:43 UTC, before the review's fixes): median brain time per turn 1,544 ms over 14 cases (CL-021 to CL-023, CL-025 to CL-031, CL-033, CL-034, CL-038, CL-039), best 1,383 ms, worst 2,111 ms. Method: each case's median turn on the brain's own clock, a turn's model calls summed, from the runner's report. All 64 model turns: median 1,466 ms, worst 2,633 ms.
- DR-001's budget is 2,000 ms for the median turn, from the caller's last word to the first audio byte. The brain alone is inside it. With arm A's measured floor of 740 to 780 ms the sum is about 2,300 ms, over it [inference: the floor was measured with no model, and a tool turn speaks only after its last model call]. The phone's own number is the probe caller's to measure.
- Cost: 0.00024 USD a call over 36 priced cases (`rates.py`: Haiku 5.5 at 0.10 and 0.50 USD per million tokens, cache reads at a tenth).
- Text walk, 2026-11-04 (scratch store, in-memory ledger): "I'm calling about application 3233 PI 9683" was verified at once, then a booking by day and time, F2.3 named aloud, a move handed off, and "stop".

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
