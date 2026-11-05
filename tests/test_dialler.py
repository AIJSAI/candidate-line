"""The dialler with a fake Twilio, a fake ledger and a pinned clock (spec 9.2 to 9.5, DR-025 sections 9 and 12;
fixes 8, 13 and 16). The ledger is `tests/outbound_fakes.FakeLedger` until lane C's lands (DR-025 section 7)."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from candidate_line import hooks
from candidate_line.outbound import number_hmac, number_key
from candidate_line.outbound.contacts import Contacts
from candidate_line.outbound.dialler import Dialler, session_outcome
from candidate_line.settings import Settings
from candidate_line.telephony.twilio_rest import TwilioError
from tests.outbound_fakes import FakeLedger, fictional

KEY = "test-signing-key"
THURSDAY_10_CENTRAL = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kwargs: float) -> None:
        self.at += timedelta(**kwargs)


class FakeTwilio:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.updates: list[tuple[str, str]] = []
        self.status = "in-progress"
        self.fail = fail

    def place_call(self, to: str, from_: str, **kwargs) -> str:
        if self.fail:
            raise TwilioError(500, None, f"HTTP 500: could not reach {to}")
        self.calls.append({"To": to, "From": from_, **kwargs})
        return f"CA{len(self.calls):032d}"

    def update_call(self, call_sid: str, twiml: str) -> None:
        self.updates.append((call_sid, twiml))

    def call_status(self, call_sid: str) -> str:
        return self.status


class Preflight:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.runs = 0

    def __call__(self) -> None:
        self.runs += 1
        if self.error is not None:
            raise self.error


class AccessDeniedException(Exception):
    """Shaped as botocore's ClientError for Polly's AccessDenied."""

    def __init__(self) -> None:
        super().__init__("not authorized")
        self.response = {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}}


def settings(**env: str) -> Settings:
    base = {
        "OUTBOUND_ENABLED": "1",
        "INTAKE_SIGNING_KEY": KEY,
        "OUTBOUND_ALLOWED_NUMBERS": f"{fictional(142)},{fictional(143)}",
        "TWILIO_LINE_NUMBER": fictional(100),
        "TWILIO_ACCOUNT_SID": "ACtest",
        "TWILIO_AUTH_TOKEN": "test-token",
        "PUBLIC_BASE_URL": "https://line.example",
    }
    return Settings.from_env(base | env)


class World:
    def __init__(self, tmp_path: Path, ledger: FakeLedger | None = None, **env: str) -> None:
        self.clock = Clock(THURSDAY_10_CENTRAL)
        self.ledger = ledger or FakeLedger(now=self.clock)
        self.ledger.now = self.clock
        self.contacts = Contacts(tmp_path / "contacts.json")
        self.twilio = FakeTwilio()
        self.preflight = Preflight()
        self.no_dial = tmp_path / "no-dial"
        self.settings = settings(**env)
        self.dialler = Dialler(
            self.settings,
            lambda: self.ledger,
            self.contacts,
            self.twilio,  # type: ignore[arg-type]
            self.clock,
            self.preflight,
            no_dial=self.no_dial,
        )
        self.clock.advance(seconds=121)  # past the task's first 120 s

    def apply(self, number: str = "", consent: bool = True, zone: str = "America/Chicago", due_in_s: int = 0):
        number = number or fictional(142)
        applicant = self.ledger.add_application(
            first_name="Ada",
            role="care-aide",
            zone=zone,
            pin="1234",
            consent={"version": "consent-2026-11-05", "accepted": consent},
            number_hmac=number_hmac(number_key(KEY), number),
            number_masked="***-***-" + number[-4:],
            nonce="n" * 22,
            received_at=self.clock(),
        )
        self.contacts.put(applicant.code, number, self.clock())
        dial = self.ledger.schedule_dial(applicant.code, 1, self.clock() + timedelta(seconds=due_in_s))
        return applicant, dial


def test_a_due_dial_is_placed_once_with_exactly_the_parameters_of_section_12(tmp_path) -> None:
    w = World(tmp_path)
    _applicant, dial = w.apply()
    assert w.dialler.tick() == "placed"
    assert w.twilio.calls == [
        {
            "To": fictional(142),
            "From": fictional(100),
            "url": f"https://line.example/voice?dial={dial['dial_id']}",
            "status_callback": "https://line.example/voice/status",
            "amd_callback": "https://line.example/voice/amd",
            "timeout_s": 30,
            "time_limit_s": 540,  # MAX_OUTBOUND_CALL_SECONDS + 60
        }
    ]
    placed = w.ledger.dial(dial["dial_id"])
    assert placed["status"] == "placed" and placed["call_sid"] == "CA" + "1".zfill(32)
    assert placed["placed_at"] == "2026-11-05T16:02:01+00:00"
    assert w.preflight.runs == 1
    assert w.dialler.tick() == "a call is in flight"  # one at a time
    assert len(w.twilio.calls) == 1


def test_nothing_is_placed_while_outbound_is_off_but_the_sweep_still_runs(tmp_path) -> None:
    w = World(tmp_path, OUTBOUND_ENABLED="0", OUTBOUND_ALLOWED_NUMBERS="")
    w.apply()
    assert w.dialler.tick() == "dialling is off"
    assert w.twilio.calls == [] and w.preflight.runs == 0
    assert w.ledger.purged_before == [w.clock() - timedelta(days=1460)]


def test_nothing_is_placed_while_the_kill_switch_or_the_no_dial_file_exists(tmp_path) -> None:
    w = World(tmp_path)
    w.apply()
    hooks.KILL_SWITCH.touch()
    try:
        assert w.dialler.tick() == "the kill switch is set"
    finally:
        hooks.KILL_SWITCH.unlink()
    w.no_dial.touch()
    assert w.dialler.tick() == "the no-dial file is set"
    assert w.twilio.calls == []
    w.no_dial.unlink()
    assert w.dialler.tick() == "placed"


def test_nothing_is_placed_in_the_tasks_first_120_seconds(tmp_path) -> None:
    w = World(tmp_path)
    w.clock.at = w.dialler.started_at + timedelta(seconds=119)
    w.apply()
    assert w.dialler.tick() == "the task is under 120 s old"
    w.clock.advance(seconds=1)
    assert w.dialler.tick() == "placed"


def test_nothing_is_placed_once_the_days_cap_is_reached(tmp_path) -> None:
    w = World(tmp_path, MAX_OUTBOUND_PER_DAY="1")
    first, _ = w.apply()
    assert w.dialler.tick() == "placed"
    w.ledger.update_dial(w.ledger.dials(first.code)[0]["dial_id"], status="done", outcome="screened")
    w.apply(number=fictional(143))
    assert w.dialler.tick() == "the day's cap is reached"
    assert len(w.twilio.calls) == 1


def test_nothing_is_placed_outside_the_applicants_window(tmp_path) -> None:
    w = World(tmp_path)
    w.apply(zone="America/Los_Angeles")  # 08:02 there
    assert w.dialler.tick() == "nothing due"
    w.clock.advance(hours=1)
    assert w.dialler.tick() == "placed"


class LaxClaim(FakeLedger):
    """A claim that lets through what DR-025 section 7 says it never will, to prove the dialler checks again."""

    def claim_due_dial(self, now, max_per_day, ready):
        for d in self.dial_rows:
            if d["status"] == "due":
                d.update(status="claimed", claimed_at=now.isoformat())
                return dict(d)
        return None


def test_an_applicant_with_no_consent_is_never_dialled_even_past_a_lax_claim(tmp_path) -> None:
    w = World(tmp_path, ledger=LaxClaim())
    applicant, dial = w.apply(consent=False)
    assert w.dialler.tick() == "no consent or opted out"
    assert w.twilio.calls == []
    assert w.ledger.dial(dial["dial_id"])["status"] == "cancelled"
    assert w.contacts.number(applicant.code) is None


def test_an_opted_out_applicant_is_never_dialled_by_code_or_by_number(tmp_path) -> None:
    w = World(tmp_path, ledger=LaxClaim())
    applicant, dial = w.apply()
    w.ledger.opt_outs.append({"code": "ACME-0000", "number_hmac": applicant.number_hmac, "how": "said stop"})
    assert w.dialler.tick() == "no consent or opted out"
    assert w.twilio.calls == []
    assert w.ledger.dial(dial["dial_id"])["outcome"] == "opted_out"
    assert w.contacts.number(applicant.code) is None


def test_a_number_off_the_allow_list_is_never_dialled_even_when_every_other_gate_holds(
    tmp_path, caplog
) -> None:
    w = World(tmp_path, OUTBOUND_ALLOWED_NUMBERS=fictional(143))
    applicant, dial = w.apply(number=fictional(142))
    with caplog.at_level(logging.INFO, logger="candidate_line.dialler"):
        assert w.dialler.tick() == "not_allowed"
    assert w.twilio.calls == [] and w.preflight.runs == 0
    cancelled = w.ledger.dial(dial["dial_id"])
    assert (cancelled["status"], cancelled["outcome"]) == ("cancelled", "not_allowed")
    assert w.ledger.applications[applicant.code]["not_dialled"] == "not_allowed"
    assert w.contacts.number(applicant.code) is None
    lines = [r.getMessage() for r in caplog.records if "allow-list" in r.getMessage()]
    assert lines == [f"dial {dial['dial_id']} not placed: ***-***-0142 is not on the allow-list"]
    assert all(
        fictional(142) not in r.getMessage() and fictional(142)[-7:] not in r.getMessage()
        for r in caplog.records
    )
    # A number on the list is placed.
    w.apply(number=fictional(143))
    assert w.dialler.tick() == "placed"
    assert [c["To"] for c in w.twilio.calls] == [fictional(143)]


def test_a_number_the_store_cannot_vouch_for_is_never_dialled(tmp_path) -> None:
    w = World(tmp_path, ledger=LaxClaim(), OUTBOUND_ALLOWED_NUMBERS=fictional(142))
    applicant, _ = w.apply()
    w.contacts._write(
        {applicant.code: {"number": " " + fictional(142), "added_at": "x", "delete_after": "x"}}
    )
    assert w.dialler.tick() == "no number"  # the store itself refuses to hand out a number that is not E.164
    assert w.twilio.calls == []


def test_polly_access_denied_sets_no_dial_and_places_nothing(tmp_path) -> None:
    w = World(tmp_path)
    _, dial = w.apply()
    w.preflight.error = AccessDeniedException()
    assert w.dialler.tick() == "speech denied"
    assert w.no_dial.exists() and w.twilio.calls == []
    assert w.ledger.dial(dial["dial_id"])["status"] == "due"  # handed back, dialled once speech returns
    assert w.dialler.tick() == "the no-dial file is set"


def test_another_preflight_failure_waits_for_the_next_tick_without_setting_no_dial(tmp_path) -> None:
    w = World(tmp_path)
    w.apply()
    w.preflight.error = TimeoutError("polly slow")
    assert w.dialler.tick() == "preflight failed"
    assert not w.no_dial.exists() and w.twilio.calls == []
    w.preflight.error = None
    assert w.dialler.tick() == "placed"


def test_a_failed_rest_call_marks_the_dial_failed_and_schedules_the_next_attempt(tmp_path, caplog) -> None:
    w = World(tmp_path)
    applicant, dial = w.apply()
    w.twilio.fail = True
    with caplog.at_level(logging.WARNING):
        assert w.dialler.tick() == "failed"
    failed = w.ledger.dial(dial["dial_id"])
    assert (failed["status"], failed["outcome"]) == ("failed", "failed")
    [second] = [d for d in w.ledger.dials(applicant.code) if d["attempt"] == 2]
    assert second["due_at"] == "2026-11-05T18:02:01+00:00"  # two hours later, inside the window
    assert all(fictional(142)[-7:] not in r.getMessage() for r in caplog.records)


def test_the_sweep_deletes_a_number_on_the_first_tick_after_the_retention_with_dialling_on_or_off(
    tmp_path,
) -> None:
    for enabled in ("1", "0"):
        w = World(tmp_path / enabled, OUTBOUND_ENABLED=enabled)
        applicant, _ = w.apply(due_in_s=10**8)
        w.clock.advance(days=30, seconds=-2)
        w.dialler.tick()
        assert w.contacts.number(applicant.code) == fictional(142)
        w.clock.advance(seconds=2)
        w.dialler.tick()
        assert w.contacts.number(applicant.code) is None
        assert w.ledger.purged_before[-1] == w.clock() - timedelta(days=1460)


def test_one_half_of_the_sweep_failing_never_stops_the_other(tmp_path, caplog) -> None:
    class NoPurge(FakeLedger):
        def purge_answers(self, before):
            raise OSError("disk full")

    w = World(tmp_path, ledger=NoPurge())
    applicant, _ = w.apply(due_in_s=10**8)
    w.clock.advance(days=31)
    w.dialler.tick()
    assert w.contacts.number(applicant.code) is None
    assert "the answers retention sweep failed" in caplog.text


# The callbacks.


def placed(w: World):
    applicant, dial = w.apply()
    assert w.dialler.tick() == "placed"
    sid = w.ledger.dial(dial["dial_id"])["call_sid"]
    return applicant, dial["dial_id"], sid


@pytest.mark.parametrize(
    ("call_status", "outcome"), [("no-answer", "no_answer"), ("busy", "busy"), ("failed", "failed")]
)
def test_no_answer_busy_or_failed_schedules_the_next_attempt(
    tmp_path, call_status: str, outcome: str
) -> None:
    w = World(tmp_path)
    applicant, dial_id, sid = placed(w)
    w.clock.advance(seconds=40)
    w.dialler.on_status({"CallSid": sid, "CallStatus": call_status})
    ended = w.ledger.dial(dial_id)
    assert ended["outcome"] == outcome and ended["status"] in ("done", "failed") and ended["ended_at"]
    [second] = [d for d in w.ledger.dials(applicant.code) if d["attempt"] == 2]
    assert second["due_at"] == "2026-11-05T18:02:01+00:00"
    w.dialler.on_status(
        {"CallSid": sid, "CallStatus": call_status}
    )  # a repeated callback schedules nothing more
    assert len(w.ledger.dials(applicant.code)) == 2


def test_the_progress_callbacks_write_the_answer_time_and_the_status(tmp_path) -> None:
    w = World(tmp_path)
    _, dial_id, sid = placed(w)
    w.dialler.on_status({"CallSid": sid, "CallStatus": "ringing"})
    assert w.ledger.dial(dial_id)["twilio_status"] == "ringing"
    w.clock.advance(seconds=5)
    w.dialler.on_status({"CallSid": sid, "CallStatus": "in-progress"})
    answered = w.ledger.dial(dial_id)
    assert answered["status"] == "in-progress" and answered["answered_at"] == "2026-11-05T16:02:06+00:00"


def test_a_person_reached_ends_the_dialling(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, sid = placed(w)
    w.dialler.on_amd({"CallSid": sid, "AnsweredBy": "human"})
    assert w.twilio.updates == []
    w.dialler.session_ended(dial_id, {"candidate": applicant.code})
    w.dialler.on_status({"CallSid": sid, "CallStatus": "completed"})
    assert w.ledger.dial(dial_id)["outcome"] == "screen_unfinished"
    assert len(w.ledger.dials(applicant.code)) == 1  # no second attempt


def test_a_person_who_hangs_up_during_the_opening_is_not_called_again(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, sid = placed(w)
    w.dialler.on_status({"CallSid": sid, "CallStatus": "completed"})
    assert w.ledger.dial(dial_id)["outcome"] == "hung_up_before_pin"
    assert len(w.ledger.dials(applicant.code)) == 1


def test_a_machine_on_the_first_attempt_hears_the_voicemail_once_and_the_call_ends(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, sid = placed(w)
    w.dialler.on_amd({"CallSid": sid, "AnsweredBy": "machine_end_beep", "MachineDetectionDuration": "4100"})
    [(updated_sid, twiml)] = w.twilio.updates
    assert updated_sid == sid
    assert twiml.startswith('<Response><Say voice="Polly.Matthew-Neural">This is ACME')
    assert twiml.endswith("</Say><Hangup/></Response>")
    assert "message for Ada about a job application" in twiml
    assert "call us back at 3 1 2, 5 5 5, 0 1 0 0" in twiml  # the line's own number, digit by digit
    assert "Home Care Aide" not in twiml and applicant.code not in twiml  # never the role or the code
    vm = w.ledger.dial(dial_id)
    assert vm["voicemail_left"] is True and vm["outcome"] == "voicemail"
    # The stream ended because of the update; the session's end leaves detection's outcome as it is.
    assert w.dialler.session_ended(dial_id, {}) == "voicemail"
    w.dialler.on_status({"CallSid": sid, "CallStatus": "completed"})
    assert w.ledger.dial(dial_id)["outcome"] == "voicemail"
    assert [d["attempt"] for d in w.ledger.dials(applicant.code)] == [1, 2]


def test_a_machine_on_a_later_attempt_and_a_fax_end_the_call_with_no_message(tmp_path) -> None:
    w = World(tmp_path)
    _applicant, dial_id, sid = placed(w)
    w.ledger.update_dial(dial_id, attempt=2)
    w.dialler.on_amd({"CallSid": sid, "AnsweredBy": "machine_end_silence"})
    assert w.twilio.updates == [(sid, "<Response><Hangup/></Response>")]
    assert w.ledger.dial(dial_id)["outcome"] == "machine" and not w.ledger.dial(dial_id)["voicemail_left"]
    w2 = World(tmp_path / "fax")
    _, fax_dial, fax_sid = placed(w2)
    w2.dialler.on_amd({"CallSid": fax_sid, "AnsweredBy": "fax"})
    assert w2.twilio.updates == [(fax_sid, "<Response><Hangup/></Response>")]
    assert w2.ledger.dial(fax_dial)["outcome"] == "failed"


def test_no_attempt_is_scheduled_past_max_dial_attempts(tmp_path) -> None:
    w = World(tmp_path, MAX_DIAL_ATTEMPTS="1")
    applicant, _, sid = placed(w)
    w.dialler.on_status({"CallSid": sid, "CallStatus": "no-answer"})
    assert len(w.ledger.dials(applicant.code)) == 1


def test_attempt_three_lands_the_next_calling_day_at_the_windows_middle(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, sid = placed(w)
    w.ledger.update_dial(dial_id, attempt=2)
    w.dialler.on_status({"CallSid": sid, "CallStatus": "busy"})
    [third] = [d for d in w.ledger.dials(applicant.code) if d["attempt"] == 3]
    assert third["due_at"] == "2026-11-06T20:30:00+00:00"  # Friday 14:30 Central


def test_an_opt_out_on_the_call_stops_any_next_attempt(tmp_path) -> None:
    w = World(tmp_path)
    applicant, _dial_id, sid = placed(w)
    w.ledger.opt_out(applicant.code, how="said stop")
    w.dialler.on_status({"CallSid": sid, "CallStatus": "no-answer"})
    assert len(w.ledger.dials(applicant.code)) == 1


def test_a_callback_for_a_call_with_no_dial_record_changes_nothing(tmp_path) -> None:
    w = World(tmp_path)
    w.dialler.on_status({"CallSid": "CAunknown", "CallStatus": "completed"})
    w.dialler.on_amd({"CallSid": "CAunknown", "AnsweredBy": "machine_end_beep"})
    assert w.twilio.updates == [] and w.ledger.dials() == []


@pytest.mark.parametrize(
    ("data", "opted", "killed", "screened", "expected"),
    [
        ({"candidate": "C"}, False, False, True, "screened"),
        ({"candidate": "C"}, False, False, False, "screen_unfinished"),
        ({"verify_failures": 2}, False, False, False, "pin_missed"),
        ({}, False, False, False, "hung_up_before_pin"),
        ({}, False, True, False, "kill"),
        ({"candidate": "C"}, True, False, True, "opted_out"),
        ({"opted_out": "wrong person"}, True, False, False, "wrong_person"),
        ({"opted_out": "said stop"}, False, False, False, "opted_out"),
    ],
)
def test_the_sessions_outcome(data, opted, killed, screened, expected) -> None:
    class Ledger:
        def opted_out(self, code=None, number_hmac=None):
            return opted

        def screen(self, code):
            return {"result": "met"} if screened else None

    assert session_outcome(data, Ledger(), "C", killed) == expected  # type: ignore[arg-type]


def test_a_claim_left_by_a_crash_is_marked_failed_and_retried(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial = w.apply()
    w.ledger.update_dial(dial["dial_id"], status="claimed", claimed_at=w.clock().isoformat())
    assert w.dialler.tick() == "a call is in flight"
    w.clock.advance(seconds=121)
    w.dialler.tick()
    assert w.ledger.dial(dial["dial_id"])["outcome"] == "failed"
    assert [d["attempt"] for d in w.ledger.dials(applicant.code)] == [1, 2]


def test_a_lost_completed_callback_is_read_from_twilio_once_the_call_is_past_its_limit(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, _sid = placed(w)
    w.clock.advance(seconds=500)
    assert w.dialler.tick() == "a call is in flight"  # inside the call's own limit, nothing is asked
    w.twilio.status = "no-answer"
    w.clock.advance(seconds=400)
    w.dialler.tick()
    assert w.ledger.dial(dial_id)["outcome"] == "no_answer"
    assert [d["attempt"] for d in w.ledger.dials(applicant.code)] == [1, 2]


def test_find_dial_by_callsid_or_by_the_signed_dial_id_and_never_another_calls(tmp_path) -> None:
    w = World(tmp_path)
    _, dial = w.apply()
    w.ledger.update_dial(dial["dial_id"], status="placed")
    found = w.dialler.find_dial(
        "CA1", dial["dial_id"]
    )  # Twilio fetched /voice before the REST reply bound it
    assert found is not None and found["call_sid"] == "CA1"
    assert w.dialler.find_dial("CA1", "")["dial_id"] == dial["dial_id"]
    assert w.dialler.find_dial("CA2", dial["dial_id"]) is None  # bound to CA1
    assert w.dialler.find_dial("CA9", "") is None
    assert w.dialler.find_dial("CA9", "D-not-an-id") is None
    w.ledger.update_dial(dial["dial_id"], status="done")
    assert w.dialler.find_dial("CA1", "") is None  # no longer in flight


def test_an_opt_out_on_the_call_deletes_the_number_when_the_session_ends(tmp_path) -> None:
    w = World(tmp_path)
    applicant, dial_id, _ = placed(w)
    w.ledger.opt_out(applicant.code, how="wrong person")
    assert w.dialler.session_ended(dial_id, {"opted_out": "wrong person"}) == "wrong_person"
    assert w.contacts.number(applicant.code) is None


def test_the_sweep_deletes_the_number_of_an_application_that_opted_out_or_was_forgotten(tmp_path) -> None:
    w = World(tmp_path, OUTBOUND_ENABLED="0", OUTBOUND_ALLOWED_NUMBERS="")
    stopped, _ = w.apply(due_in_s=10**6)
    forgotten, _ = w.apply(number=fictional(143), due_in_s=10**6)
    kept, _ = w.apply(number=fictional(144), due_in_s=10**6)
    w.ledger.opt_out(stopped.code, how="said stop")  # on an inbound call, where no outbound session ends
    w.ledger.forget(forgotten.code)
    w.dialler.tick()
    assert w.contacts.codes() == (kept.code,)


def test_a_next_attempt_the_ledger_refuses_is_let_go(tmp_path, caplog) -> None:
    from candidate_line.tools.ledger import LedgerError

    class Refusing(FakeLedger):
        def schedule_dial(self, code, attempt, due_at):
            if attempt > 1:
                raise LedgerError("not_dialable", "This application is not dialled (not_allowed).")
            return super().schedule_dial(code, attempt, due_at)

    w = World(tmp_path, ledger=Refusing())
    applicant, _, sid = placed(w)
    with caplog.at_level(logging.INFO):
        w.dialler.on_status({"CallSid": sid, "CallStatus": "busy"})
    assert len(w.ledger.dials(applicant.code)) == 1
    assert "no attempt 2" in caplog.text
