# Prompt card 01: the spec, from a five-line problem card

Work item: write `spec.md` for the line from a five-line problem card the room confirms, and nothing else.
Record: `docs/decisions/DR-016-the-spec.md` (live). Rule 2 of `AGENTS.md`: no code for a work item until the spec holds the line it serves.

## Paste this

> Read `AGENTS.md` and `docs/decisions/DR-000-how-decisions-are-recorded.md` in full. Then read the five-line problem card below and write `spec.md` at the repository root, following the shape in this card exactly. Touch no other file. Before you write, ask me the open questions listed under "Decisions left open", one at a time, and wait for each answer. Narrate each file you write in one line. When `spec.md` is written, stop and run my teach-back.
>
> Problem card (five lines, confirmed by the room):
> 1. Who calls: ...
> 2. What they want: ...
> 3. What the line may do on its own: ...
> 4. What the line must never do: ...
> 5. What a good call looks like, in one sentence: ...

## The shape of `spec.md`

1. **The job**, in three sentences, from the card.
2. **The caller**, who they are and what they know when they dial.
3. **May**: the actions the line takes on its own, one line each, each with the data it needs (`data/` is synthetic; the spec names the file).
4. **Must ask first**: the actions that need a human's yes, and who the human is.
5. **Never**: the list that binds every tool and every runtime path (Rule 5). Each line is testable: it names what the line never says or does, and how an eval case would catch it.
6. **Cite or refuse**: which knowledge the line may answer from (the sections of `data/faq.md` by id), and the refusal line it says when the answer is not there (Rule 6).
7. **The tiers**: what the line handles alone, what it hands to a person during the call, and what it writes up afterwards; one line each, boundaries only. The mechanics come in cards 05 and 06.
8. **Done means**: the acceptance criteria for the whole line, measurable, including the latency budget from DR-001 and the eval pass rate from card 02.

## Acceptance criteria

- `spec.md` exists, under 400 words, with the eight sections above and nothing function-specific outside it.
- Every Never line names the eval that would catch it, by a case id card 02 will create.
- Nothing in it names a real person, a real firm or a phone number; the firm is the name James gives, ACME until then.
- `make gate` still passes (the spec changes no code).

## Decisions left open, asked of James before writing

1. The firm's name. (ACME until he names it; the name goes into `candidate_line/persona.py` later, not now.)
2. The one sentence a good call ends on.
3. Whether the line may book a slot on its own or only hold it for a person to confirm.
4. The refusal line, in Gus's voice, said when the FAQ has no answer.

## Files this card may touch

`spec.md` only.

## Teach-back, after

James explains, closed book: what the line may do, what it must ask first, what it never does, and how a Never line becomes a test. Grade each point against `spec.md` by section number; cards for the misses.
