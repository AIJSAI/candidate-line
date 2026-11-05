"""The dialler: one task in the line's process that places one outbound call at a time, and only when every gate
holds (spec 9.2 to 9.5, DR-025 sections 9 and 12).

Why one loop with every gate in code: a dial rings a stranger's phone and spends money with nobody watching, so it
is placed only with dialling on, no kill or no-dial file, the task past its first 120 s, the day's cap not reached,
no call in flight, the applicant consented and not opted out, inside their window, a number in the contacts store
that is on OUTBOUND_ALLOWED_NUMBERS, and a speech service that can still speak. The allow-list is checked here,
immediately before Calls.json, as an exact string, because it is the control that holds when intake, the ledger or
the contacts store is wrong (fix 13). Why the retention sweep runs on every tick whatever else is off: a raw number
must go on the first tick after its time even while dialling is off (fix 16). Why the callbacks live here too: the
outcome of a dial, the next attempt and the voicemail are one set of rules, and /voice/status, /voice/amd and the
media session all call into them.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfoNotFoundError

from candidate_line import hooks
from candidate_line.outbound import Applicant, OutboundLedger, voicemail_line
from candidate_line.outbound.contacts import Contacts
from candidate_line.outbound.window import in_window, next_attempt
from candidate_line.settings import Settings
from candidate_line.telephony.twilio_rest import TwilioError, TwilioRest, scrub_numbers
from candidate_line.tools.ledger import LedgerError
from candidate_line.traces.store import mask_number

log = logging.getLogger("candidate_line.dialler")

ROOT = Path(__file__).resolve().parents[2]
# `make dial-off` touches this and `make dial-on` removes it: it stops the dialler alone, the line stays open. The
# dialler also touches it itself when Polly answers AccessDenied, the AWS budget stop (DR-023).
NO_DIAL = ROOT / "var" / "no-dial"
TICK_S = 15.0
# A task that has just started may be one of two during a deploy, or one that is crash-looping; neither dials.
STARTUP_GRACE = timedelta(seconds=120)
RING_TIMEOUT_S = 30
# TimeLimit is the line's own cap plus this, so a line that has failed is still hung up by Twilio.
TIME_LIMIT_MARGIN_S = 60
# The one short word the preflight asks Polly for before a dial, so the line never rings a phone it cannot speak to.
PREFLIGHT_WORD = "Hello."
# A claim with no CallSid this old was never placed by this task, which is the only dialler (DesiredCount 1).
STALE_CLAIM = timedelta(seconds=120)
DIAL_ID = re.compile(r"^D-[0-9a-f]{12}$")
IN_FLIGHT = ("claimed", "placed", "in-progress")
FINISHED = ("done", "cancelled", "failed")
TERMINAL_CALL_STATUSES = ("completed", "busy", "failed", "no-answer", "canceled")
# Outcomes that mean no person was reached, so the next attempt is scheduled (spec 9.4).
NOT_REACHED = frozenset({"no_answer", "busy", "failed", "machine", "voicemail"})
_CALL_STATUS_OUTCOME = {"busy": "busy", "no-answer": "no_answer", "failed": "failed", "canceled": "no_answer"}
HANGUP_TWIML = "<Response><Hangup/></Response>"
VOICE = "Polly.Matthew-Neural"


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def is_access_denied(error: BaseException) -> bool:
    """Polly's answer once the budget action has denied the task role its speech services (DR-023)."""
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return "AccessDenied" in str(code) or "AccessDenied" in type(error).__name__


def _mark_not_dialled(ledger: OutboundLedger, code: str) -> None:
    """Records on the application that its number is off the allow-list, for the cockpit's "not dialled" and so
    no later attempt is ever scheduled for it. The dial is already cancelled and the number deleted before this
    runs, so a failure here is logged and never undoes either."""
    try:
        ledger.set_not_dialled(code, "not_allowed")
    except Exception:
        log.exception("the not-dialled reason for %s was not saved", code)


def _machine(answered_by: object) -> bool:
    return str(answered_by or "").startswith("machine")


def session_outcome(data: Mapping[str, Any], ledger: OutboundLedger, code: str, killed: bool) -> str:
    """The dial's outcome from what the media session's call did (DR-025 section 8). The PIN match is the
    session's `candidate`, which `confirm_applicant` sets; two misses are the shared `verify_failures`; an opt-out
    on the call leaves its `how` in `opted_out` (lane A's `screening.record_opt_out`)."""
    if data.get("opted_out") or ledger.opted_out(code=code):
        return "wrong_person" if data.get("opted_out") == "wrong person" else "opted_out"
    confirmed = data.get("candidate") == code
    if confirmed and ledger.screen(code):
        return "screened"
    if killed:
        return "kill"
    if int(data.get("verify_failures") or 0) >= 2:
        return "pin_missed"
    return "screen_unfinished" if confirmed else "hung_up_before_pin"


class Dialler:
    """The tick, the dial and the callbacks. `run` is the lifespan task; everything else is a plain method the
    tests call with a fake ledger, a fake Twilio and a pinned clock."""

    def __init__(
        self,
        settings: Settings,
        ledger: Callable[[], OutboundLedger],
        contacts: Contacts,
        twilio: TwilioRest | None,
        clock: Callable[[], datetime],
        preflight: Callable[[], object],
        no_dial: Path = NO_DIAL,
    ) -> None:
        self._settings = settings
        self._ledger = ledger
        self._contacts = contacts
        self._twilio = twilio
        self._clock = clock
        self._preflight = preflight
        self._no_dial = no_dial
        self.started_at = clock()

    async def run(self) -> None:
        """Ticks for the life of the process. A tick that fails is logged and the next one runs."""
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("dialler tick failed")
            await asyncio.sleep(TICK_S)

    # The tick.

    def tick(self) -> str:
        """One pass: the retention sweep, then at most one dial. Returns what it did, in a few words."""
        now = self._clock()
        self.sweep(now)
        closed = self.closed(now)
        if closed:
            return closed
        ledger = self._ledger()
        self._recover(ledger, now)
        if any(d.get("status") in IN_FLIGHT for d in ledger.dials()):
            return "a call is in flight"
        cap = self._settings.max_outbound_per_day
        if ledger.dials_placed_today() >= cap:
            return "the day's cap is reached"
        dial = ledger.claim_due_dial(now, cap, self._ready(now))
        if dial is None:
            return "nothing due"
        return self._place(ledger, dial, now)

    def sweep(self, now: datetime) -> None:
        """The retention sweep: raw numbers past CONTACTS_RETENTION_DAYS, and answers, dials and applications past
        ANSWERS_RETENTION_DAYS. Each half is tried on its own, so one failing never keeps the other from running."""
        try:
            purged = self._contacts.purge(now)
            if purged:
                log.info("retention: %d contact numbers deleted", purged)
        except Exception:
            log.exception("the contacts retention sweep failed")
        try:
            self._drop_stopped_contacts()
        except Exception:
            log.exception("the opt-out sweep of the contacts store failed")
        try:
            before = now - timedelta(days=self._settings.answers_retention_days)
            forgotten = self._ledger().purge_answers(before)
            if forgotten:
                log.info("retention: %d applications past the answers' retention removed", forgotten)
        except Exception:
            log.exception("the answers retention sweep failed")

    def _drop_stopped_contacts(self) -> None:
        """Deletes the number of any application that opted out (on an inbound call too, where no outbound
        session ends to do it) or that the ledger no longer holds (a deletion request), within one tick."""
        codes = self._contacts.codes()
        if not codes:
            return
        ledger = self._ledger()
        for code in codes:
            if ledger.applicant(code) is None or ledger.opted_out(code=code):
                self._contacts.delete(code)
                log.info("the number for %s was deleted: opted out or forgotten", code)

    def closed(self, now: datetime) -> str | None:
        """Why no dial may start now, or None. Read on every tick and again just before the dial."""
        if not self._settings.outbound_enabled:
            return "dialling is off"
        if hooks.KILL_SWITCH.exists():
            return "the kill switch is set"
        if self._no_dial.exists():
            return "the no-dial file is set"
        if now - self.started_at < STARTUP_GRACE:
            return "the task is under 120 s old"
        if self._twilio is None:
            return "no Twilio client"
        return None

    def _ready(self, now: datetime) -> Callable[[dict[str, Any], Applicant], bool]:
        def ready(dial: dict[str, Any], applicant: Applicant) -> bool:
            try:
                return in_window(now, applicant.zone, self._settings.call_window)
            except (ZoneInfoNotFoundError, ValueError):  # a zone this machine cannot read is no calling hour
                return False

        return ready

    def _place(self, ledger: OutboundLedger, dial: dict[str, Any], now: datetime) -> str:
        dial_id, code = str(dial["dial_id"]), str(dial["code"])
        applicant = ledger.applicant(code)
        if applicant is None:
            self._cancel(ledger, dial_id, "failed", now)
            log.warning("dial %s cancelled: no application %s", dial_id, code)
            return "no application"
        hashed = applicant.number_hmac
        if (
            not applicant.consented
            or ledger.opted_out(code=code)
            or (hashed is not None and ledger.opted_out(number_hmac=hashed))
        ):
            self._cancel(ledger, dial_id, "opted_out", now)
            self._contacts.delete(code)
            log.info("dial %s cancelled: %s has no consent or opted out", dial_id, code)
            return "no consent or opted out"
        number = self._contacts.number(code)
        if number is None:
            self._cancel(ledger, dial_id, "failed", now)
            log.warning("dial %s cancelled: no number for %s in the contacts store", dial_id, code)
            return "no number"
        if number not in self._settings.outbound_allowed_numbers:
            self._cancel(ledger, dial_id, "not_allowed", now)
            self._contacts.delete(code)
            _mark_not_dialled(ledger, code)
            log.warning("dial %s not placed: %s is not on the allow-list", dial_id, mask_number(number))
            return "not_allowed"
        closed = self.closed(self._clock())
        if closed:
            self._release(ledger, dial_id)
            return closed
        try:
            self._preflight()
        except Exception as error:  # noqa: BLE001 (any failure to speak means no dial; botocore raises many kinds)
            self._release(ledger, dial_id)
            if is_access_denied(error):
                self._no_dial.parent.mkdir(parents=True, exist_ok=True)
                self._no_dial.touch()
                log.error("Polly answered AccessDenied (the budget stop?); var/no-dial set, no dial placed")
                return "speech denied"
            log.warning(
                "the Polly preflight failed (%s); the dial waits for the next tick", type(error).__name__
            )
            return "preflight failed"
        return self._dial(ledger, dial, applicant, number, now)

    def _dial(
        self, ledger: OutboundLedger, dial: dict[str, Any], applicant: Applicant, number: str, now: datetime
    ) -> str:
        dial_id = str(dial["dial_id"])
        base = str(self._settings.public_base_url).rstrip("/")
        # Marked placed before the request, so a /voice that Twilio fetches before the reply finds the dial in
        # flight, and a failed request still counts against the day's cap: a cap that undercounts is no cap.
        ledger.update_dial(dial_id, status="placed", placed_at=stamp(now))
        assert self._twilio is not None
        try:
            call_sid = self._twilio.place_call(
                number,
                str(self._settings.twilio_line_number),
                url=f"{base}/voice?dial={dial_id}",
                status_callback=f"{base}/voice/status",
                amd_callback=f"{base}/voice/amd",
                timeout_s=RING_TIMEOUT_S,
                time_limit_s=self._settings.max_outbound_call_seconds + TIME_LIMIT_MARGIN_S,
            )
        except TwilioError as error:
            ledger.update_dial(dial_id, status="failed", outcome="failed", ended_at=stamp(now))
            log.warning("dial %s failed at Twilio: %s", dial_id, scrub_numbers(str(error)))
            self._schedule_next(ledger, dial, applicant, now)
            return "failed"
        ledger.bind_call(dial_id, call_sid)
        log.info(
            "dial %s placed for %s, attempt %s, to %s",
            dial_id,
            applicant.code,
            dial.get("attempt"),
            mask_number(number),
        )
        return "placed"

    def _cancel(self, ledger: OutboundLedger, dial_id: str, outcome: str, now: datetime) -> None:
        ledger.update_dial(dial_id, status="cancelled", outcome=outcome, ended_at=stamp(now))

    def _release(self, ledger: OutboundLedger, dial_id: str) -> None:
        """Hands a claim back, so the dial is due again on a later tick."""
        ledger.update_dial(dial_id, status="due", claimed_at=None, placed_at=None)

    def _schedule_next(
        self, ledger: OutboundLedger, dial: Mapping[str, Any], applicant: Applicant | None, made_at: datetime
    ) -> None:
        """The next attempt after one that reached nobody, while attempts remain and nobody opted out."""
        code = str(dial["code"])
        attempt = int(dial.get("attempt") or 1)
        if applicant is None or ledger.opted_out(code=code):
            return
        if any(int(d.get("attempt") or 0) > attempt or d.get("status") == "due" for d in ledger.dials(code)):
            return  # already scheduled, by an earlier callback for the same call
        due = next_attempt(
            attempt, made_at, applicant.zone, self._settings.call_window, self._settings.max_dial_attempts
        )
        if due is None:
            return
        try:
            ledger.schedule_dial(code, attempt + 1, due)
        except LedgerError as refused:
            # The ledger refuses a dial for an application it may never dial; that is the answer, not a fault.
            log.info("no attempt %d for %s: %s", attempt + 1, code, refused)
            return
        log.info("attempt %d for %s scheduled", attempt + 1, code)

    def _recover(self, ledger: OutboundLedger, now: datetime) -> None:
        """Ends a dial left in flight by a lost callback or a crash, so one lost message never stops the dialler."""
        limit = timedelta(
            seconds=self._settings.max_outbound_call_seconds + TIME_LIMIT_MARGIN_S + RING_TIMEOUT_S + 120
        )
        for d in ledger.dials():
            status, sid = d.get("status"), d.get("call_sid")
            claimed, placed = _parse(d.get("claimed_at")), _parse(d.get("placed_at"))
            if status == "claimed" and not sid and claimed is not None and now - claimed > STALE_CLAIM:
                self._lost(ledger, d, now, "a claim with no call")
            elif status in ("placed", "in-progress") and placed is not None and now - placed > limit:
                if sid and self._twilio is not None:
                    try:
                        call_status = self._twilio.call_status(str(sid))
                    except TwilioError as error:
                        log.warning(
                            "dial %s: Twilio status unread (%s)", d.get("dial_id"), type(error).__name__
                        )
                        call_status = ""
                    if call_status in TERMINAL_CALL_STATUSES:
                        self.on_status({"CallSid": str(sid), "CallStatus": call_status})
                        continue
                if now - placed > 2 * limit:
                    self._lost(ledger, d, now, "no end heard from Twilio")

    def _lost(self, ledger: OutboundLedger, d: Mapping[str, Any], now: datetime, why: str) -> None:
        ledger.update_dial(str(d["dial_id"]), status="failed", outcome="failed", ended_at=stamp(now))
        log.warning("dial %s marked failed: %s", d.get("dial_id"), why)
        self._schedule_next(ledger, d, ledger.applicant(str(d["code"])), _parse(d.get("placed_at")) or now)

    # /voice: the dial record an outbound call belongs to.

    def find_dial(self, call_sid: str, dial_hint: str) -> dict[str, Any] | None:
        """The in-flight dial for this call: by its CallSid, or by the signed dial id while no CallSid is bound,
        which then binds it. A dial bound to another call, or no longer in flight, answers nothing."""
        ledger = self._ledger()
        record = ledger.dial(call_sid) if call_sid else None
        if record is None and DIAL_ID.match(dial_hint):
            found = ledger.dial(dial_hint)
            if found is not None and found.get("call_sid") in (None, call_sid):
                record = ledger.bind_call(dial_hint, call_sid) if call_sid else None
        if record is None:
            return None
        if dial_hint and record.get("dial_id") != dial_hint:
            return None
        return record if record.get("status") in IN_FLIGHT else None

    def admit(self, dial: Mapping[str, Any], to: str) -> tuple[str | None, str]:
        """Whether /voice may answer this outbound call, checked again at answer time: the `To` on the allow-list
        (fix 13), no kill switch, and the applicant still consented and not opted out since the claim. Returns
        the refusal, which is also the dial's outcome, or None and the applicant's first name for the opening."""
        ledger = self._ledger()
        dial_id, code = str(dial["dial_id"]), str(dial["code"])
        now = self._clock()
        if to not in self._settings.outbound_allowed_numbers:
            ledger.update_dial(dial_id, status="cancelled", outcome="not_allowed", ended_at=stamp(now))
            self._contacts.delete(code)
            _mark_not_dialled(ledger, code)
            log.warning("outbound call %s hung up: %s is not on the allow-list", dial_id, mask_number(to))
            return "not_allowed", ""
        if hooks.KILL_SWITCH.exists():
            ledger.update_dial(dial_id, status="done", outcome="kill", ended_at=stamp(now))
            log.info("outbound call %s hung up: the kill switch is set", dial_id)
            return "kill", ""
        applicant = ledger.applicant(code)
        hashed = applicant.number_hmac if applicant is not None else None
        if (
            applicant is None
            or not applicant.consented
            or ledger.opted_out(code=code)
            or (hashed is not None and ledger.opted_out(number_hmac=hashed))
        ):
            ledger.update_dial(dial_id, status="done", outcome="opted_out", ended_at=stamp(now))
            self._contacts.delete(code)
            log.info("outbound call %s hung up: no consent or an opt-out since the claim", dial_id)
            return "opted_out", ""
        return None, applicant.first_name

    # /voice/status and /voice/amd.

    def on_status(self, form: Mapping[str, str]) -> None:
        """Writes Twilio's progress on a dial. At the end, a dial that reached nobody gets its outcome and, while
        attempts remain, the next attempt; one the session or detection has already given an outcome keeps it."""
        sid, call_status = form.get("CallSid", ""), form.get("CallStatus", "")
        ledger = self._ledger()
        dial = ledger.dial(sid) if sid else None
        if dial is None:
            log.info("status callback for a call with no dial record")
            return
        now = self._clock()
        fields: dict[str, Any] = {"twilio_status": call_status}
        if call_status == "in-progress":
            if not dial.get("answered_at"):
                fields["answered_at"] = stamp(now)
            if dial.get("status") in ("claimed", "placed"):
                fields["status"] = "in-progress"
        if call_status not in TERMINAL_CALL_STATUSES:
            ledger.update_dial(sid, **fields)
            return
        fields["ended_at"] = stamp(now)
        outcome = dial.get("outcome")
        if outcome is None:
            if call_status != "completed":
                outcome = _CALL_STATUS_OUTCOME.get(call_status, "failed")
            elif dial.get("voicemail_left"):
                outcome = "voicemail"
            elif _machine(dial.get("answered_by")):
                outcome = "machine"
            elif dial.get("answered_by") == "fax":
                outcome = "failed"
            else:
                outcome = "hung_up_before_pin"  # a person picked up and the stream never ran to a PIN
        fields["outcome"] = outcome
        if dial.get("status") not in FINISHED:
            fields["status"] = "failed" if call_status == "failed" else "done"
        ledger.update_dial(sid, **fields)
        if outcome in NOT_REACHED:
            made_at = _parse(dial.get("placed_at")) or now
            self._schedule_next(ledger, dial, ledger.applicant(str(dial["code"])), made_at)

    def on_amd(self, form: Mapping[str, str]) -> None:
        """Detection's verdict. A person (or no verdict) goes on. A machine on the first attempt hears the
        voicemail line once and the call ends; on a later attempt, or a fax, the call ends with no message."""
        sid, answered_by = form.get("CallSid", ""), form.get("AnsweredBy", "")
        ledger = self._ledger()
        dial = ledger.dial(sid) if sid else None
        if dial is None:
            log.info("detection callback for a call with no dial record")
            return
        # Written first, so a media session that ends because of what follows leaves the outcome to detection.
        ledger.update_dial(sid, answered_by=answered_by)
        if not (_machine(answered_by) or answered_by == "fax"):
            return
        if _machine(answered_by) and int(dial.get("attempt") or 1) == 1 and not dial.get("voicemail_left"):
            applicant = ledger.applicant(str(dial["code"]))
            first_name = applicant.first_name if applicant is not None else ""
            line = voicemail_line(first_name, str(self._settings.twilio_line_number))
            twiml = f'<Response><Say voice="{VOICE}">{escape(line)}</Say><Hangup/></Response>'
            if self._update(sid, twiml):
                ledger.update_dial(sid, voicemail_left=True, outcome="voicemail")
                log.info("voicemail left on dial %s", dial.get("dial_id"))
                return
        self._update(sid, HANGUP_TWIML)
        ledger.update_dial(sid, outcome="failed" if answered_by == "fax" else "machine")

    def _update(self, sid: str, twiml: str) -> bool:
        if self._twilio is None:
            return False
        try:
            self._twilio.update_call(sid, twiml)
            return True
        except TwilioError as error:
            log.warning("call update failed: %s", scrub_numbers(str(error)))
            return False

    # The media session's end.

    def session_ended(self, dial_id: str, data: Mapping[str, Any]) -> str | None:
        """Writes the outcome the media session's call reached. Detection's verdict, when it found a machine,
        stands: the session then ended because the call was turned into a voicemail or a hang-up."""
        ledger = self._ledger()
        dial = ledger.dial(dial_id)
        if dial is None:
            return None
        answered_by = dial.get("answered_by")
        if dial.get("voicemail_left") or _machine(answered_by) or answered_by == "fax":
            return dial.get("outcome")
        code = str(dial["code"])
        outcome = session_outcome(data, ledger, code, hooks.KILL_SWITCH.exists())
        if outcome in ("opted_out", "wrong_person"):
            self._contacts.delete(code)  # at once, not at the next sweep (spec 9.12 and 9.13)
        fields: dict[str, Any] = {"outcome": outcome}
        if dial.get("status") in IN_FLIGHT:
            fields["status"] = "done"
        ledger.update_dial(dial_id, **fields)
        return outcome
