# DR-009: Synthetic data

Status: DRAFT
Built: pre-built (PREBUILT.md row 6)
Commit: 656fc6a

## What it is

The fixtures the line runs on before Wednesday and during it: eight candidates with codes and PINs, two weeks of first-round slots, a three-page FAQ with section ids, and a baseline of past invites for the scorecard. All of it synthetic, all of it marked so.

## The decision

- **One seed, one script, byte-for-byte regeneration** for the structured files: `scripts/make_synthetic_data.py` with seed `20261101` writes `data/candidates.yaml`, `data/slots.yaml` and `data/baseline_invites.csv`, and a test regenerates them into a temporary folder and compares. An eval case that names a slot id or a code means the same thing next week.
- **The prose is written once from a committed prompt.** `data/PROMPT.md` is the generating prompt; `data/faq.md` (about 1,100 words, eight sections `F1` to `F8`, 28 subsections with ids like `F3.2`) was written by the build session from it on 2026-11-01. Gus cites those ids (AGENTS.md rule 6), so the ids are the FAQ's load-bearing part and they are stable by construction.
- **Nothing in a fixture can be used to evaluate a person.** Candidates carry a code, a PIN, a fictional name, a role, a stage, an invite time, a booked slot and a callback flag. No scores, no notes, no résumé, no phone number and no email: the line reads the caller's number from the call and never stores it in a fixture, and the FAQ says in plain words that the line cannot see notes or decisions (F6.2, F8.1).
- **Every file says it is synthetic in its first line** (a YAML comment, a CSV comment line, an HTML comment in the Markdown), and `candidates.yaml` and `slots.yaml` carry `synthetic: true` as data too, so a tool that loads them can refuse a file without the flag.
- **The shapes.** Codes are `ACME-` plus four digits; PINs are four-digit strings with leading zeros kept (a PIN of `0394` is not the number 394); slot ids are `S` plus month, day, hour and minute (`S1105-0930`), which a person can read back on a phone; slot times carry the Central offset (`-06:00`, standard time after the clocks fell back on 2026-11-01). The baseline has forty invites from June to September 2026 with a log-normal invite-to-booked time (median about 30 hours, 15 percent never booked), which is the shape a scorecard needs to beat and not a claim about any real funnel.
- **The firm is ACME until James names it.** The name is his call (KICKOFF.md, item 11) and the check against real firms happens when he picks.

## The alternative rejected, and why

- **Having a model generate the structured files.** A second run gives different codes and slots, so every eval case would float; the prose is the only part a model writes, and it is written once.
- **Realistic contact details.** Fake phone numbers and emails get copied into prompts, logs and screenshots and look real on a projector; the line has no use for them, so the fixtures do not hold them.
- **A larger candidate set.** Eight is enough for every case the plan names (four unbooked, two booked, one moved, one done) and small enough to read aloud in the room.
- **A baseline drawn from a real recruiting dataset.** Synthetic data only (AGENTS.md rule 10), and the scorecard needs a shape, not a truth.

## What would change the decision

James naming the firm (then the prefix, the FAQ and this record change in one commit); a tool needing a field the fixtures lack (then the script grows the field and the seed stays); the room asking for a case the eight cannot play (then a ninth candidate is added live, as a declared change).

## Evidence

- `uv run python scripts/make_synthetic_data.py`, 2026-11-01: 8 candidates, 40 slots (10 business days by 4 times), 40 baseline invites; 3 slots booked, matching the two booked candidates and the one who moved once.
- `uv run pytest -q tests/test_synthetic_data.py`: the synthetic marks, the code and PIN shapes, the slot and candidate cross-check, the baseline's size and flag, the FAQ's section ids and absence of scoring words, and the byte-for-byte regeneration.
- `wc -w data/faq.md`: 1,122 words.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
