# DR-020: The guard over Gus's own words

Status: DRAFT
Built: live (rebuilt 2026-11-04 evening, after the session, from James's 16:26 CT test call)
Commit: this commit

## What it is

The guard checks every sentence speech will say against the lexicon in `candidate_line/guard/lexicon.txt`, and replaces a caught sentence with the fallback line before the caller hears it (`LineHooks.before_speak`, `candidate_line/guard/guard.py`). It serves the Never lines about Gus's words: 5.1, 5.3 and 5.4.

## The decision

- **The lexicon:** 73 rules, one a line, each an id, a regex and the spec line it serves. The ten probe patterns p01 to p10 as written in `bakeoff/probes.yaml` (p09 narrowed, as its header says), 46 `eval-` rules for spec 5.1, 5 `person-` rules for 5.3, 4 `pin-` rules for 5.4, and 8 `allow-` refusal cues. Six of them were added on the evening of 4 November (below).
- **The negation rule:** a hit is excused when a refusal cue sits in the same clause before it ("I can't tell you whether you'll move on"), or when the hit sits in a whether or if clause and a cue is anywhere in the sentence. A comma, a semicolon, a dash, "but", "and", "so", "except" and its kin, and "that say" or "which say" end a clause, so "I can't say, but you did well" and "I can't tell you anything except that you're a strong candidate" are still caught (the last two since the review of 2026-11-04). A `pin-` hit is never excused.
- **A PIN said back with no word PIN beside it:** the `pin-` rules need the word, and on the review walk Gus said a caller's PIN back in words when asked to repeat "the four digits I said". So `verify_caller` keeps every PIN given on the call in the call's scratch, and `before_speak` passes the guard a check that finds any of them in a sentence, as numerals or words, spaced or not; its hit is `pin-heard`, never excused, and written up like any other.
- Sentences are cut by the speech splitter and matched straightened, so the guard cuts where Polly does. Two caught sentences in a row say the fallback once. A guard that fails says the fallback: it fails closed. Each hit is a tier-3 reason naming rule ids only, never the sentence, since a `pin-` sentence holds the PIN.

## Changes proposed to James, 2026-11-04 evening

His words that evening were "the rest seem to make sense", in a reply that does not name this diff, so they are not his approval of it: this record's own rule has him read the lexicon diff itself before it is committed, and his words go here once he has.

- **Six rules from the review** (DR-021, Next), as the reviewer wrote them and in the place the reviewer measured them, after `eval-41` and before `person-01`, so the older rules still name the sentences they caught before:
  - `eval-42`, past-tense judgements: "You were really strong in the first round." (spec 5.1)
  - `eval-43`, relayed feedback: "Your feedback was positive." (spec 5.1)
  - `eval-44`, praise: "Well done on getting this far." (spec 5.1)
  - `eval-45`, reassurance: "You have nothing to worry about." (spec 5.1)
  - `eval-46`, bare scores: "I'd give you an eight." (spec 5.1)
  - `person-05`, claims to be on the team: "I'm part of the recruiting team." (spec 5.3)
- **The red-proof** gains two sentences per new rule, each asserted to be caught by that rule's own id and not by an older one, and two sentences that must pass: a slot confirmation, and the F2.3 answer, which names the interviewer's notes and the hiring team. All twelve passed the lexicon before the six rules, checked on the old and the new lexicon side by side. Every earlier assertion is unchanged and green, every FAQ line still passes, and the six fixed lines still pass.
- **The reviewer's measurement** (DR-021): of 60 probe paraphrases, 40 got through the lexicon before and 12 after, with 0 false hits on 30 normal sentences. Those 60 and 30 sentences are not in the repository, so that number is the reviewer's and was not re-run here.
- **Replayed:** every sentence Gus has said in the stored eval runs and calls of 2026-11-04 (2,700 sentences, read-only) went through the new lexicon, and none hit one of the six rules.
- **Open, false hits found by hand** and left as written, since a narrower rule is a new diff for James: "I'd give you a one-minute summary of the process." (`eval-46`), "There's nothing to worry about if you miss the call; the coordinator can rebook it." (`eval-45`), "Nope, not a recording; this is ACME's automated line." (`person-05`). Each would be replaced by the fallback line, so the cost is a lost sentence, not a leak; none was said in the 2,700.

## The alternative rejected, and why

- A second small model on every reply: not deterministic, and slower than the latency budget allows (DR-001).
- An allow-list of exact refusal sentences: Haiku words its refusals differently on each run.
- Excusing any sentence with a negation in it: "I can't say, but you did well" would pass.

## What would change the decision

A paraphrase the evals or the probe caller find that the lexicon misses, or a refusal it wrongly catches. Each change is a lexicon diff James approves.

## Evidence

- The red-proof after the six rules, `tests/test_guard_red_proof.py`, 138 tests passed on the evening of 2026-11-04: the 124 below plus 12 new-rule sentences and 2 clean ones; 29.9 microseconds a sentence on this Mac (n = 12,300 checks).
- The red-proof, `tests/test_guard_red_proof.py`, 124 tests passed on 2026-11-04: the 10 probe sentences, 22 paraphrases, 25 further evaluations, 7 spoken PINs and 8 claims to be a person are caught; 11 quoted refusals, 28 normal answers, every FAQ answer and the 6 fixed lines pass. Measured 26.8 microseconds a sentence on this Mac (n = 11,100 checks), under the card's 5 ms.
- The red-then-green order card 05 asks for is in the history: `tests/test_guard_red_proof.py` is committed alone first (with the guard package absent it fails 124 of 124, `ModuleNotFoundError: No module named 'candidate_line.guard'`), and the guard lands in the next commit, which makes it green. Both commits were made on the evening of 4 November 2026 by the build helper, after the review.
- Live, the first eval run: `pin-03` caught "your PIN was received" inside the verify reply of CL-022 and CL-023 and replaced the whole sentence, the code read back with it. That sentence says no PIN, so it is a false hit; the brief changed (DR-019), and the rule did not, since a lexicon change is James's to approve.
- Every boundary case passed on the baseline run with the guard in front (DR-017).

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
