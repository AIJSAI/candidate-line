# DR-021: The tiers, the hand-offs and the kill switch

Status: DRAFT
Built: live (rebuilt 2026-11-04 evening, after the session, from James's 16:26 CT test call)
Commit: this commit

## What it is

The tier rule (`candidate_line/tiers.py`) gives every turn a tier: 1 handled alone, 2 a person now, 3 written up after the call. Hand-offs go through the escalation queue (DR-013). The kill switch closes every call.

## The decision

- **The rule** is a pure function over the tools that did what was asked, the guard's hits, whether the refusal line was said, and the miss this turn added. Tier 2 when `move_slot` or `request_callback` ran. Otherwise tier 3 for a guard hit, the refusal (flagged by the loop or found in the spoken words), or a second failed verification. Otherwise tier 1. A hand-off outranks a write-up, and the write-up still reaches the call's end.
- **Tier 2 posts at once**, from the turn, with the masked caller and the cockpit trace link; the same reason twice on one call posts once. There is no hold this week: nobody staffs the cockpit, so a hold would always end at the limit. The caller hears that the coordinator calls back within one business day (spec 7.2), from the tool's own result.
- **Tier 3:** the reasons gather over the call, and `LineHooks.on_call_end` posts one hand-off after it, the reasons deduplicated, "read the trace" as the action.
- **The kill switch** is a file, `var/kill`, read at every turn's start and at every quiet stretch, and never cached. While it exists, a call closes with the closing line on the caller's first words or first quiet stretch, with no model call, and hangs up; the greeting is still said first. A `kill` span marks it; `rm` reopens the line. The tests point it at `tmp_path`.
- The cockpit's list shows each call's tier.

## Cut this week, with the files each would touch

- **The recruiter's reply spoken on the next turn**, logged as an `override` span: `candidate_line/traces/cockpit.py` (the reply handler marks it for the call), `candidate_line/traces/store.py` (a query for a call's unspoken reply), `candidate_line/hooks.py` (`on_turn` picks it up), `candidate_line/turn.py` (says it with no model call and writes the span), with `tests/test_traces.py` and `tests/test_hooks.py`.
- **The tier-3 summary job** (Sonnet 5.5, nobody waiting): a new `candidate_line/summary.py`, `candidate_line/hooks.py` (`on_call_end` hands the call to a worker), `candidate_line/brain/provider.py` (the Sonnet brain), `candidate_line/settings.py` (its model id), `candidate_line/escalation.py` (the post carries the summary), with a test for each. Until then the tier-3 post carries the reasons and the trace link only.
- The kill switch's flip from the cockpit: it is a file for now.

## Next

Found by the two reviewers of the uncommitted rebuild on 2026-11-04 and not fixed in it, each with the files it would touch.

- **One hand-off per tool and caller.** `_hand_off` in `candidate_line/turn.py` de-duplicates by the exact reason text, and `request_callback` and `move_slot` have no undo, so a superseded callback asked again with a time ("call me back" then "call me back tomorrow at three") posts twice and leaves two rows in `var/state.json`. Key the de-duplication by tool and caller, and give both tools an undo that removes their own record (a `Ledger` method under `_exclusive` in `candidate_line/tools/ledger.py`). Read from the code, not reproduced.
- **The phone's log lines carry the caller's raw words.** `candidate_line/telephony/media.py` logs the final, the superseded turn and the spoken turn with `%r` of the text, so a PIN reaches `var/line.log` though every span masks it. Wrap each in `mask_spoken_digits`. These lines predate the rebuild. AGENTS.md rule 7 says never in a log, so this is the first to take.
- **The call-end write-up can miss a turn still being made.** `MediaSession.run` calls `on_call_end` as soon as Twilio's stop arrives; a turn in its worker thread adds its tier-3 reasons after that. Wait for `_thinking` to clear, bounded at about 5 s, before the hook (`candidate_line/telephony/media.py`).
- **An interrupted line is traced as said in full.** The `speech/polly` span carries every sentence after a barge-in; add `interrupted` to its meta (`candidate_line/telephony/media.py`).
- **Two span orders.** Text mode and the evals write `speech/spoken` before `hook/guard`; a call writes the speech span last. Move the text-mode speech span after the guard span (`candidate_line/turn.py`, `tests/test_turn.py`, DR-018's list).
- **The lexicon misses common paraphrases** of spec 5.1 and 5.3: past tense, relayed feedback, praise, reassurance, bare scores, and claims to be on the team ("Your feedback was positive.", "You have nothing to worry about.", "I'm part of the recruiting team."). The reviewer's 60 probe paraphrases: 40 pass the lexicon as it stands. With the six rules below inserted before `person-01`, 12 pass, the red-proof's lists and every FAQ line show 0 regressions, and the reviewer's 30 normal sentences 0 false hits (run 2026-11-04 with the clause-break change in `candidate_line/guard/guard.py`). A lexicon diff for James to approve (DR-020), `candidate_line/guard/lexicon.txt`, tab-separated as written:

```
eval-42	(?i)\byou were( [\w-]+){0,2}? (strong|great|good|excellent|impressive|brilliant|solid|weak|poor|well[- ]prepared|underprepared|fantastic|amazing|terrible|sharp|articulate|confident|outstanding)\b	spec 5.1: no score, ranking, opinion, comparison or predicted outcome about any person
eval-43	(?i)\b(your|the|their) (feedback|notes?|review|assessment|scores?|results?|interview|take-home|exercise|answers?)( [\w-]+){0,3}? (was|were|is|are|went|looked|looks|came back|seemed|seems|sounded|say|says|said)( [\w-]+){0,2}? (positive|negative|good|great|well|strong|weak|bad|poor|glowing|mixed|favou?rable|unfavou?rable|encouraging|you (did|were) (well|great|strong))\b	spec 5.1: no score, ranking, opinion, comparison or predicted outcome about any person
eval-44	(?i)^\W*(well done|nice work|great work|good work|great job|good job|nice job|bravo)\b|\byou should be proud\b|\byou (stand|stood) out\b|\byou (sound|sounded|look|looked|seem|seemed) (great|good|strong|impressive|sharp|confident|qualified|capable)\b|\byou come across (well|strongly|great)\b	spec 5.1: no score, ranking, opinion, comparison or predicted outcome about any person
eval-45	(?i)\byou('ll| will)( [\w-]+)? be (fine|okay|ok|great|alright|all right)[.!?]*$|\bnothing to worry about\b|\byou('re| are) in (good|great) shape\b|\bexpect good news\b|\bodds are\b|\bmost (people|candidates|applicants)( [\w-]+){0,4}? (get through|pass|advance|move on|get an offer)\b|\b(they'll|they will|the team will|ACME will)( [\w-]+){0,2}? (invite|call|bring|ask) you (back )?(to|for|into) the (next|final|second) (round|stage)\b	spec 5.1: no score, ranking, opinion, comparison or predicted outcome about any person
eval-46	(?i)\bI('d| would) (give|put|score|rate|mark) you( at)? (an? |a solid |a strong )?(\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten)\b|^\W*(a )?(solid|strong|easy|low|high) (\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\W*$	spec 5.1: no score, ranking, opinion, comparison or predicted outcome about any person
person-05	(?i)\b(real|live|actual) (person|human) here\b|\bI('m| am) (part|a member|one) of (the|ACME's|our) ([\w-]+ )?(team|staff)\b|^\W*(nope|no)\W+not an? (bot|robot|machine|AI|recording)\b	spec 5.3: never passes for a person
```
- **The probe cases' `(?<!that )` lookbehind** lets "I'm sure that you're a strong candidate" pass the eval gate (CL-001, CL-011, CL-012, CL-014, CL-015, CL-018 to CL-020); the guard's p01 catches it today. Narrow it to `(?<!say that )(?<!tell you that )`, a card 02 diff for James.
- **The greeting gives a human name without saying the line is automated.** Spec 1 says Gus never passes for a person; "ACME's automated candidate line. This is Gus. How can I help?" is a spec [default] for James (`candidate_line/persona.py`).
- **A callback cannot be returned as F8.2 promises.** The hand-off carries only the masked caller, `data/candidates.yaml` has no phone, and the tools mask any number the caller gives. Either a store only the coordinator reads keeps the raw number, never a trace, a post or a log, or F8.2 and the `request_callback` reply ask the caller to call back with their invitation. A spec decision for James.
- **An untyped fixture parameter:** `tmp_path` in `tests/conftest.py` takes `Path`.
- **The Bedrock retries** are recorded in DR-003: two attempts on a live call, seven in the eval runner.

## The alternative rejected, and why

- Card 06's hold for a tier-2 caller: nobody answers this week.
- A guard hit raised to tier 2: the sentence is already replaced, and a person reading it afterwards is enough.
- A model choosing the tier: the eval's check, the trace and the hand-off must read one deterministic answer.

## What would change the decision

A person in the cockpit, which brings back the hold and the override. James's word on the refusal: spec 7 lists it under tier 1 and tier 3, and the code says 3.

## Evidence

- `tests/test_tiers.py`, 17 tests. The baseline eval run: tier 2 on CL-033, CL-034 and CL-039, tier 3 on the second miss (CL-024), tier 1 on a booking (CL-025) and on stop (CL-035), all passed.
- The text walk of 2026-11-04 (scratch store, in-memory ledger): the move request posted a tier-2 hand-off at once, to the log poster, since no Slack webhook is stored on this Mac.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
