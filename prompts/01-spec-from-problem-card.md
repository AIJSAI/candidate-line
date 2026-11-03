# Prompt card 01: the spec, from a five-line problem card

Work item: write `spec.md` for the line from a five-line problem card the room confirms, and nothing else.
Record: `docs/decisions/DR-016-the-spec.md` (live). Rule 2 of `AGENTS.md`: no code for a work item until the spec holds the line it serves.

## Paste this

> Read `AGENTS.md` and `docs/decisions/DR-000-how-decisions-are-recorded.md` in full. Then read the five-line problem card below and write `spec.md` at the repository root, following the shape in this card exactly, then `docs/decisions/DR-016-the-spec.md` from the DR-000 template with the open decisions and the answers given. Touch no other file. Before you write, ask me the open questions listed under "Decisions left open", one at a time, and wait for each answer. Narrate each file you write in one line. When both are written, stop.
>
> Problem card (five lines, confirmed by the room):
> 1. Who calls: ACME's job candidates who hold a first-round invitation, from their own phones, often outside office hours.
> 2. What they want: to book or move their first-round slot, to ask how the process works, or to have a person call them back.
> 3. What the line may do on its own: verify a caller by application code and PIN, book an open slot, move a booked slot once, answer a process question from the FAQ and name the section, and take a callback request.
> 4. What the line must never do: evaluate a person (no score, ranking, opinion, comparison or predicted outcome), answer a process question from anywhere but the FAQ, or pass for a person.
> 5. What a good call looks like, in one sentence: a verified candidate hangs up inside three minutes with a slot confirmed out loud or a callback promised, having heard nothing about how they are doing.

The five lines were drafted by the session on 2026-11-02 from `KICKOFF.md` section 1. They are the room's to confirm or change, line by line, before the paste; a changed line changes `spec.md`, never a card.

## The shape of `spec.md`

1. **The job**, in three sentences, from the card.
2. **The caller**, who they are and what they know when they dial.
3. **May**: the actions the line takes on its own, one line each, each with the data it needs (`data/` is synthetic; the spec names the file).
4. **Must ask first**: the actions that need a human's yes, and who the human is.
5. **Never**: the list that binds every tool and every runtime path (Rule 5). Each line is testable: it names what the line never says or does, and how an eval case would catch it.
6. **Cite or refuse**: which knowledge the line may answer from (the sections of `data/faq.md` by id), the refusal line it says when the answer is not there (Rule 6), and the fallback line it says when the guard replaces a sentence (card 05; it may be the same line).
7. **The tiers**: what the line handles alone, what it hands to a person during the call, and what it writes up afterwards; one line each, boundaries only; and the closing line the line says when the kill switch is on. The mechanics come in cards 05 and 06.
8. **Done means**: the acceptance criteria for the whole line, measurable, including the latency budget from DR-001, the eval gate from card 02 (every boundary case passes; the regression pass rate holds at or above the committed baseline), and the observability line that card 03 serves (every turn of every call leaves its spans in the trace store, readable by a recruiter).

## Acceptance criteria

- `spec.md` exists, under 500 words by `wc -w`, with the eight sections above and nothing function-specific outside it.
- Every Never line names the eval that would catch it, by a case id card 02 will create.
- Nothing in it names a real person, a real employer or client firm, or a phone number (a vendor such as AWS or Twilio may be named); the firm is the name James gives, ACME until then.
- `make gate` still passes (the spec changes no code).

## Decisions left open, asked of James before writing

1. The firm's name. (ACME until he names it; the name goes into `candidate_line/persona.py` later, not now.)
2. The one sentence a good call ends on.
3. Whether the line may book a slot on its own or only hold it for a person to confirm.
4. The refusal line, in Gus's voice, said when the FAQ has no answer.
5. The fallback line the guard says in place of a sentence it caught (the refusal line doubles for it unless he wants another).
6. The closing line the kill switch makes every call say before it hangs up.

## Files this card may touch

`spec.md`, `docs/decisions/DR-016-the-spec.md`.

## Teach-back, after

James explains, closed book: what the line may do, what it must ask first, what it never does, and how a Never line becomes a test. Grade each point against `spec.md` by section number; cards for the misses.
