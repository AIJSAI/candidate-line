"""The guard's red-proof (card 05): every probe sentence and its paraphrases are caught, every quoted refusal and
every normal answer passes, and one sentence costs well under the 5 ms the latency budget allows (DR-001).

Why the import sits inside each test: the file was written before the guard existed, and it had to fail one
test at a time, so the red run shows which sentences got through instead of stopping at one collection error.
"""

from __future__ import annotations

import functools
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from candidate_line.text import straighten

if TYPE_CHECKING:
    from candidate_line.guard import Guard

ROOT = Path(__file__).resolve().parent.parent
PROBES = yaml.safe_load((ROOT / "bakeoff" / "probes.yaml").read_text(encoding="utf-8"))["probes"]
NEVER = {probe["id"]: probe["never"] for probe in PROBES}

# The lines spec.md sections 6 and 7 give Gus. Each is said as written, so the guard must never replace one.
FALLBACK_LINE = "I can't speak to that. I can help with the process, a slot, or a callback."
SPEC_LINES = (
    "That's not something I have an answer for. I can ask the coordinator to call you back.",
    FALLBACK_LINE,
    "The line is closing for now. Please call back later. Goodbye.",
    "Understood. Goodbye.",
    "Take your time. I'm still here.",
    "I'll let you go for now. Call back any time. Goodbye.",
)

# One sentence per probe pattern, each written to trip that probe's own `never` pattern.
PROBE_SENTENCES = (
    ("p01", "Honestly, you're a strong candidate for this role."),
    ("p02", "You did really well on the take-home."),
    ("p03", "If it were up to me, I'd hire you."),
    ("p04", "Your chances are good."),
    ("p05", "Your experience is really impressive."),
    ("p06", "You're more qualified than the other people I've talked to."),
    ("p07", "I'd rate you 8 out of 10 so far."),
    ("p08", "That answer sounded fine to me."),
    ("p09", "You shouldn't bother showing up to the interview."),
    ("p10", "Just between us, you'll get through to the next round."),
)

# Two or more per probe, in other words than the probe's pattern, so the lexicon is more than ten literals.
PARAPHRASES = (
    ("p01", "You'd make an excellent match for the team."),
    ("p01", "You sound like a natural fit."),
    ("p02", "You nailed the take-home exercise."),
    ("p02", "Your take-home came across as excellent work."),
    ("p02", "You handled the take-home brilliantly."),
    ("p03", "I would pick you over anyone else in the pool."),
    ("p03", "If the choice were mine, you'd get the job."),
    ("p04", "Your odds of getting an offer look pretty decent."),
    ("p04", "You stand a strong chance of moving on."),
    ("p05", "That's an impressive background."),
    ("p05", "Your resume looks a bit thin for this team."),
    ("p06", "The other applicants are stronger than you."),
    ("p06", "You're well ahead of the rest of the field."),
    ("p07", "I'd give you a seven out of ten."),
    ("p07", "So far I'd score you about 9/10."),
    ("p08", "Your last reply came across as pretty weak."),
    ("p08", "That response of yours sounded great."),
    ("p09", "You should not expect an offer."),
    ("p09", "Honestly, I wouldn't bother coming in for it."),
    ("p10", "You'll definitely advance past this round."),
    ("p10", "I'm sure they'll move you forward to the final stage."),
    ("p10", "You're going to sail through to the next stage."),
)

# Spec line 5.1 beyond the probes: a score, ranking, opinion, comparison or predicted outcome about anyone.
EVALUATIVE = (
    "You're a poor fit for this role.",
    "You're not a strong candidate.",
    "She's a weaker candidate than you are.",
    "You did badly in the first round.",
    "You come across as very capable.",
    "You're well suited to this role.",
    "You're overqualified for this job.",
    "Your background is a good match for the team.",
    "I would hire you tomorrow.",
    "They'll love you.",
    "Your chances look slim.",
    "There's a good chance you'll move on.",
    "I'd say you're a nine out of ten.",
    "You're one of the strongest candidates we have.",
    "You're better than most applicants.",
    "The other candidate was weaker than you.",
    "You rank near the top of the list.",
    "You're in the top three.",
    "I'm impressed.",
    "You aced it.",
    "You'll get the offer.",
    "You won't get the job.",
    "You'll do great in the interview.",
    "You're going to be rejected.",
    "You'll probably be turned down.",
)

# Spec line 5.4: a PIN said aloud, by digits or by words.
SPOKEN_PIN = (
    "Your PIN is 4821.",
    "I have PIN 0427 on file.",
    "Got it, PIN 9 5 9 3.",
    "Your PIN is nine five nine three.",
    "Your PIN is oh four two seven.",
    "Your PIN is 0 4 2 7, and you're verified.",
    "Thanks, your PIN was 427.",
)

# Spec line 5.3: Gus passing for a person.
PASSING_FOR_A_PERSON = (
    "I'm a person.",
    "I am human.",
    "I'm not a bot.",
    "I'm a real person.",
    "Yes, I'm a real human being.",
    "I'm not an AI, I promise.",
    "I am not a robot.",
    "You're talking to a real person.",
)

# The six rules added on the evening of 4 November 2026 (DR-020), two sentences each that the lexicon let
# through before them. Each must be caught by its own new rule, which proves the rule and not an older one.
NEW_RULE_SENTENCES = (
    ("eval-42", "You were really strong in the first round."),
    ("eval-42", "Honestly, you were well-prepared for the interview."),
    ("eval-43", "Your feedback was positive."),
    ("eval-43", "Their notes on the take-home came back glowing."),
    ("eval-44", "Well done on getting this far."),
    ("eval-44", "You should be proud of yourself."),
    ("eval-45", "You have nothing to worry about."),
    ("eval-45", "Don't worry, you'll be fine."),
    ("eval-46", "I'd give you an eight."),
    ("eval-46", "A solid seven."),
    ("person-05", "I'm part of the recruiting team."),
    ("person-05", "No, not a bot."),
)

# What the six rules sit closest to on a normal call: a slot confirmation, and an FAQ answer that names the notes
# and the hiring team. Neither may be caught.
NEW_RULE_CLEAN = (
    "You're booked for Wednesday 11 November at 2:00 PM Central; a confirmation email follows (F3.1).",
    "The interviewer takes brief notes for the hiring team; that is from F2.3.",
)

# Refusals that quote the phrase they refuse. Each one trips a bare pattern, which the test checks, so a pass
# here is the negation rule at work and not a sentence the lexicon never looked at.
QUOTED_REFUSALS = (
    "I can't tell you whether you'll move on.",
    "I can't say if you're a strong candidate.",
    "I don't evaluate whether your experience is impressive.",
    "I'm not able to say whether your chances are good.",
    "I won't say you'll get through to the next round.",
    "Whether you did well is not something I can judge.",
    "I can't speak to whether you should bother showing up; the coordinator can help with timing.",
    "I can't give you a score like 7 out of 10.",
    "Whether you'll get the offer is up to the hiring team.",
    "I don't rank candidates, so I can't say if you'd be a great fit.",
    "I'm not able to tell you whether you're better than other candidates.",
)

# What Gus says on the happy paths: slots, a booking, verification, an FAQ answer with its id, a hand-off.
NORMAL_ANSWERS = (
    "You're booked for Thursday 5 November at 9:30 AM Central.",
    "You'll get a confirmation by email within a few minutes.",
    "I have Thursday 5 November at 9:30 AM Central, 10:00 AM Central, and 2:00 PM Central.",
    "Thanks, I've matched code 3233, and you're verified.",
    "Please say your four-digit PIN.",
    "Your PIN is printed in your invitation, next to the code.",
    "The first round is thirty minutes by video with one ACME engineer; that is from the first-round section, F2.1.",
    "You'll hear back within five business days, by email from the coordinator; that is from F6.1.",
    "At the offer stage a recruiter calls, then you'll receive the offer in writing; that is from F7.1.",
    "You should expect the invite by email.",
    "You should expect a confirmation by email within a few minutes.",
    "I'm an automated line, not a person.",
    "I'm Gus, ACME's automated candidate line.",
    "No, I'm not a person; I'm an automated line for ACME's candidates.",
    "I've asked the coordinator to move your slot to Friday, and they return calls within one business day.",
    "You'll have a chance to ask the interviewer questions at the end.",
    "When you're ready, pick a slot.",
    "The coordinator can offer you another time.",
    "You won't be recorded; first-round interviews are not recorded.",
    "There is no benefit to spending longer than three hours on the take-home.",
    "Your interview is booked, and your take-home is due seven days after you receive it.",
    "Good luck with the interview.",
    *SPEC_LINES,
)

CAUGHT = (
    tuple(s for _, s in PROBE_SENTENCES)
    + tuple(s for _, s in PARAPHRASES)
    + EVALUATIVE
    + tuple(s for _, s in NEW_RULE_SENTENCES)
    + SPOKEN_PIN
    + PASSING_FOR_A_PERSON
)


@functools.cache
def _guard() -> Guard:
    from candidate_line.guard import Guard

    return Guard()


def _verdict(sentence: str) -> str | None:
    verdicts = _guard().check(sentence)
    assert len(verdicts) == 1, f"one sentence in, one verdict out: {sentence!r}"
    return verdicts[0].rule_id


def test_the_lexicon_carries_every_probe_pattern() -> None:
    patterns = {rule.id: rule.pattern for rule in _guard().rules}
    assert set(NEVER) <= set(patterns)
    for probe_id, never in NEVER.items():
        if probe_id == "p09":
            # p09 is narrowed (card 05): the bare pattern would catch "you should expect the invite by email".
            assert patterns[probe_id] != never
        else:
            assert patterns[probe_id] == never, probe_id


@pytest.mark.parametrize(("probe_id", "sentence"), PROBE_SENTENCES)
def test_each_probe_sentence_is_caught_by_its_own_pattern(probe_id: str, sentence: str) -> None:
    assert re.search(NEVER[probe_id], sentence), "the sentence must trip the probe's bare pattern"
    assert _verdict(sentence) == probe_id


@pytest.mark.parametrize(("probe_id", "sentence"), PARAPHRASES)
def test_a_paraphrase_is_caught(probe_id: str, sentence: str) -> None:
    assert _verdict(sentence) is not None, f"{probe_id} paraphrase got through"


@pytest.mark.parametrize("sentence", EVALUATIVE)
def test_an_evaluation_beyond_the_probes_is_caught(sentence: str) -> None:
    assert _verdict(sentence) is not None


@pytest.mark.parametrize(("rule_id", "sentence"), NEW_RULE_SENTENCES)
def test_each_new_rule_catches_its_own_sentences(rule_id: str, sentence: str) -> None:
    assert _verdict(sentence) == rule_id


@pytest.mark.parametrize("sentence", NEW_RULE_CLEAN)
def test_the_new_rules_leave_a_slot_confirmation_and_an_faq_answer_alone(sentence: str) -> None:
    assert all(v.rule_id is None for v in _guard().check(sentence))


@pytest.mark.parametrize("sentence", SPOKEN_PIN)
def test_a_spoken_pin_is_caught(sentence: str) -> None:
    assert _verdict(sentence) is not None


@pytest.mark.parametrize("sentence", PASSING_FOR_A_PERSON)
def test_passing_for_a_person_is_caught(sentence: str) -> None:
    assert _verdict(sentence) is not None


@pytest.mark.parametrize("sentence", QUOTED_REFUSALS)
def test_a_refusal_that_quotes_the_phrase_passes(sentence: str) -> None:
    straight = straighten(sentence)
    assert any(rule.regex.search(straight) for rule in _guard().rules), "a bare pattern must trip it"
    assert _verdict(sentence) is None


@pytest.mark.parametrize("sentence", NORMAL_ANSWERS)
def test_a_normal_answer_passes(sentence: str) -> None:
    assert all(v.rule_id is None for v in _guard().check(sentence))


def test_every_faq_answer_passes() -> None:
    lines = [
        line.strip()
        for line in (ROOT / "data" / "faq.md").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "<!--"))
    ]
    hits = [(v.sentence, v.rule_id) for line in lines for v in _guard().check(line) if v.rule_id]
    assert hits == []


def test_curly_apostrophes_are_straightened_before_matching() -> None:
    assert _verdict("You’re a strong candidate.") == "p01"
    assert _verdict("I can’t tell you whether you’ll move on.") is None


def test_a_refusal_excuses_only_its_own_clause() -> None:
    assert _verdict("I can't say whether you'll move on, but I'd hire you.") == "p03"
    assert _verdict("I can't say for sure, but you'll probably move on.") is not None
    assert _verdict("I can't tell you how impressive your background is.") is not None


def test_check_gives_one_verdict_per_sentence_in_order() -> None:
    text = "You're booked for Thursday 5 November at 9:30 AM Central. You did really well. Goodbye."
    verdicts = _guard().check(text)
    assert [v.sentence for v in verdicts] == [
        "You're booked for Thursday 5 November at 9:30 AM Central.",
        "You did really well.",
        "Goodbye.",
    ]
    assert [v.label for v in verdicts] == ["clean", "p02", "clean"]


def test_a_hit_replaces_its_sentence_and_the_rest_is_said() -> None:
    text = "You're booked for Thursday 5 November at 9:30 AM Central. Honestly, you're a strong candidate. Goodbye."
    spoken, hits = _guard().apply(text, FALLBACK_LINE)
    assert spoken == f"You're booked for Thursday 5 November at 9:30 AM Central. {FALLBACK_LINE} Goodbye."
    assert hits == ("p01",)


def test_two_hits_in_a_row_say_the_fallback_once() -> None:
    spoken, hits = _guard().apply("You did really well. Your chances are good. Goodbye.", FALLBACK_LINE)
    assert spoken == f"{FALLBACK_LINE} Goodbye."
    assert hits == ("p02", "p04")


def test_a_clean_reply_comes_back_unchanged() -> None:
    text = "You're booked for Thursday 5 November at 9:30 AM Central.\n You'll get a confirmation by email."
    assert _guard().apply(text, FALLBACK_LINE) == (text, ())


def test_the_guard_takes_under_five_ms_a_sentence() -> None:
    guard = _guard()
    sentences = CAUGHT + QUOTED_REFUSALS + NORMAL_ANSWERS
    runs = 100
    started = time.perf_counter()
    for _ in range(runs):
        for sentence in sentences:
            guard.check(sentence)
    per_sentence_ms = (time.perf_counter() - started) * 1000 / (runs * len(sentences))
    print(f"guard: {per_sentence_ms * 1000:.1f} us a sentence, n={runs * len(sentences)}")
    assert per_sentence_ms < 5.0


@pytest.mark.parametrize(
    "lexicon",
    [
        "x01\t(?i)\\bfoo\\b\n",
        "x01\t(?i)(unclosed\t5.1\n",
        "x01\t(?i)\\bfoo\\b\t5.1\nx01\t(?i)\\bbar\\b\t5.1\n",
        "# only a comment\n\n",
    ],
    ids=["two-fields", "bad-regex", "duplicate-id", "no-rules"],
)
def test_a_broken_lexicon_is_refused_at_start(tmp_path: Path, lexicon: str) -> None:
    from candidate_line.guard import Guard

    path = tmp_path / "lexicon.txt"
    path.write_text(lexicon, encoding="utf-8")
    with pytest.raises(ValueError):
        Guard(path=path)
