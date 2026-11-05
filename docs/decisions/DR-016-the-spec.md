# DR-016: The spec, written by the build helper from the problem card

Status: DRAFT
Built: live (rebuilt 2026-11-04 evening, after the session, from James's 16:26 CT test call)
Commit: this commit

## What it is

`spec.md` is the contract for the line: what Gus may do alone, what needs a person first, what he never does, where his answers come from, the tiers, and what done means. Every eval case names the spec line it tests (DR-017), and every component names the line it serves.

## The decision

The session did not reach card 01. The build helper wrote `spec.md` on the evening of 2026-11-04 from the five-line problem card in `prompts/01`, after James's test call at 16:26 CT showed the placeholder prompt asking again for a code the caller had given. James was not asked the card's open decisions. Every answer below is the helper's default, not his, and each is marked `[default]` in the spec so one line changes it:

1. The firm is ACME.
2. A good call ends on the problem card's own sentence (spec section 8).
3. The line books on its own. The booking is written when the caller names one open slot by day and time, or says yes to a read-back; a turn superseded by the caller's next words undoes it.
4. The refusal line: "That's not something I have an answer for. I can ask the coordinator to call you back."
5. The guard gets a fallback line of its own: "I can't speak to that. I can help with the process, a slot, or a callback."
6. The kill switch line: "The line is closing for now. Please call back later. Goodbye."
7. The holding line after six quiet seconds: "Take your time. I'm still here."
8. The hold limit: thirty more quiet seconds, then "I'll let you go for now. Call back any time. Goodbye." and the call ends.

Three more are the helper's too, though the card did not ask them: the 60-minute problem card (every move is a hand-off), tier 2 posted at once with no hold because nobody staffs the cockpit this week, and the stop line "Understood. Goodbye."

Three more defaults came after the review of the rebuild the same evening, each marked in the spec: a filler-only transcript is not a turn, while "uh huh", "mm hmm" and "huh?" are (section 2, the code in `candidate_line/telephony/media.py` had it before the spec did); the slots are also given in the caller's time zone, as F3.4 promises (3.2); and a second miss offers a callback instead of another try (3.1). The review also corrected two lines that did not match the code or the FAQ: `move_slot` takes the caller's preferred time, not a slot id, and the coordinator's one business day is F1.3 and F8.2, not F3.2 (section 4).

## The alternative rejected, and why

- Waiting for James's answers before rebuilding: the number is live, a candidate may call tonight, and the placeholder could not verify a caller.
- The 90-minute card, where the line moves a slot once itself: more surface on a line nobody watches this week.
- Holding a tier-2 caller for a person: with nobody in the cockpit, every hold would end in the hold-limit line.

## What would change the decision

James's answer to any of the eight decisions, which arrives as a spec line, then a case, then code (AGENTS.md rule 2). A person staffing the cockpit, which brings back the tier-2 hold. The 90-minute card.

## Evidence

- The 16:26 CT test call: the transcriber wrote "application 3233 PI 9683" and the line asked for the code again. CL-021 is that line; it failed on the first live eval run of this rebuild and passes on the baseline run (DR-017).
- `wc -w spec.md` on 2026-11-04: 780 words, over card 01's limit of 600. Not trimmed here, since the spec is not this work item's file.
- Spec section 7 lists "a refusal" under tier 1 and under tier 3. The code follows tier 3 (`candidate_line/tiers.py`). The line needs James's word; until then no eval case checks the tier of a refusal.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
