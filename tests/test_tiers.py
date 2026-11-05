"""The tier rule (card 06): three inputs or more per tier, readable reasons, and the hand-off it builds."""

from __future__ import annotations

import pytest

from candidate_line import tiers
from candidate_line.persona import KILL_LINE, REFUSAL_LINE, STOP_LINE
from candidate_line.tiers import Tier, assign, write_ups
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
