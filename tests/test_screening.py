"""The outbound screen through the turn loop with a scripted brain (DR-025 sections 1 to 3, card 08 lane A): the
PIN, the intro and the questions said by code, "Noted:" after each answer, the unclear repeat, the skip, the met
line whole, the not-met line and its hand-off, the gate in book_slot and list_open_slots, the second PIN miss and
the stop.

The ledger: lane C owns tools/ledger.py, and until its commit lands the Ledger there has no applicant surface, so
these tests run on FakeLedger below, written to DR-025 section 7's method names and shapes. Once the real Ledger
has every method the tests use, `make_ledger` picks it instead, so the same tests hold lane C's ledger to the
contract. Every ledger pins its clock to the evening before the first interview slot (the eval runner's
EVAL_CLOCK), so no test waits for the calendar.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yaml

from candidate_line.brain import Message, Reply, ToolCall
from candidate_line.escalation import Escalation, format_email, format_subject
from candidate_line.hooks import default_hooks
from candidate_line.persona import (
    NO_SLOT_LINE,
    OUTBOUND_STOP_LINE,
    PIN_RETRY_LINE,
    PIN_SECOND_MISS_LINE,
    UNCLEAR_LINE,
    intro_line,
    outbound_opening,
    verified_applicant_line,
)
from candidate_line.tools import OUTBOUND_TOOL_SPECS, TOOL_SPECS, actions, screening
from candidate_line.tools.codes import code_digits, spoken_digits
from candidate_line.tools.ledger import (
    MAX_LISTED,
    DayFilter,
    Ledger,
    LedgerError,
    Slot,
    normalise_slot_id,
)
from candidate_line.tools.roles import DATA, ROLES_PATH, Role, load_roles, spoken_value
from candidate_line.traces.store import TraceStore
from candidate_line.turn import TurnContext, TurnResult, run_turn

NOW = datetime.fromisoformat(
    "2026-11-04T18:00:00-06:00"
)  # a Wednesday; the first interview slot is Thursday 09:00
ROLES = load_roles()
APPLICATIONS: list[dict[str, Any]] = yaml.safe_load((DATA / "applications.yaml").read_text(encoding="utf-8"))[
    "applications"
]
BY_CODE = {a["code"]: a for a in APPLICATIONS}
LERATO = BY_CODE["ACME-3108"]  # care-aide, Central, Recruiter A
CARMEN = BY_CODE["ACME-3474"]  # care-aide, New York
INES = BY_CODE["ACME-2609"]  # warehouse-associate, Recruiter B
MET_AIDE = {"q1": "yes", "q2": "weekends", "q3": "25", "q4": "yes", "q5": "yes"}
TEST_NUMBER = "+15555550142"  # a fictional 555-01xx number, injected at run time (DR-025 section 6)


# The fake ledger: DR-025 section 7's applicant surface, in memory, over the committed fixtures.


@dataclass(frozen=True)
class FakeApplicant:
    code: str
    first_name: str
    role: str
    zone: str
    received_at: str
    consent: dict[str, Any]
    number_hmac: str | None = None

    @property
    def consented(self) -> bool:
        return bool(self.consent.get("accepted"))


class FakeLedger(Ledger):
    """The real Ledger for candidates and first-round slots, and DR-025 section 7's methods for applicants."""

    def __init__(self, now: datetime = NOW) -> None:
        super().__init__(now=lambda: now)
        self._apps = {
            a["code"]: FakeApplicant(
                a["code"], a["first_name"], a["role"], a["zone"], a["applied_at"], dict(a["consent"])
            )
            for a in APPLICATIONS
        }
        self._app_pins = {a["code"]: str(a["pin"]) for a in APPLICATIONS}
        doc = yaml.safe_load(ROLES_PATH.read_text(encoding="utf-8"))
        rows = [
            Slot(
                str(s["id"]),
                datetime.fromisoformat(str(s["start"])),
                int(s["duration_min"]),
                str(s["recruiter"]),
                str(s["status"]),
                None,
            )
            for s in doc["interview_slots"]
        ]
        self._interview = {s.id: s for s in sorted(rows, key=lambda s: s.start)}
        self._recorded: dict[str, dict[str, dict[str, Any]]] = {}
        self._screens: dict[str, dict[str, Any]] = {}
        self._stops: list[dict[str, Any]] = []
        self._held: dict[str, str] = {}
        self._dial_rows: list[dict[str, Any]] = []

    def applicant(self, code: object) -> FakeApplicant | None:
        digits = code_digits(code)
        return next((a for c, a in self._apps.items() if code_digits(c) == digits), None) if digits else None

    def match(self, code: str, pin: str) -> Any:
        return super().match(code, pin) or self.match_applicant_pin(code, pin)

    def match_applicant_pin(self, code: str, pin: str) -> FakeApplicant | None:
        found = self.applicant(code)
        return found if found is not None and self._app_pins[found.code] == pin else None

    def answers(self, code: str) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._recorded.get(code, {}))

    def record_answer(
        self, code: str, question_id: str, value: str, heard: str, call_id: str | None
    ) -> dict[str, Any] | None:
        book = self._recorded.setdefault(code, {})
        previous = copy.deepcopy(book.get(question_id))
        book[question_id] = {"value": value, "heard": heard, "at": self._stamp_now(), "call_id": call_id}
        return previous

    def restore_answer(self, code: str, question_id: str, previous: dict[str, Any] | None) -> None:
        if previous is None:
            self._recorded.get(code, {}).pop(question_id, None)
        else:
            self._recorded.setdefault(code, {})[question_id] = previous

    def screen(self, code: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._screens.get(code))

    def set_screen(self, code: str, result: str, call_id: str | None, promised_by: str | None) -> None:
        self._screens[code] = {
            "result": result,
            "at": self._stamp_now(),
            "call_id": call_id,
            "promised_by": promised_by,
        }

    def clear_screen(self, code: str) -> None:
        self._screens.pop(code, None)

    def schedule_dial(self, code: str, attempt: int, due_at: datetime) -> dict[str, Any]:
        row = {"dial_id": f"D-{len(self._dial_rows):012x}", "code": code, "attempt": attempt, "status": "due"}
        row["due_at"] = due_at.astimezone(UTC).isoformat(timespec="seconds")
        self._dial_rows.append(row)
        return dict(row)

    def dials(self, code: str | None = None) -> list[dict[str, Any]]:
        return [dict(d) for d in self._dial_rows if code is None or d["code"] == code]

    def opt_out(self, code: str, how: str, call_id: str | None = None, number_hmac: str | None = None) -> int:
        cancelled = 0
        for row in self._dial_rows:
            if row["code"] == code and row["status"] == "due":
                row["status"], row["outcome"], cancelled = "cancelled", "opted_out", cancelled + 1
        self._stops.append(
            {
                "code": code,
                "number_hmac": number_hmac,
                "at": self._stamp_now(),
                "call_id": call_id,
                "how": how,
            }
        )
        return cancelled

    def opted_out(self, code: str | None = None, number_hmac: str | None = None) -> bool:
        return any(
            s["code"] == code or (number_hmac and s["number_hmac"] == number_hmac) for s in self._stops
        )

    def open_slots(
        self, day: DayFilter | None = None, limit: int = MAX_LISTED, recruiter: str | None = None
    ) -> list[Slot]:
        if recruiter is None:
            return super().open_slots(day, limit)
        held = set(self._held.values())
        return [
            s
            for s in self._interview.values()
            if s.interviewer == recruiter
            and s.status == "open"
            and s.id not in held
            and s.start > self._now()
            and (day is None or day.matches(s.start))
        ][:limit]

    def find_slot(self, text: object) -> Slot | None:
        found = super().find_slot(text)
        sid = normalise_slot_id(text)
        return found or (self._interview.get(sid) if sid else None)

    def booked_slot(self, code: str) -> Slot | None:
        if code in self._apps:
            sid = self._held.get(code)
            return self._interview.get(sid) if sid else None
        return super().booked_slot(code)

    def book(self, code: str, slot_id: object, call_id: str | None = None) -> Slot:
        if code not in self._apps:
            return super().book(code, slot_id, call_id)
        screen = self._screens.get(code)
        if not screen or screen["result"] != "met":
            raise LedgerError("screen_not_met", "This applicant's screen is not met, so nothing is booked.")
        if code in self._held:
            raise LedgerError("already_booked", "This applicant already holds a slot.")
        sid = normalise_slot_id(slot_id)
        slot = self._interview.get(sid) if sid else None
        if slot is None:
            raise LedgerError("unknown_slot", "There is no slot with that id.")
        if slot.id in self._held.values() or slot.start <= self._now():
            raise LedgerError("not_open", "That slot is not open.")
        self._held[code] = slot.id
        return slot

    def unbook(self, code: str, slot_id: str) -> bool:
        if code not in self._apps:
            return super().unbook(code, slot_id)
        if self._held.get(code) != slot_id:
            return False
        del self._held[code]
        return True

    def state(self, code: str) -> dict[str, Any]:
        if code not in self._apps:
            return super().state(code)
        role = ROLES[self._apps[code].role]
        recorded = self._recorded.get(code, {})
        screen = self._screens.get(code)
        return {
            "booked_slot": self._held.get(code),
            "answers_recorded": len(recorded),
            "questions_left": sum(1 for q in role.questions if q.id not in recorded),
            "screen": screen["result"] if screen else None,
            "opted_out": self.opted_out(code),
            "dials_due": sum(1 for d in self._dial_rows if d["code"] == code and d["status"] == "due"),
            "callback_requested": any(c.get("code") == code for c in self.callbacks()),
        }


_CONTRACT = (
    "applicant",
    "match_applicant_pin",
    "answers",
    "record_answer",
    "restore_answer",
    "screen",
    "set_screen",
    "clear_screen",
    "schedule_dial",
    "opt_out",
    "opted_out",
)
REAL_LEDGER = all(hasattr(Ledger, name) for name in _CONTRACT)


def make_ledger(now: datetime = NOW) -> Ledger:
    return Ledger(now=lambda: now) if REAL_LEDGER else FakeLedger(now)


# The scripted brain and the call.


class ScriptedBrain:
    """Returns its replies in order and records what it was sent; one call too many fails the test."""

    name = "scripted"
    model = "scripted"

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[Message], tuple[Any, ...]]] = []

    def reply(self, system: str, messages: Any, max_tokens: int = 200, tools: Any = ()) -> Reply:
        self.calls.append((list(messages), tuple(tools)))
        if not self.replies:
            raise AssertionError("the brain was called once more than the script allows")
        return self.replies.pop(0)


def said(text: str) -> Reply:
    return Reply(text, 50, 10, 100, "scripted", "scripted")


def asks(*calls: tuple[str, dict[str, Any]]) -> Reply:
    tool_calls = tuple(ToolCall(f"tu-{name}-{i}", name, args) for i, (name, args) in enumerate(calls))
    return Reply("", 50, 10, 100, "scripted", "scripted", tool_calls=tool_calls, stop_reason="tool_use")


class Queue:
    def __init__(self) -> None:
        self.items: list[Escalation] = []

    def submit(self, e: Escalation) -> bool:
        self.items.append(e)
        return True


def outbound_ctx(
    app: dict[str, Any] = LERATO, ledger: Ledger | None = None, store: TraceStore | None = None
) -> TurnContext:
    ctx = TurnContext(
        call_id="CA-out", channel="voice", system="sys", store=store, ledger=ledger or make_ledger()
    )
    ctx.data["outbound"] = {
        "code": app["code"],
        "first_name": app["first_name"],
        "dial_id": "D-0123456789ab",
        "attempt": 1,
    }
    ctx.escalations = Queue()  # type: ignore[assignment]
    return ctx


def turn(
    ctx: TurnContext, heard: str, *replies: Reply, tools: Any = OUTBOUND_TOOL_SPECS
) -> tuple[TurnResult, ScriptedBrain]:
    brain = ScriptedBrain(*replies)
    return run_turn(brain, default_hooks(), ctx, heard, tools=tools), brain


def confirm(ctx: TurnContext, pin: str) -> tuple[TurnResult, ScriptedBrain]:
    return turn(ctx, f"It's {pin}.", asks(("confirm_applicant", {"pin": pin})))


def answer(ctx: TurnContext, qid: str, value: str, heard: str = "") -> tuple[TurnResult, ScriptedBrain]:
    words = heard or f"my answer is {value}"
    return turn(ctx, words, asks(("record_answer", {"question_id": qid, "value": value, "heard": words})))


def screen(ctx: TurnContext, answers: dict[str, str]) -> TurnResult:
    """Every answer in posted order, after the PIN; the last turn's result."""
    result: TurnResult | None = None
    for qid, value in answers.items():
        result, _ = answer(ctx, qid, value)
    assert result is not None
    return result


def role_of(app: dict[str, Any]) -> Role:
    return ROLES[app["role"]]


def _met(role: Role) -> dict[str, str]:
    values: dict[str, str] = {}
    for q in role.questions:
        rule = q.rule
        values[q.id] = str(rule.value[0]) if rule.form == "one_of" else str(rule.value)  # type: ignore[index]
    return values


def _unmet_value(q: Any) -> str:
    if q.rule.form == "equals":
        return "no"
    if q.rule.form == "one_of":
        return next(o.id for o in q.options if o.id not in q.rule.value)
    return str(q.rule.value - 1) if q.rule.form == "at_least" else str(q.rule.value + 1)


# The PIN, the intro and the questions, said by code.


def test_the_pin_confirms_and_the_intro_and_first_question_are_said_by_code_in_one_model_call() -> None:
    ctx = outbound_ctx()
    result, brain = confirm(ctx, LERATO["pin"])
    aide = role_of(LERATO)
    assert result.spoken == f"{intro_line(5, 'Home Care Aide')} {aide.questions[0].say}"
    assert len(brain.calls) == 1 and brain.calls[0][1] == OUTBOUND_TOOL_SPECS
    assert ctx.data["candidate"] == "ACME-3108" and ctx.data["asked"] == "q1"
    assert result.tier == "1" and result.tools_called == ("confirm_applicant",) and result.hand_offs == ()
    [tool_result] = ctx.history[2].tool_results
    body = json.loads(tool_result.content)
    assert body == {
        "confirmed": True,
        "first_name": "Lerato",
        "role": "Home Care Aide",
        "questions": 5,
        "next_question_id": "q1",
        "values": "yes, no, declined or unclear",
    }
    assert LERATO["pin"] not in tool_result.content and LERATO["pin"] not in result.spoken
    # The history alternates as on the refusal path: tool use, results, then the words code said.
    assert [m.role for m in ctx.history] == ["user", "assistant", "tool", "assistant"]
    assert ctx.history[-1] == Message("assistant", result.spoken)
    # The intro offers a person at any time, routed through request_callback by the brief.
    assert "Say person at any time and a recruiter will call you instead." in result.spoken


def test_each_answer_is_followed_by_noted_and_the_next_question_with_one_model_call() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    aide = role_of(LERATO)
    result, brain = answer(ctx, "q1", "yes", "Yes, I've had my licence ten years.")
    assert result.spoken == f"Noted: yes. {aide.questions[1].say}" and len(brain.calls) == 1
    assert ctx.data["asked"] == "q2" and result.tier == "1"
    result, _ = answer(ctx, "q2", "weekends", "Weekends suit me best.")
    assert result.spoken == f"Noted: weekends only. {aide.questions[2].say}"
    result, _ = answer(ctx, "q3", "25", "About twenty-five.")
    assert result.spoken == f"Noted: 25 hours a week. {aide.questions[3].say}"
    recorded = ctx.ledger.answers("ACME-3108")  # type: ignore[union-attr]
    assert {qid: r["value"] for qid, r in recorded.items()} == {"q1": "yes", "q2": "weekends", "q3": "25"}
    assert (
        recorded["q1"]["heard"] == "Yes, I've had my licence ten years."
        and recorded["q1"]["call_id"] == "CA-out"
    )


def test_the_first_unclear_repeats_the_question_and_the_second_is_recorded() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    q1 = role_of(LERATO).questions[0]
    first, brain = answer(ctx, "q1", "unclear", "Hmm, it depends what you mean.")
    assert first.spoken == f"{UNCLEAR_LINE} {q1.say}" and len(brain.calls) == 1
    assert "q1" not in ctx.ledger.answers("ACME-3108")  # type: ignore[union-attr]
    second, _ = answer(ctx, "q1", "unclear", "I really couldn't say.")
    assert second.spoken.startswith("Noted: not clear. ") and ctx.data["asked"] == "q2"
    assert ctx.ledger.answers("ACME-3108")["q1"]["value"] == "unclear"  # type: ignore[union-attr]


def test_a_skip_counts_as_asked_and_meets_no_rule() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    skipped, _ = answer(ctx, "q1", "declined", "I'd rather skip that.")
    assert skipped.spoken.startswith("Noted: skipped. ") and ctx.data["asked"] == "q2"
    last = screen(ctx, {k: v for k, v in MET_AIDE.items() if k != "q1"})
    q1 = role_of(LERATO).questions[0]
    assert f"For this role, the posting asks for {q1.asks}." in last.spoken
    assert ctx.ledger.screen("ACME-3108")["result"] == "not_met"  # type: ignore[index, union-attr]


def test_the_met_line_is_said_whole_with_its_slots_and_its_question_and_posts_nothing() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    last = screen(ctx, MET_AIDE)
    assert last.spoken == (
        "Noted: yes. That's every question, thank you. A recruiter will read all your answers before the "
        "interview. The nearest open interview times are Thursday 5 November at 9:00 AM Central, Thursday 5 "
        "November at 1:00 PM Central and Friday 6 November at 9:00 AM Central. Which suits you?"
    )
    assert last.tier == "1" and last.hand_offs == () and ctx.escalations.items == []  # type: ignore[union-attr]
    saved = ctx.ledger.screen("ACME-3108")  # type: ignore[union-attr]
    assert saved is not None and saved["result"] == "met" and saved["promised_by"] is None
    body = json.loads(ctx.history[-2].tool_results[0].content)
    assert body["next_step"] == "offer_slots" and [s["id"] for s in body["slots"]] == [
        "S1105-0900",
        "S1105-1300",
        "S1106-0900",
    ]


def test_the_met_line_gives_each_slot_in_the_applicants_zone_beside_central() -> None:
    ctx = outbound_ctx(CARMEN)
    confirm(ctx, CARMEN["pin"])
    last = screen(ctx, MET_AIDE)
    assert "Thursday 5 November at 9:00 AM Central (10:00 AM New York time)" in last.spoken
    assert last.spoken.endswith("Which suits you?")


def test_the_not_met_line_names_only_the_posted_asks_and_posts_one_tier_two_screening_hand_off() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    aide = role_of(LERATO)
    last = screen(ctx, MET_AIDE | {"q2": "weekdays", "q3": "12"})
    assert last.spoken == (
        f"Noted: yes. That's every question, thank you. For this role, the posting asks for {aide.questions[1].asks} "
        f"and {aide.questions[2].asks}. A recruiter will read your answers and call you within one business day."
    )
    assert "weekdays" not in last.spoken and "12" not in last.spoken
    assert last.tier == "2"
    [hand_off] = last.hand_offs
    assert ctx.escalations.items == [hand_off]  # type: ignore[union-attr]
    assert hand_off.tier == "2" and hand_off.record_url == "http://127.0.0.1:8001/applicants/ACME-3108"
    assert hand_off.reason == (
        "screening hand-off from ACME-3108 (Lerato): Home Care Aide; recruiter call promised by "
        "6:00 PM Central on Thursday 5 November 2026"
    )
    assert format_subject(hand_off) == "Screening hand-off: Lerato (ACME-3108)"
    saved = ctx.ledger.screen("ACME-3108")  # type: ignore[union-attr]
    assert (
        saved is not None
        and saved["result"] == "not_met"
        and saved["promised_by"] == "2026-11-06T00:00:00+00:00"
    )


def test_a_met_screen_with_no_open_slot_says_the_no_slot_line_and_hands_off() -> None:
    late = datetime.fromisoformat("2026-11-19T10:00:00-06:00")  # after every interview slot; a Thursday
    ctx = outbound_ctx(ledger=make_ledger(late))
    confirm(ctx, LERATO["pin"])
    last = screen(ctx, MET_AIDE)
    assert last.spoken == f"Noted: yes. {NO_SLOT_LINE}" and last.tier == "2"
    [hand_off] = last.hand_offs
    assert hand_off.reason.endswith("promised by 10:00 AM Central on Friday 20 November 2026")
    assert ctx.ledger.screen("ACME-3108")["result"] == "met"  # type: ignore[index, union-attr]


def test_a_result_never_holds_a_verdict_word_the_model_could_repeat() -> None:
    for answers in (MET_AIDE, MET_AIDE | {"q4": "no"}):
        ctx = outbound_ctx()
        confirm(ctx, LERATO["pin"])
        screen(ctx, answers)
        contents = " ".join(r.content for m in ctx.history for r in m.tool_results)
        assert not re.search(r"(?i)\b(met|unmet|not_met|qualif\w*|eligible|pass\w*|fail\w*)\b", contents)


# The gate in code.


def test_book_slot_and_list_open_slots_refuse_while_a_question_is_unasked_even_when_called_directly() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    answer(ctx, "q1", "yes")
    result, _ = turn(
        ctx,
        "Just book me Thursday at nine.",
        asks(("list_open_slots", {}), ("book_slot", {"slot_id": "S1105-0900"})),
        said("Let's finish the questions first."),
    )
    listed, booked = (json.loads(r.content) for r in ctx.history[-2].tool_results)
    assert listed["error"] == booked["error"] == screening.GATE_UNASKED
    assert ctx.ledger.booked_slot("ACME-3108") is None and result.state["booked_slot"] is None  # type: ignore[index, union-attr]


def test_book_slot_and_list_open_slots_refuse_a_requirement_unmet_and_the_ledger_refuses_too() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    screen(ctx, MET_AIDE | {"q1": "no"})
    turn(
        ctx,
        "Can I have Thursday at nine anyway?",
        asks(("list_open_slots", {}), ("book_slot", {"slot_id": "S1105-0900"})),
        said("A recruiter will call you."),
    )
    listed, booked = (json.loads(r.content) for r in ctx.history[-2].tool_results)
    assert listed["error"] == booked["error"] == screening.GATE_UNMET
    with pytest.raises(LedgerError) as refused:
        ctx.ledger.book("ACME-3108", "S1105-0900")  # type: ignore[union-attr]
    assert refused.value.kind == "screen_not_met"


def test_after_the_met_line_the_applicant_books_only_the_roles_recruiters_open_slot() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    screen(ctx, MET_AIDE)
    turn(
        ctx,
        "Thursday at eleven.",
        asks(("book_slot", {"slot_id": "S1105-1100"})),
        said("That one isn't open."),
    )
    assert json.loads(ctx.history[-2].tool_results[0].content)["error"].startswith(
        "That is not one of the open"
    )
    turn(ctx, "9:30?", asks(("book_slot", {"slot_id": "S1105-0930"})), said("Not open."))
    assert "error" in json.loads(ctx.history[-2].tool_results[0].content)
    booked, _ = turn(
        ctx,
        "The first one.",
        asks(("book_slot", {"slot_id": "S1105-0900"})),
        said("Booked, Thursday at 9 AM."),
    )
    body = json.loads(ctx.history[-2].tool_results[0].content)
    assert body == {"booked": True, "slot_id": "S1105-0900", "slot": "Thursday 5 November at 9:00 AM Central"}
    assert booked.state["booked_slot"] == "S1105-0900" and booked.cited == ()  # type: ignore[index]
    [undo] = ctx.data["undo"]
    undo()  # a superseded turn's booking is taken back
    assert ctx.ledger.booked_slot("ACME-3108") is None  # type: ignore[union-attr]


def test_list_open_slots_for_a_met_applicant_gives_the_recruiters_slots_in_their_zone() -> None:
    ctx = outbound_ctx(INES)
    confirm(ctx, INES["pin"])
    screen(ctx, _met(role_of(INES)))
    outcome = actions.run_tool("list_open_slots", {}, ctx)
    body = json.loads(outcome.content)
    assert [s["id"] for s in body["slots"]][:2] == ["S1105-1100", "S1105-1630"]
    assert body["slots"][0]["local"] == "10:00 AM Denver time"


# The PIN misses.


def test_the_first_pin_miss_says_the_retry_line_and_the_second_the_second_miss_line_at_tier_three() -> None:
    ctx = outbound_ctx()
    first, brain = confirm(ctx, "1111")
    assert first.spoken == PIN_RETRY_LINE and len(brain.calls) == 1 and first.tier == "1"
    assert "candidate" not in ctx.data and ctx.data["verify_failures"] == 1
    second, _ = confirm(ctx, "2222")
    assert second.spoken == PIN_SECOND_MISS_LINE and second.tier == "3"
    assert "verification failed 2 times on this call" in ctx.data["tier3"]
    # No third PIN is checked, even the right one, and it is still kept for the guard.
    turn(
        ctx,
        LERATO["pin"],
        asks(("confirm_applicant", {"pin": LERATO["pin"]})),
        said("I can ask a recruiter to call."),
    )
    assert "candidate" not in ctx.data and LERATO["pin"] in ctx.data["pins_heard"]
    assert "Two misses already" in json.loads(ctx.history[-2].tool_results[0].content)["error"]


def test_confirm_applicant_needs_a_dialled_applicant_and_four_digits() -> None:
    inbound = TurnContext(call_id="CA-in", channel="voice", system="", ledger=make_ledger())
    outcome = actions.run_tool("confirm_applicant", {"pin": "4398"}, inbound)
    assert outcome.is_error and "no application on this call" in outcome.content
    ctx = outbound_ctx()
    outcome = actions.run_tool("confirm_applicant", {"pin": "43"}, ctx)
    assert outcome.is_error and "not four digits" in outcome.content and "verify_failures" not in ctx.data


def test_the_answers_wait_for_the_pin() -> None:
    ctx = outbound_ctx()
    outcome = actions.run_tool("record_answer", {"question_id": "q1", "value": "yes", "heard": "yes"}, ctx)
    assert outcome.is_error and json.loads(outcome.content)["error"] == screening.NOT_CONFIRMED


# What record_answer takes.


def test_an_answer_for_a_question_not_yet_said_names_the_one_to_record() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    for qid in ("q3", "q9", ""):
        outcome = actions.run_tool("record_answer", {"question_id": qid, "value": "yes", "heard": "yes"}, ctx)
        assert outcome.is_error and json.loads(outcome.content)["error"] == "Record the answer to q1."


@pytest.mark.parametrize(
    ("qid", "value", "allowed"),
    [
        ("q1", "maybe", "yes, no, declined or unclear"),
        ("q2", "sundays", "weekdays, weekends, both, declined or unclear"),
        ("q3", "4398", "a whole number from 0 to 60 (hours a week), declined or unclear"),
        ("q3", "61", "a whole number from 0 to 60 (hours a week), declined or unclear"),
    ],
)
def test_a_value_outside_the_questions_kind_names_the_values_it_takes(
    qid: str, value: str, allowed: str
) -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    for earlier, value_ in MET_AIDE.items():
        if earlier < qid:
            answer(ctx, earlier, value_)
    outcome = actions.run_tool("record_answer", {"question_id": qid, "value": value, "heard": value}, ctx)
    assert (
        outcome.is_error
        and json.loads(outcome.content)["error"] == f"For this question the value is {allowed}."
    )


def test_an_earlier_answer_may_be_recorded_again_until_the_last_then_the_answers_are_fixed() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    screen(ctx, {"q1": "yes", "q2": "both"})
    again, _ = answer(ctx, "q1", "no", "Sorry, my licence lapsed.")
    assert again.spoken == f"Noted: no. {role_of(LERATO).questions[2].say}"
    screen(ctx, {"q3": "30", "q4": "yes", "q5": "yes"})
    outcome = actions.run_tool("record_answer", {"question_id": "q1", "value": "yes", "heard": "yes"}, ctx)
    assert outcome.is_error and "fixed for this call" in outcome.content


def test_the_heard_words_are_kept_with_any_pin_or_phone_number_masked() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    words = f"Yes. My PIN is {LERATO['pin']} and call me on {TEST_NUMBER} instead."
    answer(ctx, "q1", "yes", words)
    kept = ctx.ledger.answers("ACME-3108")["q1"]["heard"]  # type: ignore[union-attr]
    # The tool masks the PIN and the number (DR-025 section 1); the ledger may mask more, never less.
    assert LERATO["pin"] not in kept and "5555550142" not in kept and kept.startswith("Yes. My PIN ****")


def test_a_superseded_turn_takes_back_its_answer_and_the_last_ones_screen() -> None:
    ctx = outbound_ctx()
    confirm(ctx, LERATO["pin"])
    answer(ctx, "q1", "yes")
    for reverse in reversed(ctx.data["undo"]):  # what media.py runs when the applicant's next words supersede
        reverse()
    assert ctx.ledger.answers("ACME-3108") == {} and ctx.data["asked"] == "q1"  # type: ignore[union-attr]
    screen(ctx, MET_AIDE)
    for reverse in reversed(ctx.data["undo"]):
        reverse()
    assert ctx.ledger.screen("ACME-3108") is None and "q5" not in ctx.ledger.answers("ACME-3108")  # type: ignore[union-attr]


def test_the_tool_spans_keep_the_question_and_value_and_mask_the_heard_digits() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-out", "outbound", caller=TEST_NUMBER)
    ctx = outbound_ctx(store=store)
    confirm(ctx, LERATO["pin"])
    answer(ctx, "q1", "yes", "Yes, licence 482913.")
    turn(
        ctx,
        "x",
        asks(("record_answer", {"question_id": "q2", "value": LERATO["pin"], "heard": "x"})),
        said("Which days?"),
    )
    tools = [s for s in store.spans("CA-out") if s.kind == "tool"]
    confirmed, recorded, refused = tools
    assert confirmed.text == "confirmed the applicant" and confirmed.meta["args"]["pin"] == "****"
    assert recorded.text == "recorded q1: yes"
    assert recorded.meta["args"] == {"question_id": "q1", "value": "yes", "heard": "Yes, licence ******."}
    assert refused.meta["args"]["value"] == "****"  # a PIN passed as a value is masked like free text
    assert LERATO["pin"] not in repr(store.spans("CA-out")) and "5555550142" not in repr(
        store.spans("CA-out")
    )


# The applicant who calls in.


def test_an_applicant_who_calls_in_verifies_by_code_and_pin_and_resumes_at_the_first_question_left() -> None:
    ledger = make_ledger()
    out = outbound_ctx(ledger=ledger)
    confirm(out, LERATO["pin"])
    screen(out, {"q1": "yes", "q2": "both"})
    ctx = TurnContext(call_id="CA-in", channel="voice", system="sys", ledger=ledger)
    ctx.escalations = Queue()  # type: ignore[assignment]
    brain = ScriptedBrain(asks(("verify_caller", {"code": "ACME-3108", "pin": LERATO["pin"]})))
    result = run_turn(brain, default_hooks(), ctx, f"ACME-3108, PIN {LERATO['pin']}", tools=TOOL_SPECS)
    q3 = role_of(LERATO).questions[2]
    assert result.spoken == (
        f"{verified_applicant_line(spoken_digits('3108'))} {intro_line(5, 'Home Care Aide')} {q3.say}"
    )
    assert len(brain.calls) == 1 and ctx.data["asked"] == "q3" and result.state["questions_left"] == 3  # type: ignore[index]
    rest, _ = turn(
        ctx,
        "thirty",
        asks(("record_answer", {"question_id": "q3", "value": "30", "heard": "thirty"})),
        tools=TOOL_SPECS,
    )
    assert rest.spoken.startswith("Noted: 30 hours a week. ")


# The stop.


def test_stop_calls_cancels_every_dial_says_the_stop_line_and_hangs_up_with_no_further_model_call() -> None:
    ledger = make_ledger()
    ledger.schedule_dial("ACME-3108", 2, NOW + timedelta(hours=2))  # type: ignore[attr-defined]
    ctx = outbound_ctx(ledger=ledger)
    result, brain = turn(ctx, "Please don't ring this phone again.", asks(("stop_calls", {})))
    assert result.spoken == OUTBOUND_STOP_LINE and result.hang_up is True and len(brain.calls) == 1
    assert json.loads(ctx.history[-2].tool_results[0].content) == {"stopped": True, "dials_cancelled": 1}
    assert result.state["opted_out"] is True and result.state["dials_due"] == 0  # type: ignore[index]
    assert ctx.data["opted_out"] == "said on the call" and result.tier == "1"


def test_stop_calls_with_nobody_on_the_list_is_refused() -> None:
    ctx = TurnContext(call_id="CA-in", channel="voice", system="", ledger=make_ledger())
    outcome = actions.run_tool("stop_calls", {}, ctx)
    assert outcome.is_error and "nobody on this call is on its list" in outcome.content


# The opening and the promised time.


@pytest.mark.parametrize("app", APPLICATIONS, ids=[a["code"] for a in APPLICATIONS])
def test_the_opening_names_the_first_name_and_nothing_else_from_the_record(app: dict[str, Any]) -> None:
    opening = outbound_opening(app["first_name"])
    role = role_of(app)
    assert app["first_name"] in opening and opening.startswith("Hello, this is ACME's automated hiring line")
    for secret in (role.title, role.site, role.recruiter, app["code"], code_digits(app["code"]), app["pin"]):
        assert str(secret) not in opening


@pytest.mark.parametrize(
    ("ended", "promised"),
    [
        ("2026-11-05T16:05:00-06:00", "2026-11-06T16:05:00-06:00"),  # Thursday to Friday
        ("2026-11-06T16:05:00-06:00", "2026-11-09T16:05:00-06:00"),  # Friday to Monday
        ("2026-11-07T11:00:00-06:00", "2026-11-09T11:00:00-06:00"),  # Saturday to Monday
        (
            "2026-11-08T11:00:00-06:00",
            "2026-11-09T11:00:00-06:00",
        ),  # a Sunday screen cannot happen; still Monday
        (
            "2026-11-05T22:30:00+00:00",
            "2026-11-06T16:30:00-06:00",
        ),  # read in Central, whatever zone it ends in
    ],
)
def test_the_promised_time_is_one_business_day_later_in_central(ended: str, promised: str) -> None:
    assert screening.promised_by(datetime.fromisoformat(ended)) == datetime.fromisoformat(promised)


# Fix 9: the email never carries an answer, a heard word or a requirement, for every fixture applicant.


def _heard_for(app: dict[str, Any], qid: str, value: str) -> str:
    return f"{app['first_name']} said {value} plainly for {qid}"


def _screen_all(app: dict[str, Any], answers: dict[str, str]) -> TurnContext:
    ctx = outbound_ctx(app, ledger=make_ledger(datetime.fromisoformat("2026-11-19T10:00:00-06:00")))
    confirm(ctx, app["pin"])
    for qid, value in answers.items():
        answer(ctx, qid, value, _heard_for(app, qid, value))
    return ctx


def _answer_sets(role: Role) -> list[dict[str, str]]:
    met = _met(role)
    sets = [met]  # met with no open slot: the clock is past every slot
    for q in role.questions:
        for bad in (_unmet_value(q), "declined"):
            sets.append(met | {q.id: bad})
    return sets


@pytest.mark.parametrize("app", APPLICATIONS, ids=[a["code"] for a in APPLICATIONS])
def test_the_screening_email_carries_the_link_and_the_time_and_no_answer_or_heard_word(
    app: dict[str, Any],
) -> None:
    role = role_of(app)
    for answers in _answer_sets(role):
        ctx = _screen_all(app, answers)
        [hand_off] = ctx.escalations.items  # type: ignore[union-attr]
        subject, body = format_subject(hand_off), format_email(hand_off)
        mail = f"{subject}\n{body}"
        assert subject == f"Screening hand-off: {app['first_name']} ({app['code']})"
        assert f"/applicants/{app['code']}" in body and "Thursday 19 November 2026" not in body
        assert "by 10:00 AM Central on Friday 20 November 2026" in body
        for q in role.questions:
            assert q.asks not in mail and q.say not in mail
            for option in q.options:
                assert option.say not in mail
            value = answers[q.id]
            assert _heard_for(app, q.id, value) not in mail
            assert spoken_value(q, value) not in mail or spoken_value(q, value) in ("yes", "no")
        assert not re.search(
            r"(?i)\b(yes|no|skipped|declined|unclear|not clear|hours a week|weeks|years)\b", mail
        )
        assert app["pin"] not in mail and "5555550142" not in mail


def test_the_voicemail_says_the_lines_number_digit_by_digit_and_never_the_role() -> None:
    from candidate_line.persona import spoken_number, voicemail_line

    assert spoken_number(TEST_NUMBER) == "5 5 5, 5 5 5, 0 1 4 2"
    line = voicemail_line("Lerato", TEST_NUMBER)
    assert line == (
        "This is ACME's automated hiring line with a message for Lerato about a job application. Please call us "
        "back at 5 5 5, 5 5 5, 0 1 4 2, or we'll try again later. To stop these calls, call that number and say stop."
    )
    assert "Home Care Aide" not in line and "Riverside" not in line and "3108" not in line
