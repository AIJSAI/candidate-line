# docs/learn: what James must be able to explain

This folder holds the teach-back format and the card deck for the Candidate Line build (KICKOFF.md, Rule 1). It follows the tutor skill (`a private file`: its teach-back, grill and receipt modes) and the tutor's card format, so a tutor session can read this deck as it reads any project's.

## The teach-back, at the end of every build block

1. **Before.** James rates how well he could explain the component today, 1 to 7.
2. **Closed book.** With the code and the decision record out of view, he explains the component in his own words as if to a reviewer, in about two minutes, typed or dictated. The session interrupts once or twice, the way a reviewer would: "Wait, who decides that?"
3. **Graded against the code.** Each point is **right**, **partly** or **wrong**, with its file and line reference (or the exact command, for account and CLI work), and the correct version in two or three sentences wherever it was partly or wrong.
4. **After.** He rates his understanding 1 to 7 again. Both ratings go into the record's Teach-back section; a big drop marks what to teach next.
5. **Say it like this.** The session writes one line into the decision record, in his words as corrected: first person, plain words, the design reason before the tech list.
6. **Cards.** Every point graded partly or wrong becomes a card in `cards.yaml` at box 1, due the next day.

The engineering, the prompting and the guardrails are taught alike: a persona line, a refusal, a lexicon entry or a tier boundary is explained the way a module is.

## The grill, the next morning (10 to 15 minutes)

One question at a time, and the message ends with the question: no hint before the answer. James answers with a confidence from 1 (guessing) to 3 (sure). The session grades the idea, not the wording: **right**, **partly** or **wrong**, then the correct answer in two or three sentences with its reference and its "say it like this" line. Due cards come first, and a miss at confidence 3 comes before anything else.

## Spacing (the tutor's boxes)

- A miss goes to box 1, due the next session; a miss at confidence 3 also sets `priority: true`.
- A right answer moves the card up one box: box 2 after 3 days, box 3 after 7, box 4 after 21. A right answer in box 4 retires it.
- A right answer at confidence 1 counts as partly. Partly keeps the box and makes the card due next session.
- Before Wednesday the calendar overrides the boxes: Wednesday morning's grill asks at least one question per row of `PREBUILT.md`, whatever a card's box.

## The card format

```yaml
- id: candidate-line-0001          # never reused
  question: "Why does the CLI hold no long-lived key?"
  answer: "Two to four sentences: the correct answer."
  say_it: "One line, first person."
  ref: "path/to/file.py:120"       # or the command, for CLI work
  source: "teach-back DR-002 2026-11-01"   # or: grill 2026-11-02, receipt 2026-11-01
  box: 1
  next_due: 2026-11-02
  history: ["2026-11-01 partly c2"]        # c = his confidence, 1 guessing to 3 sure
```

## The daily receipt

At the end of each build day, the tutor skill's receipt mode writes the private notebook from its template. Its three questions are added to this deck, so one deck holds the whole build.

## What a line here never says

Every "say it like this" line explains this build. None claims anything about James's past work, any employer or any real firm; those are said in words only, from his own record, and never written here.
