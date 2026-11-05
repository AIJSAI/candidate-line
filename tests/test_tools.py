"""The tools over data/: the parsers, verification, slots and booking, the hand-offs, the FAQ and the ledger file.

Every ledger here pins its clock to the afternoon before the first slot, so no test waits for the calendar or
breaks after it. The PINs are the synthetic ones in data/candidates.yaml.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from candidate_line.settings import DEFAULT_STATE_PATH, Settings
from candidate_line.tools import (
    OUTBOUND_TOOL_NAMES,
    OUTBOUND_TOOL_SPECS,
    TOOL_NAMES,
    TOOL_SPECS,
    Ledger,
    ToolOutcome,
    actions,
    code_digits,
    faq_index,
    pin_digits,
)
from candidate_line.tools.ledger import CANDIDATES_PATH, SLOTS_PATH, parse_day, spoken_label
from candidate_line.turn import TurnContext

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)  # 12:00 Central on the day before the first slot
HANNAH = ("ACME-3233", "9683")  # invited, no slot
PRIYA = ("ACME-6792", "4731")  # booked S1109-1400
DANIEL = ("ACME-1431", "0963")  # booked, and the PIN with a leading zero
NORA = ("ACME-7356", "5640")  # first round done


def _ledger(state_path: Path | str | None = None, now: datetime = NOW) -> Ledger:
    return Ledger(CANDIDATES_PATH, SLOTS_PATH, state_path, now=lambda: now)


def _ctx(ledger: Ledger | None = None) -> TurnContext:
    return TurnContext(call_id="CA-test", channel="text", system="", ledger=ledger or _ledger())


def _run(ctx: TurnContext, name: str, **args: Any) -> tuple[ToolOutcome, dict[str, Any]]:
    outcome = actions.run_tool(name, args, ctx)
    return outcome, json.loads(outcome.content)


def _next_turn(ctx: TurnContext) -> None:
    """What run_turn does at a turn's start for the miss count: one try per thing the caller said."""
    ctx.data.pop("missed_this_turn", None)


def _verify(ctx: TurnContext, who: tuple[str, str] = HANNAH) -> dict[str, Any]:
    _, body = _run(ctx, "verify_caller", code=who[0], pin=who[1])
    assert body.get("verified") is True, body
    return body


# The parsers, on what the transcriber wrote.


@pytest.mark.parametrize(
    "heard",
    ["ACME-3233", "acme 3233", "acne 3233", "application 3233", "3,233", "32 33", "ACME 3 2 3 3", "3233."],
)
def test_a_code_is_its_four_digits_however_the_transcriber_spelled_it(heard: str) -> None:
    assert code_digits(heard) == "3233"


def test_spelled_digits_count_only_when_there_are_no_numerals() -> None:
    assert code_digits("three two three three") == "3233"
    assert code_digits("oh, one sec, it's 3233") == "3233"
    assert code_digits(3233) == "3233"


@pytest.mark.parametrize("heard", ["", None, "ACME", "323", "ACME-32334", "3233 and 9683", True])
def test_anything_but_four_digits_is_no_code(heard: object) -> None:
    assert code_digits(heard) is None


def test_a_pin_keeps_its_leading_zero_and_three_digits_get_it_back() -> None:
    assert pin_digits("0963") == "0963"
    assert pin_digits("963") == "0963"
    assert pin_digits("zero nine six three") == "0963"
    assert pin_digits("9,683") == "9683"
    assert pin_digits("96 83") == "9683"
    assert pin_digits("96") is None
    assert pin_digits("96834") is None


# Verification.


def test_a_match_makes_the_caller_that_candidate_and_reads_the_code_back_as_digits() -> None:
    ctx = _ctx()
    outcome, body = _run(ctx, "verify_caller", code="acne 3,233", pin="96 83")
    assert not outcome.is_error and body["verified"] is True
    assert ctx.data["candidate"] == "ACME-3233"
    assert body["first_name"] == "Hannah" and body["name"] == "Hannah Haddad"
    assert body["role"] == "Site Reliability Engineer" and body["stage"] == "invited"
    assert body["booked_slot"] is None and body["code_digits"] == "3 2 3 3"
    assert outcome.state == {"booked_slot": None, "moves_used": 0, "callback_requested": False}
    assert "9683" not in outcome.content


def test_a_booked_candidate_hears_their_slot_spoken() -> None:
    body = _verify(_ctx(), PRIYA)
    assert body["booked_slot"] == "Monday 9 November at 2:00 PM Central"
    assert body["booked_slot_id"] == "S1109-1400" and body["can_book"] is False


def test_a_miss_is_counted_and_never_echoes_the_pin() -> None:
    ctx = _ctx()
    outcome, body = _run(ctx, "verify_caller", code="ACME-3233", pin="1234")
    assert not outcome.is_error and body["verified"] is False
    assert ctx.data["verify_failures"] == 1 and "candidate" not in ctx.data
    assert body["code_heard"] == "3 2 3 3" and "1234" not in outcome.content
    # A second reading of the same words in the same turn spends no second try.
    _run(ctx, "verify_caller", code="ACME-3233", pin="1243")
    assert ctx.data["verify_failures"] == 1
    # A real code with the wrong PIN reads exactly like a code that does not exist.
    _next_turn(ctx)
    _, unknown = _run(ctx, "verify_caller", code="ACME-0000", pin="1234")
    assert unknown["reason"] == body["reason"] and ctx.data["verify_failures"] == 2
    assert "next" not in body and "callback" in unknown["next"]  # the second miss offers a callback


def test_a_verified_caller_cannot_switch_to_another_candidate_but_may_verify_again() -> None:
    ctx = _ctx()
    _verify(ctx)
    outcome, body = _run(ctx, "verify_caller", code="ACME-1022", pin="7613")  # Mei's, synthetic
    assert outcome.is_error and "already verified" in body["error"] and ctx.data["candidate"] == HANNAH[0]
    _, again = _run(ctx, "verify_caller", code=HANNAH[0], pin=HANNAH[1])  # a superseded turn's carried words
    assert again["verified"] is True


def test_every_pin_given_on_the_call_is_kept_for_the_guard_and_never_in_a_result() -> None:
    ctx = _ctx()
    outcome, _ = _run(ctx, "verify_caller", code="ACME-3233", pin="7613")
    _verify(ctx)
    assert ctx.data["pins_heard"] == ["7613", "9683"] and "7613" not in outcome.content


def test_an_unreadable_pin_is_asked_again_and_not_counted() -> None:
    ctx = _ctx()
    outcome, body = _run(ctx, "verify_caller", code="ACME-3233", pin="96")
    assert outcome.is_error and "PIN" in body["error"]
    assert ctx.data.get("verify_failures", 0) == 0


def test_the_line_stops_checking_after_two_misses_even_for_the_right_pair() -> None:
    # Spec 3.1: a second miss offers a callback and ends the checking, even when the caller insists.
    assert actions.MAX_VERIFY_ATTEMPTS == 2
    ctx = _ctx()
    _run(ctx, "verify_caller", code="ACME-3233", pin="1111")
    _next_turn(ctx)
    _, second = _run(ctx, "verify_caller", code="ACME-3233", pin="2222")
    _next_turn(ctx)
    assert second["tries_left"] == 0 and "No other code or PIN is checked" in second["next"]
    outcome, body = _run(ctx, "verify_caller", code=HANNAH[0], pin=HANNAH[1])
    assert outcome.is_error and "callback" in body["error"] and "candidate" not in ctx.data
    assert ctx.data["verify_failures"] == 2 and HANNAH[1] not in outcome.content
    # Never checked, but kept, so the guard still catches the insisted PIN if Gus says it back.
    assert HANNAH[1] in ctx.data["pins_heard"]


@pytest.mark.parametrize("heard", ["963", "0963", "0 9 6 3", "zero nine six three"])
def test_the_leading_zero_pin_verifies_as_heard(heard: str) -> None:
    ctx = _ctx()
    _, body = _run(ctx, "verify_caller", code="ACME 1431", pin=heard)
    assert body["verified"] is True and ctx.data["candidate"] == DANIEL[0]


def test_a_pin_the_data_file_wrote_as_a_number_keeps_its_zero(tmp_path: Path) -> None:
    rows = CANDIDATES_PATH.read_text(encoding="utf-8").replace("pin: 0963", "pin: 963")
    assert "pin: 963" in rows
    (tmp_path / "candidates.yaml").write_text(rows, encoding="utf-8")
    ledger = Ledger(tmp_path / "candidates.yaml", SLOTS_PATH, None, now=lambda: NOW)
    assert ledger.match("1431", "0963") is not None


# Slots and booking.


def test_slots_need_a_verified_caller() -> None:
    ctx = _ctx()
    for name, args in (("list_open_slots", {}), ("book_slot", {"slot_id": "S1105-0930"}), ("move_slot", {})):
        outcome = actions.run_tool(name, args, ctx)
        assert outcome.is_error and "verified" in json.loads(outcome.content)["error"], name
    assert ctx.ledger is not None and ctx.ledger.bookings() == {}


def test_open_slots_are_nearest_first_at_most_six_and_spoken_in_central_time() -> None:
    ctx = _ctx()
    _verify(ctx)
    _, body = _run(ctx, "list_open_slots")
    assert len(body["slots"]) == 6
    assert body["slots"][0] == {"id": "S1105-0930", "label": "Thursday 5 November at 9:30 AM Central"}
    assert [s["id"] for s in body["slots"]][-2:] == ["S1106-0930", "S1106-1000"]


def test_a_started_slot_is_not_offered() -> None:
    later = datetime(2026, 11, 5, 15, 45, tzinfo=UTC)  # 9:45 Central, after the first slot began
    ctx = _ctx(_ledger(now=later))
    _verify(ctx)
    _, body = _run(ctx, "list_open_slots")
    assert body["slots"][0]["id"] == "S1105-1000"


def test_a_day_narrows_the_list_and_an_unknown_day_says_so() -> None:
    ctx = _ctx()
    _verify(ctx)
    _, friday = _run(ctx, "list_open_slots", day="Friday 6 November")
    assert [s["id"] for s in friday["slots"]] == ["S1106-0930", "S1106-1000", "S1106-1400", "S1106-1530"]
    _, monday = _run(ctx, "list_open_slots", day="Monday afternoon")
    assert [s["id"] for s in monday["slots"]] == [
        "S1109-1530",
        "S1116-1400",
        "S1116-1530",
    ]  # 9 Nov 2 PM is held
    _, tomorrow = _run(ctx, "list_open_slots", day="tomorrow")
    assert "not understood" in tomorrow["note"] and len(tomorrow["slots"]) == 6
    assert "never call one today or tomorrow" in tomorrow["note"]
    assert parse_day("the 6th of November") == parse_day("6 November")
    assert parse_day("I may be free") is None


def test_a_time_zone_adds_each_slot_in_the_caller_s_time_and_a_bad_one_says_so() -> None:
    ctx = _ctx()
    _verify(ctx)
    _, london = _run(ctx, "list_open_slots", day="Thursday 5 November", time_zone="Europe/London")
    first = london["slots"][0]
    assert first["label"] == "Thursday 5 November at 9:30 AM Central"
    assert first["local"] == "Thursday 5 November at 3:30 PM London time"
    _, bad = _run(ctx, "list_open_slots", time_zone="Moon/Base")
    assert "local" not in bad["slots"][0] and "Central time only" in bad["note_time_zone"]


def test_spoken_label_is_the_same_words_everywhere() -> None:
    assert spoken_label(datetime.fromisoformat("2026-11-12T14:00:00-06:00")) == (
        "Thursday 12 November at 2:00 PM Central"
    )


def test_booking_writes_the_slot_and_a_superseded_turn_undoes_it() -> None:
    ctx = _ctx()
    _verify(ctx)
    outcome, body = _run(ctx, "book_slot", slot_id="s1105-0930")
    assert not outcome.is_error and body["booked"] is True
    assert body["slot_id"] == "S1105-0930" and body["slot"] == "Thursday 5 November at 9:30 AM Central"
    assert body["invited_at"] == "2026-10-29T04:10:00-06:00"
    assert body["confirmation"].endswith("(F3.1).") and outcome.cited == ("F3.1",)
    assert outcome.state == {"booked_slot": "S1105-0930", "moves_used": 0, "callback_requested": False}
    ledger = ctx.ledger
    assert ledger is not None and not ledger.is_open("S1105-0930")
    assert outcome.undo is not None
    outcome.undo()
    outcome.undo()  # a second reversal is a no-op
    assert ledger.is_open("S1105-0930") and ledger.state(HANNAH[0])["booked_slot"] is None


def test_undo_never_releases_a_slot_held_before_the_call() -> None:
    ledger = _ledger()
    assert ledger.unbook(PRIYA[0], "S1109-1400") is False
    assert ledger.state(PRIYA[0])["booked_slot"] == "S1109-1400"


def test_a_candidate_who_holds_a_slot_is_told_the_move_goes_to_the_coordinator() -> None:
    ctx = _ctx()
    _verify(ctx, PRIYA)
    outcome, body = _run(ctx, "book_slot", slot_id="S1105-0930")
    assert outcome.is_error and body["booked"] is False and "coordinator" in body["error"]
    assert body["booked_slot"] == "Monday 9 November at 2:00 PM Central"
    assert outcome.undo is None and ctx.ledger is not None and ctx.ledger.is_open("S1105-0930")


def test_a_slot_someone_else_holds_or_no_slot_at_all_is_refused() -> None:
    ctx = _ctx()
    _verify(ctx)
    held, body = _run(ctx, "book_slot", slot_id="S1112-1400")
    assert held.is_error and "not open" in body["error"]
    missing, body = _run(ctx, "book_slot", slot_id="S9999-0000")
    assert missing.is_error and "no slot" in body["error"]
    bare, body = _run(ctx, "book_slot")
    assert bare.is_error and "id" in body["error"]


def test_a_finished_first_round_books_nothing() -> None:
    ctx = _ctx()
    _verify(ctx, NORA)
    outcome, body = _run(ctx, "book_slot", slot_id="S1105-0930")
    assert outcome.is_error and "first round is done" in body["error"]


# The hand-offs.


def test_a_move_is_handed_to_the_coordinator_and_books_nothing() -> None:
    ctx = _ctx()
    _verify(ctx, PRIYA)
    ledger = ctx.ledger
    assert ledger is not None
    before = [s.id for s in ledger.open_slots()]
    outcome, body = _run(ctx, "move_slot", preferred="S1106-0930")
    assert not outcome.is_error and body["recorded"] is True and body["moved"] is False
    assert body["preferred"] == "Friday 6 November at 9:30 AM Central"
    assert outcome.escalate is not None and outcome.escalate.reason.startswith("move request")
    assert "Friday 6 November at 9:30 AM Central" in outcome.escalate.reason
    assert outcome.escalate.suggested_action == "call the candidate back about the move"
    assert outcome.state == {"booked_slot": "S1109-1400", "moves_used": 0, "callback_requested": False}
    assert [s.id for s in ledger.open_slots()] == before
    # The reply is fixed words (spec section 4): the promise and the slot that stays, never the model's own wording.
    assert outcome.say is not None and "within one business day" in outcome.say
    assert outcome.say.endswith(f"your interview stays {ledger.booked_slot(PRIYA[0]).label}.")
    assert ledger.moves()[0]["code"] == PRIYA[0] and ledger.moves()[0]["current"] == "S1109-1400"


def test_a_move_with_no_slot_to_move_is_refused() -> None:
    ctx = _ctx()
    _verify(ctx)
    outcome, body = _run(ctx, "move_slot", preferred="Friday")
    assert outcome.is_error and outcome.escalate is None and "book" in body["error"]


def test_an_unverified_caller_can_ask_for_a_callback() -> None:
    ctx = _ctx()
    outcome, body = _run(ctx, "request_callback", best_time="after 5 PM", reason="none of the slots work")
    assert not outcome.is_error and body["recorded"] is True and body["for"] == "the caller"
    assert outcome.state is None
    assert outcome.escalate is not None and "the caller" in outcome.escalate.reason
    assert "none of the slots work" in outcome.escalate.reason and "after 5 PM" in outcome.escalate.reason
    assert ctx.ledger is not None and ctx.ledger.callbacks()[0]["code"] is None


def test_a_verified_callback_sets_the_flag_and_never_carries_the_pin_or_a_number() -> None:
    ctx = _ctx()
    _verify(ctx)
    # Zeros, so the test holds no real number; the mask keys on the digit count, not the digits.
    outcome, _ = _run(ctx, "request_callback", reason="my PIN 96 83 failed, ring 000 000 0000")
    assert outcome.state is not None and outcome.state["callback_requested"] is True
    assert outcome.escalate is not None
    saved = json.dumps(ctx.ledger.callbacks()) if ctx.ledger else ""
    for text in (outcome.content, outcome.escalate.reason, saved):
        assert "96 83" not in text and "9683" not in text and "000 000 0000" not in text


@pytest.mark.parametrize(
    "reason",
    [
        "code 3233 and 9683, call me",
        "my pin nine six eight three did not work",
        "I gave 9 6 8 3 but it failed",
    ],
)
def test_an_unverified_callback_never_carries_a_bare_or_spelled_pin(reason: str) -> None:
    ctx = _ctx()
    outcome, _ = _run(ctx, "request_callback", reason=reason, best_time="after 3:30 PM")
    assert outcome.escalate is not None
    saved = json.dumps(ctx.ledger.callbacks()) if ctx.ledger else ""
    for text in (outcome.content, outcome.escalate.reason, saved):
        assert "9683" not in text and "9 6 8 3" not in text and "nine six" not in text
    assert "after 3:30 PM" in outcome.escalate.reason  # a time keeps its digits


# The FAQ.


def test_a_question_gets_the_named_sections_and_cites_them() -> None:
    outcome, body = _run(_ctx(), "answer_question", section_ids=["f2.1", "F2.1", "F3.2"])
    assert outcome.cited == ("F2.1", "F3.2")
    first = body["sections"][0]
    assert first["id"] == "F2.1" and first["title"] == "How long is it, and in what format?"
    assert first["text"].startswith("Thirty minutes, by video")
    _, whole = _run(_ctx(), "answer_question", section_ids="F3")
    assert [s["id"] for s in whole["sections"]] == ["F3.1", "F3.2", "F3.3", "F3.4", "F3.5"]


@pytest.mark.parametrize("sent", ['["F2.1"]', "['F2.1', 'F3.2']"])
def test_section_ids_sent_as_json_text_still_find_their_sections(sent: str) -> None:
    outcome, _ = _run(_ctx(), "answer_question", section_ids=sent)
    assert outcome.cited[0] == "F2.1" and not outcome.is_error


def test_a_question_the_faq_does_not_cover_returns_no_section() -> None:
    # F10.1 since F9 landed (card 08): an id no FAQ section has.
    outcome, body = _run(_ctx(), "answer_question", section_ids=["F10.1", "salary"])
    assert not outcome.is_error and body == {"sections": []} and outcome.cited == ()


def test_the_index_names_every_section_under_its_heading() -> None:
    lines = faq_index().splitlines()
    assert len(lines) == 9 and lines[0].startswith("F1 The process: F1.1 What are the stages?")
    assert "F3.2 Can I move my slot?" in lines[2] and "Once, through the coordinator" not in faq_index()


def test_end_call_hangs_up() -> None:
    outcome, _ = _run(_ctx(), "end_call")
    assert outcome.hang_up and not outcome.is_error


# The ledger file and the settings behind it.


def test_every_change_is_written_through_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "var" / "state.json"
    ctx = _ctx(_ledger(path))
    _verify(ctx)
    _run(ctx, "book_slot", slot_id="S1105-1000")
    _run(ctx, "request_callback", best_time="Friday")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["bookings"]["ACME-3233"]["slot_id"] == "S1105-1000"
    assert saved["callbacks"][0]["code"] == "ACME-3233"
    assert "9683" not in path.read_text(encoding="utf-8")
    again = _ledger(path)
    assert again.state("ACME-3233") == {
        "booked_slot": "S1105-1000",
        "moves_used": 0,
        "callback_requested": True,
    }
    assert not again.is_open("S1105-1000")


def test_a_change_from_another_ledger_on_the_same_file_is_seen(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    first, second = _ledger(path), _ledger(path)
    first.book("ACME-9004", "S1105-0930")
    assert not second.is_open("S1105-0930")
    with pytest.raises(actions.LedgerError):
        second.book("ACME-2490", "S1105-0930")
    path.unlink()  # a reset between walks
    assert first.is_open("S1105-0930")


def test_an_unreadable_state_file_is_set_aside_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    ledger = _ledger(path)
    assert ledger.bookings() == {}
    assert [p.name.startswith("state.json.bad-") for p in tmp_path.iterdir()].count(True) == 1


def test_an_unreadable_state_file_is_read_as_set_aside_until_it_is_restored(tmp_path: Path) -> None:
    """F6: what intake and the dialler read, on this ledger and on a new one over the same file."""
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    assert ledger.is_set_aside() is False and ledger.set_aside_at is None
    path.write_text("{not json", encoding="utf-8")
    assert ledger.is_set_aside() is True and ledger.set_aside_at is not None
    assert _ledger(path).is_set_aside() is True
    for aside in tmp_path.glob("state.json.bad-*"):
        aside.unlink()  # the operator read it and let it go
    assert ledger.is_set_aside() is False and ledger.set_aside_at is None


def test_an_unreadable_state_file_that_cannot_be_moved_is_never_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: a fault that stops the read can stop the move too; the next change must not then replace the records
    it could not read with an empty file."""
    from candidate_line.tools import ledger as ledger_module

    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    real_replace = ledger_module.os.replace

    def no_move(src, dst):
        if ".bad-" in str(dst):
            raise OSError("read-only")
        return real_replace(src, dst)

    monkeypatch.setattr(ledger_module.os, "replace", no_move)
    ledger = _ledger(path)
    assert ledger.is_set_aside() is True
    with pytest.raises(actions.LedgerError):
        ledger.book("ACME-9004", "S1105-0930")
    assert path.read_text(encoding="utf-8") == "{not json"
    monkeypatch.setattr(ledger_module.os, "replace", real_replace)
    path.write_text("{}", encoding="utf-8")  # the fault cleared and the file reads again
    assert ledger.is_set_aside() is False
    ledger.book("ACME-9004", "S1105-0930")


def test_two_calls_booking_one_slot_at_once_get_it_once(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "state.json")
    won: list[str] = []

    def book(code: str) -> None:
        try:
            ledger.book(code, "S1105-1400")
            won.append(code)
        except actions.LedgerError:
            pass

    threads = [
        threading.Thread(target=book, args=(code,)) for code in ("ACME-9004", "ACME-2490", "ACME-1022")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1 and len(_ledger(tmp_path / "state.json").bookings()) == 1


def test_the_file_backed_default_is_one_ledger_for_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    assert Ledger.default() is Ledger.default()
    monkeypatch.setenv("STATE_PATH", ":memory:")
    assert Ledger.default() is not Ledger.default()


def test_state_path_comes_from_the_environment() -> None:
    assert Settings.from_env({}).state_path == str(DEFAULT_STATE_PATH)
    assert DEFAULT_STATE_PATH.parts[-2:] == ("var", "state.json")
    assert Settings.from_env({"STATE_PATH": ""}).state_path == str(DEFAULT_STATE_PATH)
    assert Settings.from_env({"STATE_PATH": ":memory:"}).state_path is None
    assert Settings.from_env({"STATE_PATH": "/x/s.json"}).state_path == "/x/s.json"


def test_a_call_with_no_ledger_gets_the_default_and_keeps_it() -> None:
    ctx = TurnContext(call_id="CA-default", channel="text", system="")
    _run(ctx, "request_callback")
    kept = ctx.ledger
    assert kept is not None and kept.state_path is None  # conftest sets STATE_PATH=:memory:
    _run(ctx, "request_callback")
    assert ctx.ledger is kept and len(kept.callbacks()) == 2


# The dispatcher.


def test_the_tools_are_named_as_the_eval_cases_name_them() -> None:
    # record_answer and stop_calls since card 08 (DR-025 section 1): an applicant who calls in answers the questions
    # and can stop the calls on the inbound line too.
    assert TOOL_NAMES == (
        "verify_caller",
        "list_open_slots",
        "book_slot",
        "move_slot",
        "answer_question",
        "request_callback",
        "end_call",
        "record_answer",
        "stop_calls",
    )
    assert OUTBOUND_TOOL_NAMES == (
        "confirm_applicant",
        "record_answer",
        "stop_calls",
        "list_open_slots",
        "book_slot",
        "answer_question",
        "request_callback",
        "end_call",
    )
    assert set(TOOL_NAMES) | set(OUTBOUND_TOOL_NAMES) == set(actions._TOOLS)
    for spec in TOOL_SPECS + OUTBOUND_TOOL_SPECS:
        assert spec.input_schema["type"] == "object" and spec.description
        # No description names a record's id, a question's id or a slot for the model to copy.
        text = json.dumps([spec.description, spec.input_schema])
        assert not re.search(r"ACME-\d|S\d{4}-\d{4}|\bq\d\b", text), spec.name


def test_verify_caller_is_refused_on_a_call_the_line_placed() -> None:
    # An outbound call is bound to the application it was placed for: a candidate's code never switches it.
    ctx = _ctx()
    ctx.data["outbound"] = {
        "code": "ACME-3108",
        "first_name": "Lerato",
        "dial_id": "D-0123456789ab",
        "attempt": 1,
    }
    outcome, body = _run(ctx, "verify_caller", code=HANNAH[0], pin=HANNAH[1])
    assert outcome.is_error and "confirm_applicant" in body["error"] and "candidate" not in ctx.data
    _, slots = _run(ctx, "list_open_slots")
    assert slots["error"] == "The applicant is not confirmed yet. Ask for the PIN first."


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("transfer_money", {}),
        ("verify_caller", "ACME-3233"),
        ("verify_caller", {"code": ["ACME", 3233], "pin": {"pin": 1}}),
        ("verify_caller", {}),
        ("book_slot", {"slot_id": {"id": "S1105-0930"}}),
        ("answer_question", {"section_ids": 21}),
        ("answer_question", {}),
        ("list_open_slots", {"day": ["Friday"]}),
        ("request_callback", {"reason": {"why": "x"}}),
        ("end_call", None),
    ],
)
def test_run_tool_never_raises(name: str, args: Any) -> None:
    outcome = actions.run_tool(name, args, _ctx())
    assert isinstance(outcome, ToolOutcome)
    json.loads(outcome.content)


def test_a_failure_inside_a_tool_is_one_sentence_and_logs_no_argument(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("secret 9683")

    ctx = _ctx()
    monkeypatch.setattr(Ledger, "match", broken)
    outcome = actions.run_tool("verify_caller", {"code": HANNAH[0], "pin": HANNAH[1]}, ctx)
    assert outcome.is_error and "callback" in json.loads(outcome.content)["error"]
    assert "RuntimeError" in caplog.text and "9683" not in caplog.text


def test_a_bare_code_beside_a_pin_is_the_code_whatever_the_transcriber_put_between_its_digits() -> None:
    from candidate_line.tools.codes import normalise_transcript

    # the operator's first call to the container, 2026-11-04 20:14 CT: the hyphen cost a turn
    assert (
        normalise_transcript("OK, it's 323-3 and the PIN is 9683.") == "OK, it's ACME-3233 and the PIN 9683."
    )
    assert normalise_transcript("32 33, pin 9683") == "ACME-3233, PIN 9683"
    assert (
        normalise_transcript("three two three three and pin nine six eight three") == "ACME-3233 and PIN 9683"
    )
    # a time is not a code, and a code already written stays as it is
    assert normalise_transcript("Thursday at 9:30, PIN 9683") == "Thursday at 9:30, PIN 9683"
    assert (
        normalise_transcript("ACME-3233, PIN 9683, and 1234 is my street")
        == "ACME-3233, PIN 9683, and 1234 is my street"
    )
    assert normalise_transcript("it's 3233") == "it's 3233"  # no PIN beside it: four digits may be anything


@pytest.mark.parametrize(
    ("heard", "brain_reads"),
    [
        # the deployed line's hearing of CL-021 on 2026-11-05 (the store's masked final "application *,****,***.")
        (
            "I'm calling about application 3,2339,683.",
            "I'm calling about application code ACME-3233 PIN 9683.",
        ),
        ("application 3,233,968,3", "application code ACME-3233 PIN 9683"),
        ("it's 32,339,683", "it's ACME-3233 PIN 9683"),
    ],
)
def test_eight_comma_grouped_digits_with_no_code_are_the_code_and_the_pin(
    heard: str, brain_reads: str
) -> None:
    from candidate_line.tools.codes import normalise_transcript

    assert normalise_transcript(heard) == brain_reads


@pytest.mark.parametrize(
    ("heard", "brain_reads"),
    [
        ("ACME-3233, 9,683", "ACME-3233, PIN 9683"),
        ("acne 3233 96,83", "ACME-3233 PIN 9683"),
        ("code 3233 and 9,683", "code ACME-3233 and PIN 9683"),
        ("acne 3,233 9,683", "ACME-3233 PIN 9683"),
    ],
)
def test_four_comma_grouped_digits_right_after_a_code_are_its_pin(heard: str, brain_reads: str) -> None:
    from candidate_line.tools.codes import normalise_transcript

    assert normalise_transcript(heard) == brain_reads


def test_a_comma_grouped_run_is_otherwise_only_its_digits() -> None:
    from candidate_line.tools.codes import normalise_transcript

    # eight digits beside a code already said are not a second code, and four with no code before them are no PIN
    assert normalise_transcript("ACME-3233, ref 12,345,678") == "ACME-3233, ref 12345678"
    assert normalise_transcript("it's 9,683") == "it's 9683"
    # a PIN word already there keeps the run a PIN, and a list of small numbers is not a thousands run
    assert normalise_transcript("ACME-3233 PIN 9,683") == "ACME-3233 PIN 9683"
    assert normalise_transcript("I have 2,3 questions") == "I have 2,3 questions"


@pytest.mark.parametrize(
    ("heard", "brain_reads"),
    [
        # CL-024's second line, "Sorry, PIN 2222.", as Transcribe wrote it on 2026-11-05 (DR-024)
        ("Sorry, 102222.", "Sorry, PIN 2222."),
        ("Sorry, ten 2222.", "Sorry, PIN 2222."),
        ("Sorry, 102,222.", "Sorry, PIN 2222."),
    ],
)
def test_the_pin_word_heard_as_ten_before_four_digits_is_the_pin(heard: str, brain_reads: str) -> None:
    from candidate_line.tools.codes import normalise_transcript

    assert normalise_transcript(heard) == brain_reads


def test_a_ten_before_four_digits_is_left_alone_unless_it_is_the_whole_mishearing() -> None:
    from candidate_line.tools.codes import normalise_transcript

    # six digits that do not start with 10, and runs of five or seven that do, are not a PIN heard as ten
    assert normalise_transcript("Sorry, 512222.") == "Sorry, 512222."
    assert normalise_transcript("Sorry, 10222.") == "Sorry, 10222."
    assert normalise_transcript("Sorry, 1022222.") == "Sorry, 1022222."
    # a PIN word or a code already there keeps the rules that read them
    assert normalise_transcript("PIN 102222") == "PIN 102222"
    assert normalise_transcript("ACME-3233, 102222") == "ACME-3233, 102222"
    # eight comma-grouped digits that start with 10 go to the code-and-PIN rule first (ACME-1022 is Mei's code)
    assert normalise_transcript("it's 10,227,613") == "it's ACME-1022 PIN 7613"
