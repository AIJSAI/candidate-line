"""The tier rule (card 06): three inputs or more per tier, readable reasons, and the hand-off it builds."""

from __future__ import annotations

import pytest

from candidate_line import tiers
from candidate_line.persona import KILL_LINE, OUTBOUND_STOP_LINE, PIN_ASK, REFUSAL_LINE, STOP_LINE
from candidate_line.tiers import Tier, assign, write_ups
from candidate_line.tools import HandOff
from candidate_line.traces.store import TraceStore
from candidate_line.turn import TurnContext


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {"tools_called": ["verify_caller", "book_slot"]},
            "handled alone: checked the code and PIN, booked a slot",
        ),
        (
            {"tools_called": ["answer_question"], "spoken": "Thirty minutes. That is F2.1."},
            "answered from the FAQ",
        ),
        ({"tools_called": [], "spoken": STOP_LINE}, "handled alone: the caller said stop"),
        ({"tools_called": [], "spoken": KILL_LINE}, "handled alone: the kill switch closed the call"),
        ({"tools_called": ["verify_caller"], "verify_failures": 1}, "checked the code and PIN"),
        ({"tools_called": [], "spoken": "Hello."}, "handled alone: a spoken answer, no tool"),
    ],
)
def test_tier_one_is_the_line_handling_it_alone(kwargs: dict, reason: str) -> None:
    tier = assign(**kwargs)
    assert tier.tier == "1" and reason in tier.reason


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"tools_called": ["verify_caller", "move_slot"]}, "a move request went to the coordinator"),
        ({"tools_called": ["request_callback"]}, "a callback request went to the coordinator"),
        (
            {"tools_called": ["move_slot", "request_callback"]},
            "a move request went to the coordinator; a callback request went to the coordinator",
        ),
    ],
)
def test_tier_two_is_a_hand_off_to_the_coordinator(kwargs: dict, reason: str) -> None:
    assert assign(**kwargs) == Tier("2", reason)


def test_a_hand_off_outranks_a_write_up_and_still_names_it() -> None:
    tier = assign(["request_callback"], guard_hits=("p01",))
    assert tier.tier == "2"
    assert tier.reason == (
        "a callback request went to the coordinator; to write up after the call: the guard replaced a sentence (p01)"
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {"tools_called": [], "guard_hits": ("p01", "eval-09", "p01")},
            "the guard replaced a sentence (p01, eval-09)",
        ),
        ({"tools_called": ["answer_question"], "refused": True}, "the refusal line was said"),
        (
            {"tools_called": [], "spoken": REFUSAL_LINE},
            "the refusal line was said",
        ),  # the model said it itself
        (
            {"tools_called": ["verify_caller"], "verify_failures": 2},
            "verification failed 2 times on this call",
        ),
        (
            {"tools_called": ["verify_caller"], "verify_failures": 3},
            "verification failed 3 times on this call",
        ),
    ],
)
def test_tier_three_is_written_up_after_the_call(kwargs: dict, reason: str) -> None:
    tier = assign(**kwargs)
    assert tier.tier == "3" and reason in tier.reason


def test_the_write_ups_never_quote_the_caught_sentence() -> None:
    # A pin- rule's sentence holds the PIN, so the reason names the rule only.
    assert write_ups(guard_hits=("pin-01",)) == ("the guard replaced a sentence (pin-01)",)
    assert write_ups() == ()


def test_the_hand_off_carries_the_masked_caller_and_the_trace_link() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA-tier", "voice", caller="+15555550142")
    ctx = TurnContext(call_id="CA-tier", channel="voice", system="", store=store)
    hand_off = tiers.escalation(ctx, "2", "callback request", "call the candidate back")
    assert hand_off.caller == "***-***-0142" and "5555550142" not in repr(hand_off)
    assert hand_off.trace_url == "http://127.0.0.1:8001/calls/CA-tier"
    bare = TurnContext(call_id="text-1", channel="text", system="")
    assert tiers.escalation(bare, "3", "x", "read the trace").caller == "-"
    assert tiers.submit(bare, hand_off) is False  # no queue, nothing posted


# Tiers by outcome (DR-025 section 15, fix 10): the hand-offs a turn posted, not only the tool names.

SCREENING = HandOff(
    reason="screening hand-off from ACME-3108 (Lerato): Home Care Aide; recruiter call promised by 6:00 PM Central",
    suggested_action="read the answers on the record",
    record_code="ACME-3108",
)


def test_any_turn_that_posted_a_hand_off_is_tier_two_whatever_the_tool() -> None:
    tier = assign(["record_answer"], hand_offs=(SCREENING,))
    assert tier == Tier(
        "2", "a screening hand-off was posted for the role's recruiter, to the operator's channel"
    )
    # The same tool ending a screen with a booking offer posts nothing and is tier 1.
    assert assign(["record_answer"]).tier == "1"
    callback = HandOff(
        "callback request from ACME-3108 (Lerato): no reason given; best time not given", "call"
    )
    assert assign(["request_callback"], hand_offs=(callback,)) == Tier(
        "2", "a callback request went to the coordinator"
    )
    odd = HandOff("a new kind from someone", "act")
    assert assign([], hand_offs=(odd,)) == Tier("2", "a hand-off went to a person (a new kind)")


def test_a_screening_hand_off_outranks_a_guard_write_up_and_names_it() -> None:
    tier = assign(["record_answer"], guard_hits=("screen-01",), hand_offs=(SCREENING,))
    assert (
        tier.tier == "2"
        and "to write up after the call: the guard replaced a sentence (screen-01)" in tier.reason
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"tools_called": ["confirm_applicant"]}, "handled alone: confirmed the applicant by PIN"),
        ({"tools_called": ["confirm_applicant", "record_answer"]}, "recorded an answer"),
        ({"tools_called": ["stop_calls"], "spoken": "x"}, "stopped every further call"),
        ({"tools_called": [], "spoken": OUTBOUND_STOP_LINE}, "the applicant asked for no more calls"),
        ({"tools_called": [], "spoken": PIN_ASK}, "the PIN ask, said again by code"),
    ],
)
def test_the_outbound_tools_handled_alone_are_tier_one(kwargs: dict, reason: str) -> None:
    tier = assign(**kwargs)
    assert tier.tier == "1" and reason in tier.reason


def test_a_second_pin_miss_is_tier_three_by_the_shared_count() -> None:
    tier = assign(["confirm_applicant"], verify_failures=2)
    assert tier == Tier("3", "verification failed 2 times on this call")


def test_a_screening_escalation_carries_the_applicants_record_link() -> None:
    ctx = TurnContext(call_id="CA-out", channel="voice", system="")
    hand_off = tiers.escalation(
        ctx, "2", SCREENING.reason, SCREENING.suggested_action, record_code="ACME-3108"
    )
    assert hand_off.record_url == "http://127.0.0.1:8001/applicants/ACME-3108"
    assert tiers.escalation(ctx, "2", "x", "y").record_url is None
