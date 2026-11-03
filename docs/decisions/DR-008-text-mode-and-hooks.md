# DR-008: Text mode and the four hooks

Status: DRAFT
Built: pre-built (PREBUILT.md row 5)
Commit: (filled when the item lands)

## What it is

The line without a phone (`make text`), and the four places in the turn loop where Wednesday's guard, observer, kill switch and override log plug in without anyone rewriting the loop.

## The decision

- **One turn function for every channel.** `candidate_line/turn.py`'s `run_turn` is what the text REPL calls, what the media stream will call from item 3, and what the eval runner drives. A rule added in the room holds in all three at once.
- **Four hooks with one contract each** (`candidate_line/hooks.py`): `on_turn` sees the caller's words before the brain and may rewrite them (spoken digits, codes); `before_speak` sees Gus's words before the caller and may replace them, with `""` meaning say nothing, which is how the guard and the kill switch will act; `on_silence` is told how long the caller has been quiet and may hand Gus a line; `on_tool` sees every tool call after it ran and only observes, which is where the traces and the override log begin. Each returns `None` for "no change", so an empty hook is four one-line methods (`NoHooks`).
- **A chain, in order.** `HookChain` runs hooks in sequence and each sees the previous one's result, so the kill switch can sit before the guard and the observer after both, and the order is read in one list.
- **The history keeps what the caller heard, not what the model wrote.** When `before_speak` replaces a sentence, the replacement goes into the transcript the next turn builds on; the model never sees its own blocked words as if they had been said.
- **Text mode is the same loop with stdin and stdout for ears and mouth.** It prints the provider, the model and each turn's latency and tokens, so `make text` doubles as the cheapest latency probe; `/silence N` runs the silence hook as if N seconds passed; `/quit` ends it. The brain and model come from the environment, as everywhere (`BRAIN_PROVIDER`, `BEDROCK_MODEL_ID`), and a provider failure is one line with the switch written next to it, not a traceback.
- **A placeholder persona** (`candidate_line/persona.py`) until the room writes Gus: it names him and tells him to decline anything about a person. It has no FAQ and no tools, so it will invent process facts, which the live build's cite-or-refuse rule exists to stop.

## The alternative rejected, and why

- **Subclassing the loop per channel.** Three loops drift; the room has ninety minutes.
- **One `on_message` hook with a mode flag.** The guard and the observer need different moments (before the caller hears a thing, after a tool ran); four names say which moment, and a flag would need a document.
- **Hooks that can throw to stop a turn.** A guard that raises leaves the caller in silence; a guard that returns a replacement leaves the caller with a sentence. Stopping the call is the kill switch's line, also a replacement.
- **A text mode that bypasses the hooks for speed.** Then the failure drill would run a different line from the one that was killed.

## What would change the decision

Tool use in the brain (item 3 onward): `on_tool` already has the shape; `Brain.reply` grows a tools argument and the loop runs the tool round trip, with `on_tool` called once per call. Streaming by sentence for Polly: `before_speak` runs per sentence, so a guard that needs the whole reply would move the cut after the hook; that is a measured latency decision for DR-006.

## Evidence

- `uv run pytest -q`, 2026-11-01: the turn and text-mode tests cover the no-hook pass-through, `on_turn` rewriting, `before_speak` replacing and silencing, the history keeping the replacement, later hooks seeing earlier replacements, the silence threshold and the REPL's two commands.
- `make text` live on 2026-11-01 with `BEDROCK_MODEL_ID` set to Haiku 4.5 (the only Claude this account's Bedrock quota allows today, DR-003): "Hi, how long is the first round?" answered in 823 ms (73 tokens in, 23 out) with an invented "about 30 minutes", which is the placeholder persona's known flaw; "Do you think I am a strong candidate?" answered "I don't evaluate people" in 688 ms. With the default model (Haiku 5.5) the same command printed the quota's AccessDeniedException in one line and the switch hint.

- **Amended 2026-11-02 evening, after the timed dry run of card 05.** `before_speak` runs once per turn with the whole reply (`run_turn`), not once per sentence as this record first said; the media path splits into sentences afterwards for Polly. A guard that must replace one sentence splits inside itself with the same `split_sentences`, which the card now says. The hooks every path runs are `LineHooks` through `default_hooks()`; `NoHooks` stays empty for the tests.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
