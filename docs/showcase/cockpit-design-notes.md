# The Today screen: where every element comes from

`cockpit-design.html` is the screen ACME's recruiting lead opens in the morning for the Candidate Line, the phone line candidates call to book their first interview. The voice is Gus. Gus never evaluates a candidate, and anything unsure goes to a person.

Rebuilt from scratch on 2026-11-03 after James's verdict on the first version: "a jumble of stranger-unfriendly data and a bombardment of information." The facts were kept and the layout thrown away. A fresh Claude session that had not seen the page then read the rebuild cold the same day; their five changes are applied (see "The stranger's pass"). The page is now four things: a top bar, the callers waiting for a person, three numbers, the latest calls. Everything cut from the page is below, under "Kept for the pilot's second screen".

Records read in this repository at commit 3919773 (2026-11-03), read-only. References are `path:line` at that commit.

## The four kinds of value

- **Measured** (one): the pause before Gus answers, 2.6 s. Its tile reads "measured, target 2 s".
- **Estimate** (one): about 18 cents per five-minute call, on the line "Estimated cost to run Gus: about 18 cents per five-minute call."
- **From a record** (fixed design values, not data): the 45-second hold limit (behind each "s left" count), the 2-second target, the three open slots.
- **Sample** (everything else that is a number, a time, a role or a name): covered by the one banner, "Sample data for ACME, a fictional firm. Only figures marked measured or estimated are real."

## Where the page departs from the brief, and why

1. **The cost reads "Estimated", never "measured", and the banner says "measured or estimated".** `docs/decisions/DR-001-voice-path.md:65` gives arm A (the Wednesday build) "about 0.18 USD" per five-minute call, computed from list prices read 2026-11-01 and a call scaled from the bake-off. The same row reserves "measured" for arm B's 0.10, which came from metered token counts. Calling 0.18 measured would be a false record; leaving it unmarked would make the banner call it sample. "A call" became "per five-minute call", the unit DR-001 prices.
2. **The 11:12 AM row reads "Booked by Gus; one reply reworded".** The guard swapped one reply for its fallback line before it was spoken (card 01 (prompts/01, decision 5)); "reworded" is the stranger's plain word for that swap. The guard hit also set tier 3, a note for the recruiter (card 05 (prompts/05, decision 2) and 06.3, `the session plan:51-52`); with the pills gone the row no longer shows that note.
3. **The bottom row reads "Booked by Gus for Thu Nov 5, 9:30 AM".** That is the first version's 6:48 AM booking (slot S1105-0930). The brief's example, Mon 11-09 3:30 PM, is one of the open slots offered in the queue, so using it twice would double-book it.
4. **Each hold reads "N s left" after a muted "On hold", and the bar shows time left.** 7 s and 33 s are 45 minus 38 and 45 minus 12; the fills, 16% and 73%, are 7/45 and 33/45, so the bar empties as the count falls.
5. **The second caller's field reads "Type what Gus should say".** That card has no slot chips, so "Or" had nothing to follow.
6. **2,640 ms is shown as 2.6 s**, one decimal.

## The stranger's pass (2026-11-03)

A stranger read the rebuild cold at 1280 x 720, scored it 6 of 10 and proposed five changes. All five remove or clarify; none adds a section, a number or a tag, so none was declined.

| Change | Applied as | Where it departs from the stranger's words, and why |
| - | - | - |
| 1. Say who Gus is | A muted line beside "Needs a person now"; the paused line rewritten | Their sentence ran fourteen words, so it is two: "Gus, the voice assistant answering your line, is holding these callers. Reply before time runs out, or Gus promises a callback." The second sentence answers their question of what happens when the hold ends (card 01 (prompts/01, decision 8)). The line hides when the line is paused, since nobody is held then. The paused line is two sentences for the same rule: "Gus told both callers someone will call them back. Both are now under Callbacks owed." |
| 2. One way to mark what is real | Banner rewritten; the "Measured" and "Estimate" chips and the footer deleted; tile sub "measured, target 2 s" | The cost line reads "Estimated cost to run Gus:", not "Estimated cost:", because they also asked whose cost it is |
| 3. Masked numbers out | The six table spans deleted; the cards read "ending 0142" and "ending 7720", as their reply fields' labels already did | none |
| 4. The table as a short log | "Latest calls", "Newest first.", the two held callers' rows and every pill deleted; outcomes say who handled the call | The rows lost their pointer and hover tint, since they open nothing |
| 5. Dates and hold times | Slots "Mon Nov 9, 3:30 PM", "Tue Nov 10, 2:00 PM", "Wed Nov 11, 9:30 AM"; "7 s left", "33 s left" | The bar now shows time left (departure 4) |

Two follow-ons keep the page true to itself. "Callbacks owed" reads 5 when the line is paused (the first version's sample value), so the paused line's claim holds on screen. Print styles scale the screen onto one landscape page and keep the phone layout off paper.

Left open. Each would add a number or a behavior: the page shows no date; the pause tile does not mark over target as bad; a slot chip does not show that it fills the reply. The stranger proposed no change for these, so they stand: "Send reply"; "Today" repeating the nav tab; "first round" on the cards only. "Calls" and "Settings" open nothing in a static design.

## Top bar

| Element | Source |
| - | - |
| "ACME Candidate Line" | the firm is ACME: `docs/decisions/DR-009-synthetic-data.md`; card 01 (prompts/01, decision 1). The phone glyph beside it is design |
| Nav "Today" (active), "Calls", "Settings" | design; static links. "Calls" is today's full call list (`candidate_line/traces/cockpit.py:93-105`). "Settings" is where the FAQ, calendar, hand-off rules and hold limit would be set; today they are files (`data/faq.md`, `data/slots.yaml`, card 06 (prompts/06, decision 2)) |
| "Phone line" switch, "Taking calls" / "Paused" | the kill switch: `prompts/06-tiers-and-observer.md:3` (work item), `:8` (one file flag), `:20` (read on every turn start, never cached, each flip a span on every live call). The state words are **sample** UI copy |
| User chip "Jordan E." | **sample** name. Sign-in is a pilot addition (below); today's reply form asks for a typed name (`cockpit.py:135-136`) |
| Banner "Sample data for ACME, a fictional firm. Only figures marked measured or estimated are real." | licenses every sample value on the page; see departure 1 for the wording. "Fictional firm": `AGENTS.md` rule 10; DR-009 |

## Needs a person now

| Element | Source |
| - | - |
| The section and its count, 2 | tier 2, a person now: `prompts/06:13` (posts the masked number, the ask in one line, the trace link; holds the call until the cockpit replies or the hold limit passes). The count is **sample** |
| "Gus, the voice assistant answering your line, is holding these callers. Reply before time runs out, or Gus promises a callback." | the hold (card 01 (prompts/01, decision 7)) and, at the limit, the call-back line (card 01 (prompts/01, decision 8)). Hidden while the line is paused |
| "Platform Engineer, first round", "Data Engineer, first round" | **sample**; the synthetic candidates carry a role and a stage (`DR-009:15`; `data/candidates.yaml` lists both roles) |
| "ending 0142", "ending 7720" | the last four kept by the masking in `docs/decisions/DR-012-trace-store-and-cockpit.md:15`; the digits are **sample** (0142 is DR-012's own example) |
| "called 11:40 AM", "called 11:41 AM" | **sample** |
| The asks: a move, a captioned call | **sample** rows. At 60 minutes every move is a hand-off (the session plan; `prompts/06:34`; `data/faq.md:37`, F3.2); accommodations go to the coordinator (`data/faq.md:68`, F5.2) |
| Hold bar, "7 s left", "33 s left" | the 45-second limit is card 06 (prompts/06, decision 2); the held seconds, 38 and 12, are **sample**. Bar fill 16% and 73% is 7/45 and 33/45, time left |
| Slot chips "Mon Nov 9, 3:30 PM", "Tue Nov 10, 2:00 PM", "Wed Nov 11, 9:30 AM" | S1109-1530, S1110-1400 and S1111-0930, each `status: open` in `data/slots.yaml` (lines 71, 89, 101). Offering them is **sample** design |
| Field "Or type what Gus should say", "Send reply" | today's reply form logs a typed reply with who and when (`cockpit.py:119-140`; `DR-013:16`). A caller on hold is silent, so Gus says the reply at the next silence tick, six quiet seconds (`candidate_line/telephony/media.py:50`, `:164-181`) |
| "Call back instead" | ends the hold now with the hold-limit line (card 01 (prompts/01, decision 8)); the hold-limit branch of `on_silence` run early. Design only |
| Off-state line "Gus told both callers someone will call them back. Both are now under Callbacks owed." | the closing line and its promise ("will call you back"), card 01 (prompts/01, decision 6). For it to reach a caller on hold, `on_silence` must read the flag as `on_turn` does (pilot addition below). The Callbacks owed tile reads 5 while paused, 3 plus the two (**sample**) |

## Today

| Tile | Value | Source |
| - | - | - |
| Booked without a person | 15, "of 25 calls" | **sample**. Measure: calls by tier, tier 1 (`prompts/07-scorecard.md:12`; `prompts/06:12`) |
| Callbacks owed | 3, "oldest due Thu 7:52 AM" | **sample**. Due one business day after the call: `data/faq.md:104` (F8.2), and the promise in card 01 (prompts/01, decision 2), 01.4, 01.6, 01.8 |
| Pause before Gus answers | 2.6 s, "measured, target 2 s" | **measured**: `docs/decisions/DR-011-probe-caller.md:43`, the recording's median 2,640 ms over three turns, 2026-11-03 15:03 CT, arm A. Target 2,000 ms for the median turn: `DR-001:23` |
| Under the tiles | "Estimated cost to run Gus: about 18 cents per five-minute call." | **estimate**: `DR-001:65`, arm A, rates read 2026-11-01 (departure 1) |

## Latest calls

| Element | Source |
| - | - |
| The table, "Newest first." | today's call list: `cockpit.py:93-105` (`call_cells`). Named "Latest calls" because it shows four of the day's calls; the full list is "Calls" |
| Columns Time, Who, Wanted, Outcome | Time is `started_at` (`candidate_line/traces/store.py:48`); Who is the role; Wanted and Outcome are pilot additions (below) |
| "by Gus", "by a person", "Gus had no answer" in the outcomes | plain words for tiers 1 to 3, `prompts/06:12-14` |
| Four rows | **sample**, the first version's six less the two callers holding now, who are the cards above: the safety-filter call that still booked, an FAQ gap, a move a person handled, an early booking |
| 11:12 AM, "Phone screen feedback, then a slot"; "Booked by Gus; one reply reworded" | the safety-filter case. The caller asked for an evaluation; the guard swapped one reply for its fallback line (card 01 (prompts/01, decision 5)) before it was spoken, marked the trace and set tier 3 without interrupting the call (card 05 (prompts/05, decision 2), 06.3) |
| 10:05 AM, "The pay range for the role"; "Gus had no answer; add it to the FAQ" | the refusal line with its callback promise, card 01 (prompts/01, decision 4); a note is tier 3 (`prompts/06:14`); the gap goes to whoever keeps the FAQ (`prompts/07:17`) |
| 9:20 AM, "Moved by a person; invite sent" | a move handed to a person (F3.2); the person's reply as in `cockpit.py:119-140` |
| 6:48 AM, "Booked by Gus for Thu Nov 5, 9:30 AM" | S1105-0930, open in `data/slots.yaml:5`. No slot on the page is used twice |

The banner now carries the footer's disclosure, so the footer is gone (its text is under "Other copy and columns cut").

## Pilot additions shown on this page

Each is on the page but not supplied by card 06 or card 07 as written.

- **Sign-in:** the user chip. Today's cockpit is a loopback page with no sign-in (`DR-012:16`); the typed name is the who (`cockpit.py:136`).
- **Off reaches a caller on hold:** `on_silence` reads the kill flag as `on_turn` does (`prompts/06:8`, `:38`; `candidate_line/hooks.py:56-58`; `media.py:50`).
- **Slot chips and "Call back instead":** one fills a reply with an open slot, the other runs the hold-limit line early; today's form logs a typed reply only (`cockpit.py:131-137`).
- **Role on a call:** from the caller's verified record (the candidates carry one, `DR-009:15`).
- **Wanted:** tier 2 the hand-off's reason (`store.py:56-57`), tier 3 the write-up (`prompts/06:14`), tier 1 the tier span's reason (`prompts/06:8`).
- **Outcome:** composed from the tool span's slot and the guard's verdict, not `calls.outcome`, which holds turn counts on the phone (`media.py:143`, `:150`).
- **Callbacks owed as a count:** one row per promise with its due time; nothing records a promise as its own row today.
- **Live queue:** one small script that refreshes the queue and leaves the reply box alone, a change to DR-012's no-script choice (`DR-012:16`; `cockpit.py:5`).

## Kept for the pilot's second screen

Everything here was on the first version and is true; it moved off the Today screen so the screen reads in ten seconds.

### How each number is measured

- **Pause before Gus answers:** caller's last word to Gus's first sound, read from the call recording by energy (DR-001's method of record). The 2.6 s is the latest of three recordings taken since Gus waits for the end of a sentence (the grace window); the other two read 2,640 and 3,170 ms on 2026-11-02 evening (`docs/decisions/DR-006-arm-a-cascaded-audio-path.md:59`). The bake-off figure, 2,060 ms over 23 turns in 16 calls (`DR-001:63`), was taken before the grace window existed. The line's own clock on the first real call read 1,098 ms over 4 turns (`DR-001:87`), a different method. DR-011's call ran the placeholder persona's three-sentence replies; shorter replies are the first fix (`DR-006:59`, `DR-011:43`; the brevity rule and reply cap, card 04). In the pilot the tile reads the line's own spans, a third method, and must say so (`prompts/07:13`).
- **Cost per call:** speech to text 0.05, voice 0.08, model 0.003, phone line 0.04 USD, at prices read 2026-11-01, with the voice share scaled from the bake-off's 3.7 turns per 40 s call to 27 turns at 192 characters a reply (`DR-001:65`). Not metered. The spend caps (50 USD a month each, `DR-002:22`, `DR-003:34`) stay off the page: in the pilot they would be ACME's own.
- **Booked without a person:** calls ending in a booking with no hand-off, tier 1 by the tier span (`prompts/07:12`).
- **Callbacks owed:** every promise of a call back within one business day, from the call record.
- **Every number carries its method:** `prompts/07:22`.

### The six-tile set (first version)

| Tile | Value then | Kind |
| - | - | - |
| Callbacks Owed | 3 (5 when paused), oldest due Thu 11-05, 7:52 AM | sample |
| Booked Without a Person | 15 of 25, 60%, 6 before 8 AM | sample |
| Hours from Invite to Booked | 28.45 h before; today blank on purpose | synthetic baseline: `data/baseline_invites.csv`, 40 invites dated 2026-06-07 to 2026-09-21, 34 booked, median of the 34 `hours_to_book` = (27.5 + 29.4) / 2. `prompts/07:15` requires the words "Synthetic data, synthetic baseline". In the pilot, today's figure comes from the booking tool's spans, with n beside it |
| Hand-Offs Today | 4: 2 waiting, 2 answered | sample; tier-2 posts (`prompts/06:13`; DR-013 queue rows) |
| Cost per Call | about $0.18 | estimate (above) |
| Pause Before Gus Answers | 2.64 s, over by 0.64 s | measured (above) |

The tile list is card 07's (`prompts/07:12-17`).

### Callbacks owed panel

One row per promise, soonest due first, each with "Mark Called" (writes who and when). The first version's three, all **sample**, each checked against `data/faq.md` and not covered there:

| Called | Question | Closest FAQ section | Due |
| - | - | - | - |
| 7:52 AM | "Will my interviewer be on the team I'd join?" | F2.1, How long is it, and in what format? | Thu 11-05, 7:52 AM |
| 8:31 AM | "Can I do the first round in Spanish?" | F5.2, What accommodations are available? | Thu 11-05, 8:31 AM |
| 10:05 AM | "What's the pay range for the Platform Engineer role?" | F7.1, What happens at the offer stage? | Thu 11-05, 10:05 AM |

When the line is paused, the two held callers join this list, due one business day later.

### FAQ gaps panel

The same unanswered questions, sent to whoever keeps the FAQ ("Send to FAQ Owner"). Source: cite-or-refuse, `prompts/07:17` (answers with a citation, refusals, and neither); `AGENTS.md` rule 6. The closest section is named by the write-up job (`prompts/06:14`); nothing computes it today.

### The trail

- **Last time a person stepped in:** who, when, what, said at the caller's next pause (`prompts/06:19`, "Every override is a span with who, when and what; the trail is the point"; `cockpit.py:119-140`; `DR-013:16`). Sample entry: Sam K., coordinator, 9:21 AM CT, caller ***-***-3381, typed "Moved to Tuesday 11-10 at 10:00 AM. Your new invite is on its way."
- **Last time the line was paused:** `prompts/06:20`. Sample entry: Jordan E., 2026-11-03 5:08 PM CT, back on after 6 minutes off for an FAQ update. With no live call, card 06 writes only a log line with no name, so this needs a flip record (one store row per flip with who and when).

### Lines Gus says, verbatim (card 01 (prompts/01), the session plan)

- Holding (01.7): "I have asked the coordinator to pick this up. Please stay on the line a moment."
- At the hold limit (01.8): "The coordinator has your request and will call you back within a business day."
- Closing, when the line is paused (01.6): "The line is paused for a moment. The coordinator has your number and will call you back."
- Refusal (01.4): "That is not in my notes, and I do not guess. I can have the coordinator call you back within a business day."
- Guard fallback (01.5): "I can't say anything about that. What else can I help with on the process?"

### Other copy and columns cut

- Header intro: "Gus answers ACME's candidate line: it books interviews and answers only from your FAQ. Gus never evaluates a candidate." (`bakeoff/persona.md:5`; `data/faq.md:101`, F8.1). The persona file is the bake-off's test persona; the room's persona must keep the never-evaluate rule.
- "Sample day, Wednesday 2026-11-04, as of 11:42 AM CT" and "Last flipped by Jordan E."
- Queue copy: "Each one also posts to your team chat" (`prompts/06:13`; card 06 (prompts/06, decision 1); `DR-013:15`) and "Gus says it at the caller's next pause, within about six seconds" (`media.py:50`).
- Calls table: Length (`ended_at` minus `started_at`, `store.py:48`), Role column and role filter (`DR-012:28`, one more query), the tier legend, "Showing 6 of 25".
- The assurance line: calls, hand-offs and replies come from the call record (`DR-012:13`); costs from the rate table (`prompts/07:14`); no audio is kept (`DR-012:14`); numbers masked in the store (`DR-012:15`); any PIN a caller says is masked (`store.py:73-84`, card 03 (prompts/03, decision 3)).
- Footer: "on the same call record as today's working version" (`DR-012:13`) and "It runs in your own cloud, wherever your team's data already lives" (the plan, `DR-012:28`; today one SQLite file on one machine).
- Hover text "Design only. In the pilot, ..." on every button.
- Cut in the stranger's pass: the footer ("Built in the pilot from your FAQ, calendar and hand-off rules. No real candidate data; ACME is a fictional firm."; the inputs that change per client, below); the "Measured" and "Estimate" chips; the masked numbers `***-***-NNNN` (DR-012:15); the outcome pills "Gus", "A person", "Note" (tiers 1 to 3, `prompts/06:12-14`); "Open a call to see every step Gus took." (the call page, `cockpit.py:147-163`; every step a span, `DR-012:13`); the two held callers' rows in the table.

## What changes for the next client

| Today | Next client |
| - | - |
| Firm ACME and the voice name Gus (DR-009; `bakeoff/persona.md:5`) | theirs |
| The FAQ (`data/faq.md`) | their candidate FAQ, with the gaps list feeding its owner |
| Slots (`data/slots.yaml`) | their scheduling calendar |
| Hand-off rules and hold limit (F3.2, F5.2; card 06 (prompts/06, decision 2): 45 s) | their rules |
| Alert channel (card 06 (prompts/06, decision 1)) | their chat tool |
| Baseline (`data/baseline_invites.csv`, synthetic) | an export of their past invites |
| Rates (DR-001's rate table, read 2026-11-01) | re-read at their volume |
| Where it runs (one SQLite file, `DR-012:13`) | their cloud and data store (`DR-012:28`) |

**What stays:** the order (the callers Gus can't finish first, then three numbers, then the calls), the three tiers, a method behind every number, masking at the store, no audio, and a line that never evaluates a candidate.

**Say it like this:** "Two callers need you now, so they come first. Then three numbers and the latest calls. Everything else is one click away."

## Checks run

- Headless Chrome, 1280 x 720: the bar, the banner, both caller cards and all three tiles are above the fold (tiles end at about 667 px); the cost line sits just under them.
- 1280 x 1100: the whole page, ending about 1,022 px down, with the table's four rows; no horizontal scroll.
- Off state from a scratch copy: the switch reads "Paused", the paused line shows above the dimmed cards, the Gus line hides, Callbacks owed reads 5.
- Print to PDF: one landscape page on Letter and on A4.
- 390 px wide (through a wrapper frame): bar on two rows, cards and tiles stack, the table scrolls inside its card.
- No em-dash or en-dash in either file; one inline script; no external assets; no sentence over twelve words on the page; ACME is the only firm named; no real person, phone number, account id or secret; no cloud or chat product named on the page; every number on the page is sample or one of the two real figures.
- Every slot on the page checked against `data/slots.yaml` at 3919773: all open, none used twice.
