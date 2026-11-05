"""The ledger's outbound half (DR-025 section 7): applications, answers, screens, dials and opt-outs, on the
synthetic fixtures and a state file in tmp_path.

The number used here is a fictional 555-01xx one, built at run time; the fixtures hold none (DR-025 section 6).
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from candidate_line.outbound.contacts import Contacts
from candidate_line.settings import Settings
from candidate_line.tools import ledger as ledger_module
from candidate_line.tools.ledger import (
    DIAL_OUTCOMES,
    NUMBER_PURPOSE,
    PIN_PURPOSE,
    Applicant,
    Ledger,
    LedgerError,
    consent_sha256,
    derive_key,
    forget_everywhere,
    number_hmac,
    pin_hmac,
)

ROOT = "a synthetic signing key for the tests only"
PIN_KEY = derive_key(ROOT, PIN_PURPOSE)
NUMBER_KEY = derive_key(ROOT, NUMBER_PURPOSE)
NUMBER = "+1312" + "555" + "0142"  # fictional, 555-01xx
NUMBER_HASH = number_hmac(NUMBER_KEY, NUMBER)
MASKED = "***-***-0142"
PIN = "7193"
# Thursday 5 November 2026, 10:00 Central: inside the window, before most of the interview slots.
NOW = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
CONSENT = {
    "version": "consent-2026-11-05",
    "accepted": True,
    "at": "2026-11-05T15:58:00+00:00",
    "source": "careers-form",
}
DIAL_KEYS = {
    "dial_id",
    "code",
    "attempt",
    "due_at",
    "status",
    "claimed_at",
    "placed_at",
    "call_sid",
    "twilio_status",
    "answered_at",
    "answered_by",
    "voicemail_left",
    "ended_at",
    "outcome",
}
CARE_AIDE_MET = {"q1": "yes", "q2": "both", "q3": "30", "q4": "yes", "q5": "yes"}


class Clock:
    """A clock a test can move."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _nonce(n: int = 0) -> str:
    return f"nonce-{n:02d}-abcdefghijklmnopqrstuvwxyz"


def _ledger(path: Path | None = None, clock: Clock | None = None, key: bytes | None = PIN_KEY) -> Ledger:
    return Ledger(state_path=path, now=clock or Clock(), pin_key=key)


def _apply(ledger: Ledger, n: int = 0, **overrides: Any) -> Applicant:
    fields: dict[str, Any] = {
        "first_name": "Ama",
        "role": "care-aide",
        "zone": "America/Chicago",
        "pin": PIN,
        "consent": CONSENT,
        "number_hmac": NUMBER_HASH,
        "number_masked": MASKED,
        "nonce": _nonce(n),
    }
    return ledger.add_application(**(fields | overrides))


def _answer_all(ledger: Ledger, code: str, answers: dict[str, str], call_id: str = "CA-screen") -> None:
    for question, value in answers.items():
        ledger.record_answer(code, question, value, f"I'd say {value}", call_id)


# The keys.


def test_the_keys_are_hmacs_one_per_purpose_and_the_code_is_inside_the_pin_mac() -> None:
    assert PIN_KEY != NUMBER_KEY and len(PIN_KEY) == 32
    assert derive_key(ROOT, PIN_PURPOSE) == PIN_KEY  # deterministic, so a restart matches the stored PINs
    first, second = pin_hmac(PIN_KEY, "ACME-1111", PIN), pin_hmac(PIN_KEY, "ACME-2222", PIN)
    assert first != second and re.fullmatch(r"[0-9a-f]{64}", first)
    assert re.fullmatch(r"[0-9a-f]{64}", NUMBER_HASH) and NUMBER not in NUMBER_HASH


def test_the_default_ledger_takes_its_pin_key_from_intake_signing_key() -> None:
    assert ledger_module._pin_key(Settings.from_env({"INTAKE_SIGNING_KEY": ROOT})) == PIN_KEY
    assert ledger_module._pin_key(Settings.from_env({})) is None
    assert ledger_module._pin_key(Settings.from_env({"INTAKE_SIGNING_KEY": ""})) is None


# The fixtures.


def test_the_fixtures_are_applicants_with_their_consent_and_no_number() -> None:
    ledger = _ledger()
    lerato = ledger.applicant("ACME-3108")
    assert lerato is not None and lerato.first_name == "Lerato" and lerato.role == "care-aide"
    assert lerato.consented and lerato.number_hmac is None and lerato.zone == "America/Chicago"
    assert ledger.applicant("3108") == lerato  # by its digits, as the transcriber gives them
    assert set(lerato.consent) == {"version", "text_sha256", "accepted", "at", "source"}
    text = ledger_module.load_applications()[2]["consent-2026-11-05"]
    assert lerato.consent["text_sha256"] == consent_sha256(text)
    dmitri = ledger.applicant("ACME-7941")
    assert dmitri is not None and not dmitri.consented
    assert ledger.applicant("ACME-9004") is None  # a candidate, not an applicant
    assert "4398" not in repr(lerato)  # the PIN stays inside the ledger
    copied = copy.deepcopy(lerato)  # a plain record a caller may copy or change without touching the fixture
    copied.consent["accepted"] = False  # type: ignore[index]
    assert ledger.applicant("ACME-3108").consented and asdict(lerato)["first_name"] == "Lerato"


def test_match_reads_candidates_as_before_and_applicants_too() -> None:
    ledger = _ledger()
    cand = ledger.match("9004", "9593")
    assert cand is not None and cand.code == "ACME-9004"
    found = ledger.match("3108", "4398")
    assert isinstance(found, Applicant) and found.code == "ACME-3108"
    assert ledger.match("3108", "4399") is None and ledger.match("9999", "4398") is None
    assert ledger.match_applicant_pin("ACME-7941", "0899") is not None  # the leading zero kept
    assert (
        ledger.match_applicant_pin("ACME-3108", "439") is None
        and ledger.match_applicant_pin("ACME-3108", "") is None
    )
    assert ledger.mask_pin("ACME-3108", "it's 4 3 9 8") == "it's ****"


# Intake applications.


def test_an_application_keeps_hmacs_the_masked_number_the_nonce_and_never_the_pin(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    app = _apply(ledger)
    assert re.fullmatch(r"ACME-\d{4}", app.code) and app.number_hmac == NUMBER_HASH
    assert ledger.candidate(app.code) is None and app.code not in ledger_module.load_applications()[0]
    raw = json.loads(path.read_text())
    record = raw["applications"][app.code]
    assert set(record) == {
        "code",
        "first_name",
        "role",
        "zone",
        "pin_hmac",
        "number_hmac",
        "number_masked",
        "consent",
        "received_at",
        "nonce",
        "not_dialled",
    }
    assert record["pin_hmac"] == pin_hmac(PIN_KEY, app.code, PIN) and record["number_masked"] == MASKED
    assert record["nonce"] == _nonce(0) and record["not_dialled"] is None
    assert record["received_at"] == "2026-11-05T16:00:00+00:00"
    assert record["consent"]["text_sha256"] and record["consent"]["accepted"] is True
    assert PIN not in json.dumps({k: v for k, v in record.items() if k != "pin_hmac"})
    assert path.stat().st_mode & 0o777 == 0o600  # first names and answers: the operator's eyes only
    assert ledger.match_applicant_pin(app.code, PIN) == app and ledger.match(app.code, PIN) == app
    assert ledger.match_applicant_pin(app.code, "7194") is None
    # A ledger under another key cannot match the stored PIN: a rotation re-keys or re-asks (card 08, decision 6).
    assert (
        _ledger(path, key=derive_key("another key", PIN_PURPOSE)).match_applicant_pin(app.code, PIN) is None
    )
    assert _ledger(path, key=None).match_applicant_pin(app.code, PIN) is None


def test_an_application_off_the_list_or_without_consent_keeps_its_reason() -> None:
    ledger = _ledger()
    off = _apply(ledger, 1, not_dialled="not_allowed")
    none = _apply(ledger, 2, consent=CONSENT | {"accepted": False}, not_dialled="no_consent")
    assert ledger.state(off.code)["dials_due"] == 0 and not none.consented
    for app in (off, none):
        with pytest.raises(LedgerError) as refusal:
            ledger.schedule_dial(app.code, 1, NOW)
        assert refusal.value.kind == "not_dialable"


@pytest.mark.parametrize(
    ("overrides", "kind"),
    [
        ({"pin": "123"}, "bad_pin"),
        ({"pin": "12345"}, "bad_pin"),
        ({"role": "astronaut"}, "unknown_role"),
        ({"first_name": "Ama 5550142"}, "bad_name"),
        ({"first_name": " "}, "bad_name"),
        ({"not_dialled": "busy"}, "bad_reason"),
        ({"consent": CONSENT | {"version": "consent-1999"}}, "unknown_consent"),
        ({"number_hmac": "not a hash"}, "bad_number_hmac"),
        ({"number_masked": NUMBER}, "unmasked_number"),
        ({"nonce": "short"}, "bad_nonce"),
        ({"nonce": "has spaces in it, twenty two"}, "bad_nonce"),
        ({"zone": "Mars/Olympus_Mons"}, "bad_zone"),
    ],
)
def test_add_application_refuses_what_the_ledger_must_never_hold(
    overrides: dict[str, Any], kind: str
) -> None:
    with pytest.raises(LedgerError) as refusal:
        _apply(_ledger(), **overrides)
    assert refusal.value.kind == kind and NUMBER not in str(refusal.value)


def test_no_application_is_stored_without_the_pin_key() -> None:
    with pytest.raises(LedgerError) as refusal:
        _apply(_ledger(key=None))
    assert refusal.value.kind == "no_pin_key"


def test_codes_are_fresh_and_never_reused(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "state.json")
    codes = {_apply(ledger, n).code for n in range(25)}
    assert len(codes) == 25
    fixtures = set(ledger_module.load_applications()[0])
    candidates = {"ACME-9004", "ACME-2490", "ACME-3233"}
    assert not codes & fixtures and not codes & candidates


def test_a_nonce_is_seen_for_ten_minutes_and_after_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = Clock()
    _apply(_ledger(path, clock), 7)
    clock.at = NOW + timedelta(minutes=9)
    restarted = _ledger(path, clock)
    window = clock.at - timedelta(minutes=10)
    assert restarted.nonce_seen(_nonce(7), window)
    assert not restarted.nonce_seen(_nonce(8), window)
    clock.at = NOW + timedelta(minutes=11)
    assert not restarted.nonce_seen(_nonce(7), clock.at - timedelta(minutes=10))


# Answers and the screen.


def test_record_answer_returns_what_it_replaced_and_restore_answer_undoes_it() -> None:
    ledger = _ledger()
    assert ledger.record_answer("ACME-3108", "q1", "no", "No, I don't drive.", "CA1") is None
    previous = ledger.record_answer("ACME-3108", "q1", "yes", "Actually yes.", "CA1")
    assert previous is not None and previous["value"] == "no" and previous["call_id"] == "CA1"
    assert set(previous) == {"value", "heard", "at", "call_id"}
    ledger.restore_answer("ACME-3108", "q1", previous)
    assert ledger.answers("ACME-3108")["q1"]["value"] == "no"
    ledger.restore_answer("ACME-3108", "q1", None)
    assert ledger.answers("ACME-3108") == {}
    ledger.restore_answer("ACME-3108", "q2", None)  # nothing to undo is no error


@pytest.mark.parametrize(
    ("question", "value", "kind"),
    [
        ("q9", "yes", "unknown_question"),
        ("q1", "maybe", "bad_value"),
        ("q2", "evening", "bad_value"),  # an option of another role's question
        ("q3", "4398", "bad_value"),  # four digits: a PIN is never stored as an answer
        ("q3", "-1", "bad_value"),
    ],
)
def test_record_answer_refuses_a_value_the_question_never_takes(question: str, value: str, kind: str) -> None:
    with pytest.raises(LedgerError) as refusal:
        _ledger().record_answer("ACME-3108", question, value, None, "CA1")
    assert refusal.value.kind == kind


def test_the_heard_words_lose_any_pin_and_any_digit_run_and_are_capped() -> None:
    ledger = _ledger()
    ledger.record_answer("ACME-3108", "q3", "30", "thirty hours, my PIN 4 3 9 8, call 312 555 0142", "CA1")
    heard = ledger.answers("ACME-3108")["q3"]["heard"]
    assert "4 3 9 8" not in heard and "0142" not in heard and "thirty hours" in heard
    ledger.record_answer("ACME-3108", "q4", "yes", "y" * 2000, "CA1")
    assert len(ledger.answers("ACME-3108")["q4"]["heard"]) == ledger_module.MAX_HEARD


def test_a_met_screen_needs_every_question_answered_with_a_posted_value() -> None:
    ledger = _ledger()
    _answer_all(ledger, "ACME-3108", {"q1": "yes", "q2": "both", "q3": "30", "q4": "yes"})
    with pytest.raises(LedgerError) as incomplete:
        ledger.set_screen("ACME-3108", "met", "CA1", None)
    assert incomplete.value.kind == "screen_incomplete"
    ledger.record_answer("ACME-3108", "q5", "declined", "rather not say", "CA1")
    with pytest.raises(LedgerError):
        ledger.set_screen("ACME-3108", "met", "CA1", None)
    with pytest.raises(LedgerError):
        ledger.set_screen("ACME-3108", "passed", "CA1", None)
    promised = datetime(2026, 11, 6, 22, 5, tzinfo=UTC)
    ledger.set_screen("ACME-3108", "not_met", "CA1", promised)
    assert ledger.screen("ACME-3108") == {
        "result": "not_met",
        "at": "2026-11-05T16:00:00+00:00",
        "call_id": "CA1",
        "promised_by": "2026-11-06T22:05:00+00:00",
    }
    with pytest.raises(LedgerError) as fixed:
        ledger.record_answer("ACME-3108", "q5", "yes", "yes", "CA1")
    assert fixed.value.kind == "screen_complete"  # from the last answer on, the answers are fixed
    ledger.clear_screen("ACME-3108")
    assert ledger.screen("ACME-3108") is None
    ledger.record_answer("ACME-3108", "q5", "yes", "yes", "CA1")
    ledger.set_screen("ACME-3108", "met", "CA1", None)
    assert ledger.screen("ACME-3108")["result"] == "met"


# state() and book() for an applicant.


def test_state_reads_an_applicant_and_a_candidate_s_state_is_unchanged() -> None:
    ledger = _ledger()
    assert ledger.state("ACME-9004") == {"booked_slot": None, "moves_used": 0, "callback_requested": False}
    assert ledger.state("ACME-3108") == {
        "booked_slot": None,
        "answers_recorded": 0,
        "questions_left": 5,
        "screen": None,
        "opted_out": False,
        "dials_due": 0,
        "callback_requested": False,
    }
    ledger.record_answer("ACME-3108", "q1", "yes", "yes", "CA1")
    ledger.record_answer("ACME-3108", "q2", "declined", "skip", "CA1")  # a skip counts as asked
    ledger.schedule_dial("ACME-3108", 2, NOW + timedelta(hours=2))
    ledger.request_callback("ACME-3108", "after five", "the questions", "CA1")
    state = ledger.state("ACME-3108")
    assert (state["answers_recorded"], state["questions_left"], state["dials_due"]) == (2, 3, 1)
    assert state["callback_requested"] is True
    with pytest.raises(KeyError):
        ledger.state("ACME-0001")


def test_book_refuses_an_applicant_until_the_screen_is_met_and_then_books_the_recruiter_s_slot() -> None:
    ledger = _ledger()
    with pytest.raises(LedgerError) as unasked:
        ledger.book("ACME-3108", "S1105-1300", "CA1")
    assert unasked.value.kind == "screen_not_met" and "come first" in str(unasked.value)
    _answer_all(ledger, "ACME-3108", CARE_AIDE_MET | {"q1": "no"})
    ledger.set_screen("ACME-3108", "not_met", "CA1", "2026-11-06T22:05:00+00:00")
    with pytest.raises(LedgerError) as unmet:
        ledger.book("ACME-3108", "S1105-1300", "CA1")
    assert unmet.value.kind == "screen_not_met" and "recruiter calls" in str(unmet.value)
    for word in ("met", "qualif", "eligib"):  # the model reads this sentence; it carries no verdict
        assert word not in str(unmet.value).lower().replace("meet", "")

    ledger.clear_screen("ACME-3108")
    ledger.record_answer("ACME-3108", "q1", "yes", "yes", "CA1")
    ledger.set_screen("ACME-3108", "met", "CA1", None)
    assert [s.id for s in ledger.open_slots(recruiter="Recruiter A", limit=3)] == [
        "S1105-1300",
        "S1106-0900",
        "S1106-1300",
    ]
    for wrong in ("S1105-1630", "S1105-1400"):  # Recruiter B's interview slot; a first-round slot
        with pytest.raises(LedgerError) as refusal:
            ledger.book("ACME-3108", wrong, "CA1")
        assert refusal.value.kind == "unknown_slot"
    slot = ledger.book("ACME-3108", "Thursday 5 November at 1:00 PM Central", "CA1")
    assert slot.id == "S1105-1300" and slot.interviewer == "Recruiter A"
    assert (
        ledger.booked_slot("ACME-3108") == slot and ledger.state("ACME-3108")["booked_slot"] == "S1105-1300"
    )
    assert "S1105-1300" not in [s.id for s in ledger.open_slots(recruiter="Recruiter A")]
    with pytest.raises(LedgerError) as twice:
        ledger.book("ACME-3108", "S1106-0900", "CA1")
    assert twice.value.kind == "already_booked"
    assert ledger.unbook("ACME-3108", "S1105-1300") and ledger.is_open("S1105-1300")


def test_a_candidate_never_books_an_interview_slot_and_the_first_round_list_is_unchanged() -> None:
    ledger = _ledger()
    with pytest.raises(LedgerError) as refusal:
        ledger.book("ACME-9004", "S1105-1300")
    assert refusal.value.kind == "unknown_slot"
    assert all(
        s.id in ledger_module._load_slots(ledger_module.SLOTS_PATH) for s in ledger.open_slots(limit=40)
    )
    assert ledger.find_slot("S1105-1300") is None and ledger.interview_slot("S1105-1300") is not None


# Opt-outs.


def test_an_opt_out_cancels_every_due_dial_for_the_code_and_the_number() -> None:
    ledger = _ledger()
    first, second = _apply(ledger, 1), _apply(ledger, 2, first_name="Kofi")
    ledger.schedule_dial(first.code, 1, NOW)
    ledger.schedule_dial(second.code, 1, NOW + timedelta(minutes=5))
    ledger.schedule_dial("ACME-3108", 1, NOW)
    assert ledger.opt_out(first.code, "said stop", call_id="CA1") == 2  # the same number applied twice
    assert ledger.opted_out(first.code) and ledger.opted_out(number_hmac=NUMBER_HASH)
    assert ledger.opted_out(second.code) and not ledger.opted_out("ACME-3108") and not ledger.opted_out()
    cancelled = [d for d in ledger.dials() if d["status"] == "cancelled"]
    assert {d["code"] for d in cancelled} == {first.code, second.code}
    assert {d["outcome"] for d in cancelled} == {"opted_out"}
    record = ledger._overlay["opt_outs"][0]
    assert record == {
        "code": first.code,
        "number_hmac": NUMBER_HASH,
        "at": "2026-11-05T16:00:00+00:00",
        "call_id": "CA1",
        "how": "said stop",
    }
    later = _apply(ledger, 3)
    with pytest.raises(LedgerError):
        ledger.schedule_dial(later.code, 1, NOW)  # a later application from the number is never dialled
    assert ledger.opt_out("ACME-3108", "wrong person") == 1
    assert ledger.dials("ACME-3108")[0]["outcome"] == "wrong_person"


def test_an_opt_out_is_never_refused_for_an_unknown_code_and_needs_a_known_how() -> None:
    ledger = _ledger()
    assert ledger.opt_out("ACME-0001", "operator", number_hmac=NUMBER_HASH) == 0
    assert ledger.opted_out("ACME-0001") and ledger.opted_out(number_hmac=NUMBER_HASH)
    with pytest.raises(LedgerError):
        ledger.opt_out("ACME-3108", "because")


# Dials.


def test_a_dial_record_has_the_shape_of_section_8_and_one_attempt_is_one_record() -> None:
    ledger = _ledger()
    dial = ledger.schedule_dial("ACME-3108", 1, NOW + timedelta(minutes=2))
    assert set(dial) == DIAL_KEYS and re.fullmatch(r"D-[0-9a-f]{12}", dial["dial_id"])
    assert dial["due_at"] == "2026-11-05T16:02:00+00:00" and dial["status"] == "due"
    assert dial["voicemail_left"] is False and dial["call_sid"] is None
    assert ledger.schedule_dial("ACME-3108", 1, NOW + timedelta(hours=1)) == dial
    assert ledger.dial(dial["dial_id"]) == dial and ledger.dials("3108") == [dial]
    with pytest.raises(LedgerError):
        ledger.schedule_dial("ACME-3108", 2, datetime(2026, 11, 5, 18, 0))  # no zone
    with pytest.raises(LedgerError):
        ledger.schedule_dial("ACME-3108", 0, NOW)
    with pytest.raises(LedgerError) as refusal:
        ledger.schedule_dial("ACME-7941", 1, NOW)  # Dmitri did not consent
    assert refusal.value.kind == "not_dialable"


def _always(dial: dict[str, Any], app: Applicant) -> bool:
    return True


def test_the_claim_takes_the_earliest_due_dial_one_at_a_time() -> None:
    ledger = _ledger()
    later = ledger.schedule_dial("ACME-3474", 1, NOW - timedelta(minutes=1))
    first = ledger.schedule_dial("ACME-3108", 1, NOW - timedelta(minutes=5))
    ledger.schedule_dial("ACME-2609", 1, NOW + timedelta(minutes=5))  # not due yet
    claimed = ledger.claim_due_dial(NOW, 20, _always)
    assert claimed is not None and claimed["dial_id"] == first["dial_id"]
    assert claimed["status"] == "claimed" and claimed["claimed_at"] == "2026-11-05T16:00:00+00:00"
    assert ledger.claim_due_dial(NOW, 20, _always) is None  # one call at a time
    for status in ("placed", "in-progress"):
        ledger.update_dial(first["dial_id"], status=status)
        assert ledger.claim_due_dial(NOW, 20, _always) is None
    ledger.update_dial(first["dial_id"], status="done", outcome="screened")
    assert ledger.claim_due_dial(NOW, 20, _always)["dial_id"] == later["dial_id"]


def test_the_claim_respects_the_day_s_cap_counted_when_a_dial_is_placed() -> None:
    ledger = _ledger()
    for code in ("ACME-3108", "ACME-3474", "ACME-2609"):
        ledger.schedule_dial(code, 1, NOW - timedelta(minutes=1))
    for _ in range(2):
        claimed = ledger.claim_due_dial(NOW, 2, _always)
        assert claimed is not None
        ledger.update_dial(claimed["dial_id"], status="done", placed_at=NOW, outcome="no_answer")
    assert ledger.dials_placed_today() == 2
    assert ledger.claim_due_dial(NOW, 2, _always) is None
    # The next Central-time day starts at 06:00 UTC in November.
    assert ledger.claim_due_dial(datetime(2026, 11, 6, 6, 1, tzinfo=UTC), 2, _always) is not None


def test_the_claim_skips_what_ready_refuses_and_what_may_never_be_dialled(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    app = _apply(ledger)
    ledger.schedule_dial(app.code, 1, NOW - timedelta(minutes=1))
    assert ledger.claim_due_dial(NOW, 20, lambda d, a: False) is None
    seen: list[tuple[str, str]] = []
    assert ledger.claim_due_dial(NOW, 20, lambda d, a: bool(seen.append((d["code"], a.code)))) is None
    assert seen == [(app.code, app.code)]
    # A not_dialled reason written after the dial (an allow-list check that failed at dial time) holds too.
    raw = json.loads(path.read_text())
    raw["applications"][app.code]["not_dialled"] = "not_allowed"
    path.write_text(json.dumps(raw))
    assert _ledger(path).claim_due_dial(NOW, 20, _always) is None
    raw["applications"][app.code]["not_dialled"] = None
    raw["opt_outs"] = [
        {"code": "ACME-0001", "number_hmac": NUMBER_HASH, "at": "x", "call_id": None, "how": "operator"}
    ]
    path.write_text(json.dumps(raw))
    assert _ledger(path).claim_due_dial(NOW, 20, _always) is None
    raw["opt_outs"] = []
    raw["applications"][app.code]["consent"]["accepted"] = False
    path.write_text(json.dumps(raw))
    assert _ledger(path).claim_due_dial(NOW, 20, _always) is None
    raw["applications"][app.code]["consent"]["accepted"] = True
    path.write_text(json.dumps(raw))
    assert _ledger(path).claim_due_dial(NOW, 20, _always) is not None


def test_set_not_dialled_marks_an_intake_application_and_keeps_every_later_dial_from_it(
    tmp_path: Path,
) -> None:
    # The dialler's allow-list check at dial time and /voice's call this (DR-025 sections 7 and 12).
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    app = _apply(ledger)
    ledger.schedule_dial(app.code, 1, NOW - timedelta(minutes=1))
    ledger.set_not_dialled(app.code, "not_allowed")
    assert json.loads(path.read_text())["applications"][app.code]["not_dialled"] == "not_allowed"
    assert ledger.claim_due_dial(NOW, 20, _always) is None
    with pytest.raises(LedgerError) as refused:
        ledger.schedule_dial(app.code, 2, NOW + timedelta(hours=2))
    assert refused.value.kind == "not_dialable"
    with pytest.raises(LedgerError) as bad:
        ledger.set_not_dialled(app.code, "busy")
    assert bad.value.kind == "bad_reason"
    # A fixture's row lives in data/, which is never rewritten, and an unknown code changes nothing.
    before = path.read_text()
    ledger.set_not_dialled("ACME-3108", "not_allowed")
    ledger.set_not_dialled("ACME-0001", "not_allowed")
    assert path.read_text() == before and ledger.applicant("ACME-3108") is not None


def test_one_dial_is_claimed_once_across_two_ledgers_on_one_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    first, second = _ledger(path), _ledger(path)
    first.schedule_dial("ACME-3108", 1, NOW - timedelta(minutes=1))
    claims: list[dict[str, Any] | None] = []
    start = threading.Barrier(8)

    def claim(ledger: Ledger) -> None:
        start.wait()
        claims.append(ledger.claim_due_dial(NOW, 20, _always))

    threads = [threading.Thread(target=claim, args=(ledger,)) for ledger in (first, second) * 4]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    won = [c for c in claims if c is not None]
    assert len(won) == 1 and second.dials()[0]["status"] == "claimed"


_CLAIM_IN_A_PROCESS = """
import sys, time
from datetime import UTC, datetime
from candidate_line.tools.ledger import Ledger
start = float(sys.argv[2])
while time.time() < start:
    time.sleep(0.005)
got = Ledger(state_path=sys.argv[1]).claim_due_dial(datetime(2026, 11, 5, 16, 0, tzinfo=UTC), 20, lambda d, a: True)
print(got["dial_id"] if got else "none")
"""


def test_one_dial_is_claimed_once_across_processes_on_one_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _ledger(path).schedule_dial("ACME-3108", 1, NOW - timedelta(minutes=1))
    start = str(time.time() + 1.5)
    root = Path(__file__).resolve().parents[1]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CLAIM_IN_A_PROCESS, str(path), start],
            cwd=root,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    outputs = [p.communicate(timeout=60)[0].strip() for p in procs]
    assert outputs.count("none") == 3 and len([o for o in outputs if o.startswith("D-")]) == 1


def test_bind_call_binds_a_live_dial_once_and_never_takes_one_over() -> None:
    ledger = _ledger()
    dial = ledger.schedule_dial("ACME-3108", 1, NOW - timedelta(minutes=1))
    assert ledger.bind_call(dial["dial_id"], "CA-first") is None  # due, not claimed: not live
    ledger.claim_due_dial(NOW, 20, _always)
    bound = ledger.bind_call(dial["dial_id"], "CA-first")
    assert bound is not None and bound["call_sid"] == "CA-first" and bound["status"] == "claimed"
    assert ledger.bind_call(dial["dial_id"], "CA-first") == bound  # Twilio fetching the Url twice
    assert ledger.bind_call(dial["dial_id"], "CA-replayed") is None
    assert ledger.bind_call("D-000000000000", "CA-x") is None and ledger.bind_call("CA-first", "CA-y") is None
    assert ledger.dial("CA-first")["dial_id"] == dial["dial_id"]
    ledger.update_dial("CA-first", status="done", outcome="screened")
    assert ledger.bind_call(dial["dial_id"], "CA-first") is None  # a finished dial is never bound again


def test_update_dial_finds_by_either_key_and_takes_only_the_record_s_fields() -> None:
    ledger = _ledger()
    dial = ledger.schedule_dial("ACME-3108", 1, NOW)
    other = ledger.schedule_dial("ACME-3474", 1, NOW)
    updated = ledger.update_dial(dial["dial_id"], status="placed", placed_at=NOW, call_sid="CA-1")
    assert updated is not None and updated["placed_at"] == "2026-11-05T16:00:00+00:00"
    answered = ledger.update_dial("CA-1", twilio_status="in-progress", answered_at=NOW, answered_by="human")
    assert answered is not None and answered["answered_by"] == "human" and set(answered) == DIAL_KEYS
    assert ledger.update_dial("CA-none", status="done") is None
    with pytest.raises(LedgerError) as no_number:
        ledger.update_dial(dial["dial_id"], number=NUMBER)
    assert no_number.value.kind == "bad_field" and NUMBER not in str(no_number.value)
    for bad in ({"status": "ringing"}, {"outcome": "great"}):
        with pytest.raises(LedgerError):
            ledger.update_dial(dial["dial_id"], **bad)
    with pytest.raises(LedgerError) as taken:
        ledger.update_dial(other["dial_id"], call_sid="CA-1")
    assert taken.value.kind == "call_sid_bound"
    assert "not_allowed" in DIAL_OUTCOMES and ledger.update_dial(
        other["dial_id"], status="cancelled", outcome="not_allowed"
    )


# Deletion and retention.


def test_forget_removes_the_application_and_keeps_only_the_consent_evidence_and_an_opt_out(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    app = _apply(ledger)
    keep = _apply(ledger, 1, first_name="Kofi", number_hmac="0" * 64)
    ledger.schedule_dial(app.code, 1, NOW)
    ledger.schedule_dial(keep.code, 1, NOW)
    ledger.record_answer(app.code, "q1", "yes", "yes I drive", "CA1")
    ledger.request_callback(app.code, "after five", "a question", "CA1")
    ledger.forget(app.code)
    assert ledger.applicant(app.code) is None and ledger.match_applicant_pin(app.code, PIN) is None
    raw = json.loads(path.read_text())
    assert raw["applications"][app.code] == {
        "code": app.code,
        "consent": {"version": "consent-2026-11-05", "at": CONSENT["at"]},
        "number_hmac": NUMBER_HASH,
        "removed": {"at": "2026-11-05T16:00:00+00:00", "why": "deletion"},
    }
    assert app.code not in raw["answers"] and [d["code"] for d in raw["dials"]] == [keep.code]
    assert raw["callbacks"] == [] and raw["opt_outs"][-1]["how"] == "deletion"
    assert "Ama" not in json.dumps(raw["applications"][app.code])
    assert ledger.opted_out(number_hmac=NUMBER_HASH)  # the number is never called again
    with pytest.raises(LedgerError):
        ledger.forget(app.code)
    # A fixture's row stays in data/; its records here go, and it is not dialled again.
    ledger.record_answer("ACME-3108", "q1", "yes", "yes", "CA2")
    ledger.forget("ACME-3108")
    assert ledger.answers("ACME-3108") == {} and ledger.opted_out("ACME-3108")
    assert ledger.applicant("ACME-3108") is not None


def test_purge_answers_removes_what_was_received_before_and_adds_no_opt_out(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = Clock(datetime(2022, 11, 1, 16, 0, tzinfo=UTC))
    ledger = _ledger(path, clock)
    old = _apply(ledger, 1)
    ledger.record_answer(old.code, "q1", "yes", "yes", "CA-old")
    clock.at = NOW
    new = _apply(ledger, 2, number_hmac="1" * 64)
    ledger.record_answer(new.code, "q1", "no", "no", "CA-new")
    cutoff = NOW - timedelta(days=1460)
    assert ledger.purge_answers(cutoff) == 1
    assert ledger.applicant(old.code) is None and ledger.answers(old.code) == {}
    assert ledger.applicant(new.code) is not None and ledger.answers(new.code)["q1"]["value"] == "no"
    assert ledger._overlay["opt_outs"] == [] and not ledger.opted_out(number_hmac=NUMBER_HASH)
    assert json.loads(path.read_text())["applications"][old.code]["removed"]["why"] == "retention"
    assert ledger.purge_answers(cutoff) == 0  # the sweep runs on every tick; a second pass removes nothing


def test_forget_everywhere_deletes_the_number_first_then_the_records() -> None:
    ledger = _ledger()
    app = _apply(ledger)
    order: list[str] = []

    def delete(code: str) -> bool:
        order.append("contact" if ledger.applicant(code) is not None else "too late")
        return True

    assert forget_everywhere(ledger, app.code, delete) is True
    assert order == ["contact"] and ledger.applicant(app.code) is None
    with pytest.raises(LedgerError):
        forget_everywhere(ledger, "ACME-0001", delete)


def test_make_forget_runs_against_the_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "state.json"
    ledger = _ledger(path)
    ledger.record_answer("ACME-3108", "q1", "yes", "yes", "CA1")
    monkeypatch.setenv("STATE_PATH", str(path))
    monkeypatch.setenv("CONTACTS_PATH", str(tmp_path / "contacts.json"))
    monkeypatch.setattr(ledger_module, "_DEFAULTS", {})
    assert ledger_module.main(["forget", "ACME-3108"]) == 0
    assert "forgot ACME-3108" in capsys.readouterr().out
    assert json.loads(path.read_text())["answers"] == {}
    assert ledger_module.main(["forget", "ACME-0001"]) == 1
    monkeypatch.setenv("STATE_PATH", ":memory:")
    assert ledger_module.main(["forget", "ACME-3108"]) == 2


def test_the_contacts_store_is_called_through_its_own_delete(tmp_path: Path) -> None:
    store = Contacts(tmp_path / "c.json")
    store.put("ACME-3108", NUMBER, NOW)
    settings = Settings.from_env({"CONTACTS_PATH": str(tmp_path / "c.json")})
    deleter = ledger_module._contacts_deleter(settings)
    assert deleter("ACME-3108") and store.number("ACME-3108") is None
    assert not deleter("ACME-3108")  # nothing left to delete
    with pytest.raises(LedgerError):
        ledger_module._contacts_deleter(replace(settings, contacts_path=""))


# The file.


def test_unknown_top_level_keys_are_kept_and_written_back(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    newer = {
        "version": 1,
        "bookings": {},
        "moves": [],
        "callbacks": [],
        "calls": {"2026-11-05": 2},
        "interviews_v2": {"ACME-3108": {"room": "B"}},
        "audit": [1, 2, 3],
    }
    path.write_text(json.dumps(newer))
    ledger = _ledger(path)
    ledger.record_answer("ACME-3108", "q1", "yes", "yes", "CA1")
    written = json.loads(path.read_text())
    assert written["interviews_v2"] == {"ACME-3108": {"room": "B"}} and written["audit"] == [1, 2, 3]
    assert written["version"] == 1 and written["calls"] == {"2026-11-05": 2}
    assert {"applications", "answers", "dials", "opt_outs"} <= set(written)
    # An older image's file, with none of the four new keys, reads as empty ones.
    path.write_text(json.dumps({"version": 1, "bookings": {}, "moves": [], "callbacks": [], "calls": {}}))
    assert _ledger(path).dials() == [] and _ledger(path).answers("ACME-3108") == {}


def test_malformed_records_are_dropped_and_the_file_still_opens(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "applications": {"ACME-1111": {"code": "ACME-2222"}, "ACME-3333": "x"},
                "answers": {"ACME-3108": {"by_question": {"q1": "yes"}, "screen": "met"}},
                "dials": [{"dial_id": "X"}, "y", {"dial_id": "D-0123456789ab", "status": "due"}],
                "opt_outs": ["z", {"code": "ACME-3108"}],
            }
        )
    )
    ledger = _ledger(path)
    assert ledger.applicant("ACME-1111") is None and ledger.applicant("ACME-3333") is None
    assert ledger.answers("ACME-3108") == {} and ledger.screen("ACME-3108") is None
    assert [d["dial_id"] for d in ledger.dials()] == ["D-0123456789ab"]
    assert ledger.opted_out("ACME-3108")


def test_a_full_scripted_screen_leaves_no_raw_number_and_no_pin_digit_in_the_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    clock = Clock()
    ledger = _ledger(path, clock)
    app = _apply(ledger)
    dial = ledger.schedule_dial(app.code, 1, NOW + timedelta(minutes=2))
    clock.at = NOW + timedelta(minutes=2)
    claimed = ledger.claim_due_dial(clock.at, 20, _always)
    assert claimed is not None
    ledger.bind_call(dial["dial_id"], "CA-screen")
    ledger.update_dial(
        "CA-screen", status="in-progress", placed_at=clock.at, answered_at=clock.at, answered_by="human"
    )
    assert ledger.match_applicant_pin(app.code, PIN) is not None
    heard = {
        "q1": f"yes, and my PIN is {PIN}",
        "q2": "both, call me back on 312 555 0142",
        "q3": f"thirty, {' '.join(PIN)}",
        "q4": "yes",
        "q5": f"yes {NUMBER}",
    }
    for question, value in CARE_AIDE_MET.items():
        ledger.record_answer(app.code, question, value, heard[question], "CA-screen")
    ledger.set_screen(app.code, "met", "CA-screen", None)
    ledger.book(app.code, "S1105-1300", "CA-screen")
    ledger.update_dial("CA-screen", status="done", ended_at=clock.at, outcome="screened")
    ledger.opt_out(app.code, "said on the call", call_id="CA-screen")
    text = path.read_text()
    digits_of_number = re.sub(r"[^0-9]", "", NUMBER)
    assert digits_of_number not in re.sub(r"[^0-9]", "", text.replace(NUMBER_HASH, ""))
    assert "5550142" not in text and "555 0142" not in text
    # The hashes and the dial id are hex, where four digits can stand by chance; everything else is read for the PIN.
    readable = re.sub(r"[0-9a-f]{12,64}", "", text)
    assert PIN not in readable and " ".join(PIN) not in readable
    assert ledger.state(app.code)["booked_slot"] == "S1105-1300"
