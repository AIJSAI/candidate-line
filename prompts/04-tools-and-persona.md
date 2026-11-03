# Prompt card 04: the tools and the persona

Work item: give the brain its tools (the actions `spec.md` lists under May and Must ask first, over the synthetic data) and its persona, so a caller can get a real answer and a real action from the line; wire `on_tool` and the `cites` path.
Record: `docs/decisions/DR-019-tools-and-persona.md` (live). The hooks exist and are empty (`LineHooks` in `candidate_line/hooks.py`, DR-008); the persona file holds a placeholder (`SYSTEM_PROMPT` in `candidate_line/persona.py`, read by every path through `Settings.system_prompt()`).

## Paste this

> Read `AGENTS.md`, `spec.md`, `candidate_line/hooks.py`, `candidate_line/turn.py`, `candidate_line/brain/provider.py`, `candidate_line/persona.py` and `data/`. Implement one tool per May and Must-ask-first line in `spec.md`, each a typed Python function over the files in `data/` with a `ToolSpec` (name, one line, JSON Schema) the model reads, observed through `LineHooks.on_tool`, with the Must-ask-first tools returning a "needs a person" result instead of acting. The brain already speaks the tool channel natively on both providers (`Brain.reply(..., tools=...)` returns `Reply.tool_calls`; an assistant `Message` carries its `tool_calls`, a `tool` message carries their `ToolResult`s; DR-003): write the loop in `run_turn` (while the reply carries tool calls, run them, append the assistant message and the tool-results message, call the brain again), never a text protocol. The loop fills `TurnResult.tools_called`, `cited` and `state`, which the eval checks read, and writes one `tool` span per call through `ctx.store` (name = the tool, text = a one-line result, meta = the arguments and the result's keys; the booking tool's carries `invited_at` and `slot`, which card 07's invite-to-booked number reads); `ctx.data` is the per-call scratch (the verified candidate, the in-memory slots). Write the persona's system prompt as `SYSTEM_PROMPT` in `candidate_line/persona.py` from the brief below, with the cite-or-refuse rule inside it. Run `make eval` and show me the cases that moved. Touch only the files named below.

## The persona brief (Gus)

- Dry, unhurried, plain words; one or two sentences a turn, because a caller is waiting and output tokens set the latency (DR-003). No lists, no markdown, no emoji: the words are spoken.
- Never evaluates a person, a take-home, an interview or a chance. The refusal line comes from `spec.md`.
- Answers process questions only from the FAQ sections the retrieval step hands it, and says the section it used in plain words ("that is in the scheduling section"); otherwise the refusal line. Never from memory.
- Confirms a code by reading it back as digits, because the transcriber hears digits as numbers with commas, "code" as "coat" and "ACME" as "acne" (DR-006; the `on_turn` normaliser maps those before the brain sees them); never reads a PIN back (it says the PIN was received), since a spoken PIN on a phone is a Never line in most specs.
- Says what it did after a tool ran. A holding line before a slow tool is voice-path work for a later card, because `run_turn` returns one reply after the tools have run.

## The tools (shape, not function)

Each tool: a name, a one-line description the model reads, a typed signature, a pure function over `data/`, a trace span through card 03's `tool` field, and an eval case from card 02 that exercises it. A Must-ask-first tool never mutates; it returns the request for the human, and card 06 decides where it goes.

## Acceptance criteria

- Every May line has a tool; every Must-ask-first line has a tool that returns a hand-off, never an action.
- The persona prompt is under 300 words (the FAQ text it carries is not counted), holds the Never list verbatim from `spec.md` (the rule sentences, without their case references), and the brevity rule.
- A turn with a tool stays inside the DR-001 budget at the median across the card 02 happy paths, measured with `make eval`'s brain-latency line (text mode: the brain only; the phone adds the speech hops). A tool turn is two model calls; the reply cap and the prompt's size are the levers.
- The `cites` checks in `evals/` pass for the cases where the answer exists, and the refusal cases pass where it does not.
- `make gate` passes.

## Decisions left open, asked of James before writing

1. Retrieval: whole FAQ in the prompt (1,100 words, cheap and simple) or a section lookup by keyword first (smaller prompt, one more place to be wrong). Ask him; the default is whole FAQ until a measurement says otherwise.
2. How Gus names a cited section aloud: by its id ("F3.2") or by its title.
3. Whether a booking tool writes to `data/slots.yaml` on disk or to an in-memory copy reset per call.
4. Whether a booking is written when the tool runs or only after the caller confirms it out loud. A turn can be superseded before Gus speaks (DR-006) and its tools have already run by then; the default is after the confirmation, so a superseded turn books nothing. That choice adds a confirmation turn to the booking and move cases, which is card 02 re-entered. Re-enter card 02 for the baseline right after this card's gate goes green: two minutes, and from then on the regression bar can fail something.

## Notes from the bake-off, 2026-11-02 (DR-001, DR-003)

- The bake-off persona already says "one or two short sentences"; arm A's replies still ran 192 characters a reply (about 45 tokens) and the recording's median turn was 2,060 ms. DR-003 measured 901 ms at a 60-token cap. The brevity rule is a latency decision: set the reply cap beside the persona (`REPLY_MAX_TOKENS` in `persona.py`, 200 today) and read `make eval`'s brain-latency line before and after.
- The dry run of this card (2026-11-02) on a text protocol took 23 minutes, made two to four model calls a tool turn at about 3,000 input tokens each with the whole FAQ in the prompt (cost per eval run up 13 times), measured a 2,316 ms median brain time on the happy paths, and once spoke a caller's PIN when its parser missed. The native channel removes the parser; the Anthropic brain marks the system prompt for the prompt cache (`cache_control`), and the cost line shows cached input tokens once the prompt is past the model's minimum cacheable size; the FAQ's size and the reply cap are the levers that remain. The second pass on the native channel took 15 minutes, zero boundary failures, median brain time 1,165 ms over 52 model turns. Two things it learned about the cap: a tool call's arguments spend output tokens, so a cap of 100 cut a `verify_caller` call off before its PIN and a cap of 250 fit two complete calls; the lever on brevity is the persona's words and a cap that leaves room for the largest tool input. And the eval cost line now prices cache reads and writes and prints them; the first replay showed 112 uncached against 3,863 cached input tokens on a tool turn.

## Files this card may touch

`candidate_line/tools/` (new), `candidate_line/persona.py`, `candidate_line/hooks.py` (the body of `LineHooks.on_tool` only), `candidate_line/turn.py` (the tool loop only), each plus the imports it needs, `tests/test_tools.py`, `docs/decisions/DR-019-tools-and-persona.md`.

## Teach-back, after

James explains: how a spoken request becomes a tool call and comes back as speech, why Must-ask-first tools never act, and where the cite-or-refuse rule lives. Grade against `turn.py`, `hooks.py` and the persona file by line.
