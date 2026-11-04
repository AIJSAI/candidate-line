# Prompt card 06: the tiers and the observer

Work item: assign every turn a tier (handled alone, handed to a person now, written up afterwards), post the hand-offs through the escalation queue, give the recruiter's cockpit its override, and add the kill switch.
Record: `docs/decisions/DR-021-tiers-and-observer.md` (live). The queue and its poster are pre-built (DR-013); the cockpit's list view and reply form exist (DR-012); the tier rule is not written.

## Paste this

> Read `AGENTS.md`, `spec.md` (section 7, the tiers), `candidate_line/escalation.py`, `candidate_line/traces/cockpit.py`, `candidate_line/hooks.py` and `candidate_line/turn.py`. Implement the tier rule from `spec.md` as one pure function over the turn's result (the tool called, the guard's verdict in `ctx.data["guard"]`, the caller's words, and the spoken reply, because a refusal runs no tool), set `TurnResult.tier` so the `tier` eval check is evaluable, write the tier and its reason into the trace (span kind `tier`, name the tier as `1`, `2` or `3`, text the reason; card 07 reads that shape), and submit tier-2 hand-offs through `ctx.escalations` (the queue every path builds beside its store; the log poster unless `SLACK_WEBHOOK_URL` is set; the masked number comes from the store's call row) with the template in `escalation.py`. Wire the cockpit's reply form so a recruiter's override is spoken on the next turn and logged as an `override` span, and show the tier on the list view. Add the kill switch: one file flag read in `LineHooks.on_turn` that makes every call say the closing line from `spec.md` and sets `ctx.data["hang_up"] = True`, which `run_turn` reports as `TurnResult.hang_up` and the phone and text mode honour. A tier-3 call gets its summary after it ends, from `LineHooks.on_call_end`, which the phone and text mode run before `end_call` (the summary job, Sonnet 5.5, nobody waiting), posted with the trace link; if the clock is short, the job is a stub that posts the trace link alone and says so. If I say the hour is short: skip the cockpit's reply form and the summary job, write both into DR-021 as the next work item with the files they would touch, and post a tier-3 call's trace link alone. Run `make text`, show me one turn per tier, and stop. Touch only the files named below.

## The tiers (boundaries from `spec.md`; the mechanics here)

- **Tier 1, alone:** the line answers or acts and says so. No post.
- **Tier 2, a person now:** the line says it is bringing a person in, posts the hand-off (caller's masked number, the ask in one line, the trace link), and holds the call with the holding line until the cockpit replies or the hold limit passes; at the limit the hook says the promise and sets `ctx.data["hang_up"] = True`, which `run_silence` reports as `SilenceReply.hang_up` and the phone and text mode honour. The post's caller is `Escalation.caller` from `ctx.store.call(call_id)`, its link `trace_link(settings.cockpit_base_url, call_id)`, and the log poster prints `[hand-off]` on screen when no webhook is set. On the phone the holding line is said by the `on_silence` hook, which fires after six quiet seconds and again after each further stretch (`media.py`); in text mode, by `/silence N`.
- **Tier 3, written up afterwards:** the line finishes the call and the summary job (Sonnet 5.5, nobody waiting; DR-003) writes the note; the note is posted with the trace link.

## The observer

- The cockpit shows live calls with their tier; a recruiter types a reply and the line speaks it next turn.
- Every override is a span with who, when and what; the trail is the point.
- The kill switch is read on every turn start, never cached, and its flip is a span on every live call; a flip with no live call leaves only the cockpit's log line. Remove the flag before `make gate`, since the eval's turns read it too.

## Acceptance criteria

- The tier function is pure, unit-tested on at least nine inputs (three per tier), and its reasons are strings a recruiter can read.
- A tier-2 turn posts within one second of the tier being assigned, and the holding line plays until a reply or the hold limit.
- The kill switch stops a live call inside one turn.
- `make gate` passes, and the `tier` check in `evals/` is now evaluable.

## Decisions left open, asked of James before writing

1. The channel: the Slack webhook as built, or a text through the line's own number (Twilio, a second cost). Ask; the default is the webhook because it exists.
2. The hold limit in seconds before a tier-2 call is closed with the callback promise.
3. Whether a guard hit (card 05) raises the tier to 2 or only marks the trace. Card 05 leaves its verdicts in `ctx.data["guard"]` and its wish in `ctx.data["tier"]`; the tier rule reads them and clears the per-turn keys at each turn's start.
4. Only at 90 minutes (at 60 every move is a hand-off, `prompts/01`): whether a second move is a person now (tier 2) or a write-up (tier 3): the FAQ's F3.2 says the coordinator returns calls within a business day, which is tier 3, and the persona says the same, while the spec's Must-ask-first line reads as tier 2; the room decides, and the spec, the FAQ line or the persona changes to agree (card 01 or 04 re-entered). The dry run's tier rule needed the caller's words as a signal because Haiku answered a second move from the FAQ without calling the coordinator tool on one run in two.

## Files this card may touch

`candidate_line/tiers.py` (new), `candidate_line/hooks.py` (the bodies of `LineHooks.on_turn` for the kill switch, `LineHooks.on_silence` for the holding line and the hold limit, and `LineHooks.on_call_end` for the tier-3 post after the call, plus their imports), `candidate_line/traces/cockpit.py` (the reply form's handler, the kill switch's flip, and the tier on the list view), `candidate_line/turn.py`, `tests/test_tiers.py`, `tests/test_traces.py` (only the tier span's expected name and text, which this card changes from card 03's placeholder), `docs/decisions/DR-021-tiers-and-observer.md`.

## Teach-back, after

James explains: who decides the tier and from what, what the recruiter sees and can do, and why the queue is bounded and has one worker (DR-013). Grade against `tiers.py`, `escalation.py` and `cockpit.py` by line.
