"""The screening tools (DR-025 section 1): confirm_applicant, record_answer and stop_calls, and the helpers the
existing tools use for an applicant.

Why the words are code's: after the PIN, every line the applicant hears is a fixed line of spec 9.9 or a posted
question, said through ToolOutcome.say with no further model call, so no applicant ever hears a reaction to an
answer and every applicant hears the same words after the same answer. The model's one job is to map what the
applicant said to a posted value. Why the gate is called here and in actions.py: rules.check alone decides which
line follows the last answer and whether a booking may be offered, so a model that calls book_slot directly is
refused in code, and the ledger refuses the booking again.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from candidate_line import persona  # by module: persona imports the tools package, so its names are read late
from candidate_line.brain import ToolSpec
from candidate_line.escalation import SCREENING_HAND_OFF, spoken_central
from candidate_line.tools import rules
from candidate_line.tools.actions import (
    MAX_TEXT,
    MAX_VERIFY_ATTEMPTS,
    OFFER_CALLBACK,
    BadArgument,
    HandOff,
    ToolOutcome,
    _caller_zone,
    _error,
    _hear_pin,
    _json,
    _ledger,
    _schema,
    _scrub,
    _tool,
    _zone_words,
)
from candidate_line.tools.codes import pin_digits
from candidate_line.tools.ledger import (
    CENTRAL,
    MAX_LISTED,
    DayFilter,
    Ledger,
    Slot,
    normalise_slot_id,
    spoken_label,
)
from candidate_line.tools.roles import (
    DECLINED,
    UNCLEAR,
    Question,
    Role,
    allowed_values,
    default_roles,
    spoken_value,
)
from candidate_line.tools.roles import role as posted_role

if TYPE_CHECKING:
    from candidate_line.turn import TurnContext

# Read at import, so a roles file the gate must never read stops the process at start, never on a live call
# (DR-025 section 4), as hooks.py builds the guard from its lexicon.
default_roles()

# The met line offers at most three times (spec 9.9): as many as a caller holds from one spoken list.
MET_SLOTS = 3
# Every open slot of one recruiter, for the check that book_slot books only the role's recruiter's.
_ALL_SLOTS = 1000
GATE_UNASKED = "The screening questions come first; a booking is offered after the last one."
GATE_UNMET = "A recruiter calls this applicant within one business day; the line books nothing on this call."
HAND_OFF_ACTION = (
    "read the answers on the applicant's record and call them by the promised time; a person decides the "
    "application"
)
NOT_CONFIRMED = "The applicant is not confirmed yet. Ask for the PIN first."
# How each opt-out is recorded (DR-025 section 7's `how`).
SAID_ON_THE_CALL = "said on the call"
SAID_STOP = "said stop"
WRONG_PERSON = "wrong person"


class ApplicantRecord(Protocol):
    """What the tools read of an applicant: the ledger's Applicant (DR-025 section 7), never its PIN or number."""

    @property
    def code(self) -> str: ...

    @property
    def first_name(self) -> str: ...

    @property
    def role(self) -> str: ...

    @property
    def zone(self) -> str: ...


# Who is on the call.


def dialled(ctx: TurnContext) -> Mapping[str, Any] | None:
    """The application this outbound call was placed for, seeded from the dial record by the media session and
    never from anything the caller sent. Not yet proof of who answered: that is the PIN."""
    seed = ctx.data.get("outbound")
    return seed if isinstance(seed, Mapping) and seed.get("code") else None


def applicant(ctx: TurnContext, ledger: Ledger) -> ApplicantRecord | None:
    """The applicant the person on the line has proved to be, by the PIN on an outbound call or by the code and PIN
    on an inbound one. A candidate's code is never an applicant's (data/applications.yaml)."""
    code = ctx.data.get("candidate")
    if not code or ledger.candidate(code) is not None:
        return None
    return ledger.applicant(code)


def opt_out_code(ctx: TurnContext, ledger: Ledger) -> str | None:
    """Whose calls a stop on this call stops: the proved applicant, or before the PIN the dialled application,
    because a wrong person's "stop" must still end the calls to that number (spec 9.7)."""
    found = applicant(ctx, ledger)
    if found is not None:
        return found.code
    seed = dialled(ctx)
    return str(seed["code"]) if seed is not None else None


def role_of(found: ApplicantRecord) -> Role:
    posted = posted_role(found.role)
    if posted is None:
        raise BadArgument("This application's role is not on file. Offer a callback from a recruiter.")
    return posted


def answers_of(ledger: Ledger, code: str) -> dict[str, str]:
    """Question id to recorded value, the only thing the gate reads."""
    return {
        str(qid): str(record["value"])
        for qid, record in ledger.answers(code).items()
        if isinstance(record, Mapping) and isinstance(record.get("value"), str)
    }


def next_question(role: Role, answers: Mapping[str, str]) -> Question | None:
    return next((q for q in role.questions if q.id not in answers), None)


def gate(ledger: Ledger, found: ApplicantRecord) -> rules.GateResult:
    return rules.check(role_of(found), answers_of(ledger, found.code))


def gate_refusal(result: rules.GateResult) -> str | None:
    """The sentence list_open_slots and book_slot refuse with, or None when the gate lets a booking through."""
    if not result.complete:
        return GATE_UNASKED
    if not result.met:
        return GATE_UNMET
    return None


def screen_unfinished(ctx: TurnContext) -> bool:
    """An outbound or applicant call with no screen recorded yet, for the write-up of a call the length cap ended
    before the last question (spec section 7). False when nothing can be read: an observer never guesses."""
    ledger = ctx.ledger
    if ledger is None:
        return False
    try:
        code = opt_out_code(ctx, ledger)
        return code is not None and ledger.screen(code) is None
    except Exception:  # noqa: BLE001  (a read at call end never breaks the hang-up)
        return False


# Slots and times.


def local_words(slot: Slot, zone_name: str | None) -> str | None:
    """The slot in the applicant's zone when it is not Central: "10:00 AM New York time", with the day only when
    it differs, so the met line stays one breath per slot."""
    zone = _caller_zone(zone_name)
    if zone is None or not zone_name:
        return None
    here, central = slot.start.astimezone(zone), slot.start.astimezone(CENTRAL)
    if here.utcoffset() == central.utcoffset():
        return None
    words = spoken_label(here).removesuffix(" Central")
    if here.date() == central.date():
        words = words.split(" at ", 1)[1]
    return f"{words} {_zone_words(zone_name)}"


def slot_rows(
    ledger: Ledger, role: Role, zone_name: str | None, day: DayFilter | None = None, limit: int = MAX_LISTED
) -> list[dict[str, Any]]:
    """The role's recruiter's open interview slots, nearest first, each with its id, its Central words and, when
    the applicant's zone differs, the local words beside them (F3.4)."""
    rows: list[dict[str, Any]] = []
    for slot in ledger.open_slots(day, limit=limit, recruiter=role.recruiter):
        row: dict[str, Any] = {"id": slot.id, "label": slot.label}
        local = local_words(slot, zone_name)
        if local:
            row["local"] = local
        rows.append(row)
    return rows


def spoken_slot(row: Mapping[str, Any]) -> str:
    return f"{row['label']} ({row['local']})" if row.get("local") else str(row["label"])


def recruiters_open_slot(ledger: Ledger, role: Role, slot_id: object) -> Slot | None:
    """The slot when it is one of the role's recruiter's open interview slots, so book_slot can never book another
    recruiter's time or a first-round slot for an applicant."""
    wanted = normalise_slot_id(slot_id)
    if wanted is None:
        found = ledger.find_slot(slot_id)
        wanted = found.id if found is not None else None
    if wanted is None:
        return None
    return next(
        (s for s in ledger.open_slots(None, limit=_ALL_SLOTS, recruiter=role.recruiter) if s.id == wanted),
        None,
    )


def promised_by(ended: datetime) -> datetime:
    """One business day after the screen ended, at the same Central clock time (spec 9.11): Thursday's screen is
    promised by Friday, Friday's and Saturday's by Monday. No holiday logic, by the build's ruling."""
    when = ended.astimezone(CENTRAL) + timedelta(days=1)
    while when.weekday() >= 5:
        when += timedelta(days=1)
    return when


def _clock(ledger: Ledger) -> datetime:
    # The ledger's own clock, which the tests and the eval runner pin; DR-025 section 7 names no public one.
    return ledger._now()


def screening_hand_off(found: ApplicantRecord, role: Role, when: datetime) -> HandOff:
    """The recruiter's hand-off (DR-025 section 15): who, the role and the promised time, and never an answer,
    the applicant's words or which requirement, so no email can carry them."""
    return HandOff(
        reason=(
            f"{SCREENING_HAND_OFF} from {found.code} ({found.first_name}): {role.title}; "
            f"recruiter call promised by {spoken_central(when)}"
        ),
        suggested_action=HAND_OFF_ACTION,
        record_code=found.code,
    )


# What the line says once the person is proved to be the applicant.


def resume(
    ctx: TurnContext, ledger: Ledger, found: ApplicantRecord, role: Role, lead: str | None = None
) -> tuple[str | None, dict[str, Any]]:
    """The words after a PIN match or a code and PIN for an applicant: `lead`, the intro and the first question
    not yet recorded, with the result fields the model reads; or no words and the next step when the screen is
    already complete, because then there is nothing fixed to say."""
    answers = answers_of(ledger, found.code)
    nxt = next_question(role, answers)
    if nxt is None or ledger.screen(found.code) is not None:
        return None, finished(ledger, found, role, answers)
    ctx.data["asked"] = nxt.id
    words = [lead] if lead else []
    words += [persona.intro_line(len(role.questions), role.title), nxt.say]
    return " ".join(words), {"next_question_id": nxt.id, "values": allowed_values(nxt)}


def finished(
    ledger: Ledger, found: ApplicantRecord, role: Role, answers: Mapping[str, str]
) -> dict[str, Any]:
    """The next step of a complete screen, for an applicant who comes back to it. Its keys name no verdict."""
    body: dict[str, Any] = {"next_question_id": None, "complete": True}
    booked = ledger.booked_slot(found.code)
    if booked is not None:
        return body | {"next_step": "booked", "booked_slot": booked.label}
    if rules.check(role, answers).met:
        slots = slot_rows(ledger, role, found.zone, limit=MET_SLOTS)
        if slots:
            return body | {"next_step": "offer_slots", "slots": slots}
    body["next_step"] = "recruiter_call"
    screen = ledger.screen(found.code) or {}
    promised = screen.get("promised_by")
    if isinstance(promised, str):
        try:
            body["recruiter_calls_by"] = spoken_central(datetime.fromisoformat(promised))
        except ValueError:
            pass
    return body


# The tools.


@_tool
def confirm_applicant(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    seed = dialled(ctx)
    if seed is None:
        raise BadArgument("There is no application on this call to confirm.")
    code = str(seed["code"])
    failures = int(ctx.data.get("verify_failures", 0))
    raw = args.get("pin")
    if failures >= MAX_VERIFY_ATTEMPTS:
        # Never checked, but a PIN said is a PIN before_speak must still be able to catch (as verify_caller).
        insisted = pin_digits(raw) if raw not in (None, "") else None
        if insisted is not None:
            _hear_pin(ctx, insisted)
        return _error(f"Two misses already on this call. {OFFER_CALLBACK}")
    pin = pin_digits(raw) if raw not in (None, "") else None
    if pin is None:
        raise BadArgument("The PIN was not four digits. Ask the applicant to say it again, digit by digit.")
    _hear_pin(ctx, pin)
    found = ledger.match_applicant_pin(code, pin)
    if found is None:
        # One thing the applicant said is one try, however many readings of it the model checks (spec 3.1).
        if not ctx.data.get("missed_this_turn"):
            failures += 1
            ctx.data["verify_failures"] = failures
            ctx.data["missed_this_turn"] = True
        second = failures >= MAX_VERIFY_ATTEMPTS
        miss: dict[str, Any] = {
            "confirmed": False,
            "failures": failures,
            "tries_left": max(MAX_VERIFY_ATTEMPTS - failures, 0),
        }
        if second:
            miss["next"] = OFFER_CALLBACK
        return ToolOutcome(
            content=_json(miss),
            state=ledger.state(code),
            say=persona.PIN_SECOND_MISS_LINE if second else persona.PIN_RETRY_LINE,
        )
    role = role_of(found)
    ctx.data["candidate"] = found.code
    say, more = resume(ctx, ledger, found, role)
    body = {
        "confirmed": True,
        "first_name": found.first_name,
        "role": role.title,
        "questions": len(role.questions),
    } | more
    return ToolOutcome(content=_json(body), state=ledger.state(found.code), say=say)


@_tool
def record_answer(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    found = applicant(ctx, ledger)
    if found is None:
        raise BadArgument(NOT_CONFIRMED)
    role = role_of(found)
    if ledger.screen(found.code) is not None:
        raise BadArgument("Every question is answered; the answers are fixed for this call.")
    answers = answers_of(ledger, found.code)
    asked_before = ctx.data.get("asked")
    question = _said_question(ctx, role, answers, args.get("question_id"))
    value = _value(question, args.get("value"))
    heard = _scrub(_heard(args), ctx, ledger) or ""
    if value == UNCLEAR and question.id not in (ctx.data.get("unclear") or ()):
        # The first unclear asks again and writes nothing (spec 9.8); a superseded turn takes the count back,
        # because the applicant never heard the question again.
        unclear: list[str] = ctx.data.setdefault("unclear", [])
        unclear.append(question.id)
        ctx.data["asked"] = question.id

        def forget_unclear() -> None:
            if question.id in unclear:
                unclear.remove(question.id)
            ctx.data["asked"] = asked_before

        return ToolOutcome(
            content=_json(
                {
                    "recorded": False,
                    "question_id": question.id,
                    "asked_again": True,
                    "values": allowed_values(question),
                }
            ),
            state=ledger.state(found.code),
            say=f"{persona.UNCLEAR_LINE} {question.say}",
            undo=forget_unclear,
        )
    previous = ledger.record_answer(found.code, question.id, value, heard, ctx.call_id)
    answers[question.id] = value
    result = rules.check(role, answers)
    ack = persona.ack_line(spoken_value(question, value))
    body: dict[str, Any] = {"recorded": True, "question_id": question.id, "value": value}
    code = found.code

    if not result.complete:
        nxt = next_question(role, answers)
        assert nxt is not None  # not complete means a question is unasked
        ctx.data["asked"] = nxt.id

        def take_back() -> None:
            ledger.restore_answer(code, question.id, previous)
            ctx.data["asked"] = asked_before

        body |= {
            "next_question_id": nxt.id,
            "questions_left": len(result.unasked),
            "values": allowed_values(nxt),
        }
        return ToolOutcome(
            content=_json(body), state=ledger.state(code), say=f"{ack} {nxt.say}", undo=take_back
        )

    # The last answer: the gate decides which fixed line follows, and nothing else does.
    body |= {"next_question_id": None, "questions_left": 0, "complete": True}
    slots = slot_rows(ledger, role, found.zone, limit=MET_SLOTS) if result.met else []
    hand_off: HandOff | None = None
    if slots:
        ledger.set_screen(code, "met", ctx.call_id, None)
        body |= {"next_step": "offer_slots", "slots": slots}
        say = f"{ack} {persona.met_line([spoken_slot(s) for s in slots])}"
    else:
        when = promised_by(_clock(ledger))
        ledger.set_screen(
            code,
            "met" if result.met else "not_met",
            ctx.call_id,
            when.astimezone(UTC).isoformat(timespec="seconds"),
        )
        body |= {"next_step": "recruiter_call", "recruiter_calls_by": spoken_central(when)}
        if result.met:
            say = f"{ack} {persona.NO_SLOT_LINE}"
        else:
            asks = [q.asks for q in role.questions if q.id in result.unmet]
            say = f"{ack} {persona.not_met_line(asks)}"
        hand_off = screening_hand_off(found, role, when)

    def take_back_screen() -> None:
        ledger.clear_screen(code)
        ledger.restore_answer(code, question.id, previous)
        ctx.data["asked"] = asked_before

    return ToolOutcome(
        content=_json(body), state=ledger.state(code), say=say, escalate=hand_off, undo=take_back_screen
    )


@_tool
def stop_calls(args: Mapping[str, Any], ctx: TurnContext) -> ToolOutcome:
    ledger = _ledger(ctx)
    code = opt_out_code(ctx, ledger)
    if code is None:
        raise BadArgument(
            "This line calls only people who applied and agreed to it; nobody on this call is on its list."
        )
    cancelled = record_opt_out(ctx, SAID_ON_THE_CALL)
    return ToolOutcome(
        content=_json({"stopped": True, "dials_cancelled": cancelled or 0}),
        state=ledger.state(code),
        say=persona.OUTBOUND_STOP_LINE,
        hang_up=True,
    )


def record_opt_out(ctx: TurnContext, how: str) -> int | None:
    """Records that no further call goes to this applicant's number and cancels every dial still due, at once
    (spec 9.12). The tool and the hooks' phrase rule both come here. None when nobody on the call is an applicant
    or a dialled application. A failed save raises, so the caller never hears a promise the ledger did not keep."""
    ledger = _ledger(ctx)
    code = opt_out_code(ctx, ledger)
    if code is None:
        return None
    seed = dialled(ctx) or {}
    number_hmac = seed.get("number_hmac") if seed.get("code") == code else None
    cancelled = ledger.opt_out(code, how=how, call_id=ctx.call_id, number_hmac=number_hmac)
    # The media session and the dialler read this for the dial's outcome and to delete the contact at once.
    ctx.data["opted_out"] = how
    return int(cancelled)


# Inside the tools.


def _said_question(ctx: TurnContext, role: Role, answers: Mapping[str, str], raw: object) -> Question:
    """The question an answer is for: one the line has said on this call or recorded before, never one ahead."""
    ids = [q.id for q in role.questions]
    asked = ctx.data.get("asked")
    said = set(answers)
    if asked in ids:
        said |= set(ids[: ids.index(asked) + 1])
    wanted = str(raw).strip().lower() if isinstance(raw, str | int) and not isinstance(raw, bool) else ""
    question = role.question(wanted) if wanted else None
    if question is None or question.id not in said:
        expected = asked if asked in ids else getattr(next_question(role, answers), "id", ids[-1])
        raise BadArgument(f"Record the answer to {expected}.")
    return question


def _value(question: Question, raw: object) -> str:
    """A posted value for this question, or the refusal naming the values it takes. A number is a whole number
    inside the posted scale, so a PIN can never pass as an answer."""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    if isinstance(raw, int) and not isinstance(raw, bool):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw.strip().lower()
    else:
        text = ""
    if text in (DECLINED, UNCLEAR):
        return text
    if question.kind == "yes_no" and text in ("yes", "no"):
        return text
    if question.kind == "choice" and question.option(text) is not None:
        return text
    if question.kind == "range" and question.range is not None and re.fullmatch(r"[0-9]{1,3}", text):
        number = int(text)
        if question.range.min <= number <= question.range.max:
            return str(number)
    raise BadArgument(f"For this question the value is {allowed_values(question)}.")


def _heard(args: Mapping[str, Any]) -> str | None:
    value = args.get("heard")
    if value is None or isinstance(value, Mapping | list | tuple):
        return None
    return re.sub(r"\s+", " ", str(value)).strip()[:MAX_TEXT] or None


# The tool specs. No description names a record's id, a question's id or a slot, so the model takes each from a
# result and never from an example (actions.py, the note above TOOL_SPECS).
CONFIRM_APPLICANT_SPEC = ToolSpec(
    "confirm_applicant",
    "Check the four-digit PIN the applicant chose when they applied. Pass it as heard.",
    _schema({"pin": {"type": "string", "description": "The four-digit PIN as heard."}}, ("pin",)),
)
RECORD_ANSWER_SPEC = ToolSpec(
    "record_answer",
    "Record the applicant's answer to the question the line just asked, after every answer. The line then says "
    "the next words itself.",
    _schema(
        {
            "question_id": {"type": "string", "description": "The question id the last result named."},
            "value": {
                "type": "string",
                "description": "One of the values the last result allows; unclear when the answer is not plainly "
                "one, declined for a skip.",
            },
            "heard": {"type": "string", "description": "The applicant's own words."},
        },
        ("question_id", "value", "heard"),
    ),
)
STOP_CALLS_SPEC = ToolSpec(
    "stop_calls",
    "The applicant asks not to be called again: stop every further call. The line says goodbye and ends the call.",
    _schema({}),
)
