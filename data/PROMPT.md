# The generating prompt for `data/` (all of it synthetic)

Everything in this folder is synthetic. The structured files are produced by `scripts/make_synthetic_data.py` from the seed `20261101`, so they regenerate byte for byte; the FAQ text was written by the build session (Claude Fable 5.1, 2026-11-01) from the prompt below. No real person, firm, number or record appears anywhere. The firm is ACME until James names it (KICKOFF.md, item 11).

## Prompt

Produce the fixtures for a phone line that serves the job candidates of ACME, a fictional engineering-services firm. The line answers process questions from an FAQ and cites the section it used, books or moves first-round interview slots, and takes callback requests. It never scores, ranks or evaluates a person, so nothing below may contain an opinion about a candidate.

1. `candidates.yaml`: eight candidates. Each has an application code in the form `ACME-` plus four digits (unique), a four-digit PIN stored as a string (leading zeros kept), a fictional full name that does not belong to any public figure, a role title, a stage (`invited`, `booked`, `moved_once`, `first_round_done`), the invite timestamp, the booked slot id or null, and a `callback_requested` flag. No phone numbers and no email addresses: the line reads the caller's number from the call itself and never stores it in a fixture. Four candidates are invited and not yet booked, two are booked, one has moved once, one has finished the first round.
2. `slots.yaml`: two weeks of first-round slots, business days only, from Thursday 2026-11-05 to Wednesday 2026-11-18, at 09:30, 10:00, 14:00 and 15:30 Central (UTC-6 after the clocks fell back), 30 minutes each, with a fictional interviewer label (`Engineer A`, `B`, `C`), a status (`open` or `booked`) and the holder's code when booked. Booked slots must match the candidates file.
3. `faq.md`: about three pages, eight numbered sections with ids `F1` to `F8` and subsections `F1.1` and so on, covering the process and its stages, the first-round interview's length and format, how to book, move or cancel, the take-home's time and deadline, logistics and accommodations, when and how candidates hear back, offers and background checks in brief, and callbacks. Plain words, no promises of outcomes, nothing that evaluates or compares anyone.
4. `baseline_invites.csv`: forty past invites with the invite timestamp, the booked timestamp or empty, the hours between, and the channel (`email` or `phone`). This is the scorecard's baseline for invite-to-booked time; a column `synthetic` is `true` on every row and the header comment says so.

Mark every file as synthetic in its first lines.
