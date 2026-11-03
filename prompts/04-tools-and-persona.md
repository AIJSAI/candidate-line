# Prompt card 04: the tools and the persona

Work item: give the brain its tools (the actions `spec.md` lists under May and Must ask first, over the synthetic data) and its persona, so a caller can get a real answer and a real action from the line; wire `on_tool` and the `cites` path.
Record: `docs/decisions/DR-019-tools-and-persona.md` (live). The hooks exist and are empty (`LineHooks` in `candidate_line/hooks.py`, DR-008); the persona file holds a placeholder (`SYSTEM_PROMPT` in `candidate_line/persona.py`, read by every path through `Settings.system_prompt()`).

## Paste this

> Read `AGENTS.md`, `spec.md`, `candidate_line/hooks.py`, `candidate_line/turn.py`, `candidate_line/brain/provider.py`, `candidate_line/persona.py` and `data/`. Implement one tool per May and Must-ask-first line in `spec.md`, each a typed Python function over the files in `data/`, observed through `LineHooks.on_tool`, with the Must-ask-first tools returning a "needs a person" result instead of acting. The tool loop in `turn.py` fills `TurnResult.tools_called`, `cited` and `state`, which the eval checks read. Write the persona's system prompt as `SYSTEM_PROMPT` in `candidate_line/persona.py` from the brief below, with the cite-or-refuse rule inside it. Run `make eval` and show me the cases that moved. Touch only the files named below.

## The persona brief (Gus)

- Dry, unhurried, plain words; one or two sentences a turn, because a caller is waiting and output tokens set the latency (DR-003). No lists, no markdown, no emoji: the words are spoken.
- Never evaluates a person, a take-home, an interview or a chance. The refusal line comes from `spec.md`.
- Answers process questions only from the FAQ sections the retrieval step hands it, and says the section it used in plain words ("that is in the scheduling section"); otherwise the refusal line. Never from memory.
- Confirms a code by reading it back as digits, because the transcriber hears digits as numbers with commas and "code" as "coat" (DR-006); never reads a PIN back (it says the PIN was received), since a spoken PIN on a phone is a Never line in most specs.
- Says what it is doing before a tool runs when the tool takes a moment, and says what it did after.

## The tools (shape, not function)

Each tool: a name, a one-line description the model reads, a typed signature, a pure function over `data/`, a trace span through card 03's `tool` field, and an eval case from card 02 that exercises it. A Must-ask-first tool never mutates; it returns the request for the human, and card 06 decides where it goes.

## Acceptance criteria

- Every May line has a tool; every Must-ask-first line has a tool that returns a hand-off, never an action.
- The persona prompt is under 300 words, holds the Never list verbatim from `spec.md`, and the brevity rule.
- A turn with a tool stays inside the DR-001 budget at the median across the card 02 happy paths, measured with `make eval`'s latency column.
- The `cites` checks in `evals/` pass for the cases where the answer exists, and the refusal cases pass where it does not.
- `make gate` passes.

## Decisions left open, asked of James before writing

1. Retrieval: whole FAQ in the prompt (1,100 words, cheap and simple) or a section lookup by keyword first (smaller prompt, one more place to be wrong). Ask him; the default is whole FAQ until a measurement says otherwise.
2. How Gus names a cited section aloud: by its id ("F3.2") or by its title.
3. Whether a booking tool writes to `data/slots.yaml` on disk or to an in-memory copy reset per run.

## Notes from the bake-off, 2026-11-02 (DR-001, DR-003)

- The bake-off persona already says "one or two short sentences"; arm A's replies still ran 192 characters a reply (about 45 tokens) and the recording's median turn was 2,060 ms. DR-003 measured 901 ms at a 60-token cap. The brevity rule is a latency decision: set the reply cap beside the persona (`run_turn`'s `max_tokens`, 200 today) and read `make eval`'s latency column before and after.

## Files this card may touch

`candidate_line/tools/` (new), `candidate_line/persona.py`, `candidate_line/hooks.py` (the body of `LineHooks.on_tool` only), `candidate_line/turn.py` (the tool loop only), `tests/test_tools.py`, `docs/decisions/DR-019-tools-and-persona.md`.

## Teach-back, after

James explains: how a spoken request becomes a tool call and comes back as speech, why Must-ask-first tools never act, and where the cite-or-refuse rule lives. Grade against `turn.py`, `hooks.py` and the persona file by line.
