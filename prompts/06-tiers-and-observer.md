# Prompt card 06: the tiers and the observer

Work item: assign every turn a tier (handled alone, handed to a person now, written up afterwards), post the hand-offs through the escalation queue, give the recruiter's cockpit its override, and add the kill switch.
Record: `docs/decisions/DR-021-tiers-and-observer.md` (live). The queue and its poster are pre-built (DR-013); the cockpit's list view and reply form exist (DR-012); the tier rule is not written.

## Paste this

> Read `AGENTS.md`, `spec.md` (section 7, the tiers), `candidate_line/escalation.py`, `candidate_line/traces/cockpit.py`, `candidate_line/hooks.py` and `candidate_line/turn.py`. Implement the tier rule from `spec.md` as one pure function over the turn's result (the tool called, the guard's verdict, the caller's words), set `TurnResult.tier` so the `tier` eval check is evaluable, write the tier and its reason into the trace, and submit tier-2 hand-offs to the escalation queue with the template in `escalation.py`. Wire the cockpit's reply form so a recruiter's override is spoken on the next turn and logged as an override span. Add the kill switch: one file flag that makes every call say the closing line from `spec.md` and hang up. Run `make text`, show me one turn per tier, and stop. Touch only the files named below.

## The tiers (boundaries from `spec.md`; the mechanics here)

- **Tier 1, alone:** the line answers or acts and says so. No post.
- **Tier 2, a person now:** the line says it is bringing a person in, posts the hand-off (caller's masked number, the ask in one line, the trace link), and holds the call with the holding line until the cockpit replies or the hold limit passes.
- **Tier 3, written up afterwards:** the line finishes the call and the summary job (Sonnet 5.5, nobody waiting; DR-003) writes the note; the note is posted with the trace link.

## The observer

- The cockpit shows live calls with their tier; a recruiter types a reply and the line speaks it next turn.
- Every override is a span with who, when and what; the trail is the point.
- The kill switch is read on every turn start, never cached, and its flip is a span too.

## Acceptance criteria

- The tier function is pure, unit-tested on at least nine inputs (three per tier), and its reasons are strings a recruiter can read.
- A tier-2 turn posts within one second of the tier being assigned, and the holding line plays until a reply or the hold limit.
- The kill switch stops a live call inside one turn.
- `make gate` passes, and the `tier` check in `evals/` is now evaluable.

## Decisions left open, asked of James before writing

1. The channel: the Slack webhook as built, or a text through the line's own number (Twilio, a second cost). Ask; the default is the webhook because it exists.
2. The hold limit in seconds before a tier-2 call is closed with the callback promise.
3. Whether a guard hit (card 05) raises the tier to 2 or only marks the trace. Card 05 leaves its verdicts in `ctx.data["guard"]` and its wish in `ctx.data["tier"]`; the tier rule reads them.

## Files this card may touch

`candidate_line/tiers.py` (new), `candidate_line/escalation.py` (the submit call site only), `candidate_line/traces/cockpit.py` (the reply form's handler and the kill switch), `candidate_line/turn.py`, `tests/test_tiers.py`, `docs/decisions/DR-021-tiers-and-observer.md`.

## Teach-back, after

James explains: who decides the tier and from what, what the recruiter sees and can do, and why the queue is bounded and has one worker (DR-013). Grade against `tiers.py`, `escalation.py` and `cockpit.py` by line.
