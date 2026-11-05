"""The scorecard (card 07) from three synthetic calls on an in-memory store and a ledger file in tmp_path."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from candidate_line import scorecard
from candidate_line.scorecard import (
    bookings_kept,
    build,
    call_cost_usd,
    invite_to_booked_hours,
    invited_at,
    ledger_bookings,
    read_baseline,
    read_calls,
)
from candidate_line.telephony.app import CLOSED_OUTCOME
from candidate_line.tools.ledger import Ledger
from candidate_line.traces import TraceStore

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"


def _model(
    store: TraceStore, call: str, ms: int, model: str = HAIKU, asks: tuple[str, ...] = (), cached: int = 0
) -> None:
    meta: dict[str, object] = {
        "provider": "anthropic",
        "cached_input_tokens": cached,
        "cache_write_input_tokens": 0,
    }
    if asks:
        meta["tool_calls"] = list(asks)
    store.span(call, "model", model, ms=ms, tokens_in=1000, tokens_out=20, text="ok", meta=meta)


def _tool(store: TraceStore, call: str, name: str, text: str, error: bool = False) -> None:
    store.span(call, "tool", name, ms=3, text=text, meta={"args": {}, "keys": [], "is_error": error})


def _tier(store: TraceStore, call: str, tier: str = "1") -> None:
    store.span(call, "hook", "guard", text="clean", meta={"hits": []})
    store.span(call, "tier", tier, text="handled")


def _three_calls() -> TraceStore:
    """A phone call that books on its third turn after a superseded booking, a text call with a missed
    verification and a callback posted twice, and a text call whose booking the five-call cap took back."""
    store = TraceStore(":memory:")
    store.start_call("v1", "voice", caller="+15555550142", provider="anthropic")
    _model(store, "v1", 900, asks=("verify_caller",))
    _tool(store, "v1", "verify_caller", "verified ACME-3233")
    _model(store, "v1", 1100)
    _tier(store, "v1")
    store.span("v1", "speech", "polly", chars=40, meta={"first_audio_gap_ms": 1500})
    _model(store, "v1", 800, asks=("book_slot",))
    _tool(store, "v1", "book_slot", "booked S1105-0930, Thursday 5 November at 9:30 AM Central")
    _model(store, "v1", 1000)
    _tier(store, "v1")
    store.span("v1", "transcribe", "final", text="actually wait")
    store.span("v1", "hook", "superseded", text="taken back", meta={"undone": 1})
    _model(store, "v1", 700, asks=("book_slot",))
    _tool(store, "v1", "book_slot", "booked S1105-1000, Thursday 5 November at 10:00 AM Central")
    _model(store, "v1", 600)
    _tier(store, "v1")
    store.span("v1", "speech", "polly", chars=40, meta={"first_audio_gap_ms": 1900})
    store.end_call("v1", "3 turns, 0 barge-ins, 1 superseded")

    store.start_call("t1", "text", provider="anthropic", model=HAIKU)
    _model(store, "t1", 1000, asks=("verify_caller",), cached=2000)
    _tool(store, "t1", "verify_caller", "no match, 1 failed on this call")
    _tool(store, "t1", "request_callback", "callback recorded, best time not given")
    for duplicate in (False, True):
        meta: dict[str, object] = {"tool": "request_callback"}
        if duplicate:
            meta["duplicate"] = True
        store.span("t1", "escalation", "2", text="callback", meta=meta)
    _model(store, "t1", 1200)
    _tier(store, "t1", "2")
    store.span("t1", "speech", "spoken", text="The coordinator will call you back.", chars=36)

    store.start_call("t2", "text", provider="anthropic", model=SONNET)
    _model(store, "t2", 2000, SONNET, asks=("verify_caller",))
    _tool(store, "t2", "verify_caller", "verified ACME-1022")
    _model(store, "t2", 2000, SONNET, asks=("move_slot",))
    _tool(store, "t2", "move_slot", "move request recorded for S1109-1400, prefers -")
    store.span("t2", "escalation", "2", text="move", meta={"tool": "move_slot"})
    _model(store, "t2", 2000, SONNET, asks=("book_slot",))
    _tool(store, "t2", "book_slot", "booked S1106-0930, Friday 6 November at 9:30 AM Central")
    _model(store, "t2", 2000, SONNET, asks=("list_open_slots",))
    _tool(store, "t2", "list_open_slots", "2 open: S1106-1000, S1106-1400")
    _model(store, "t2", 2000, SONNET, asks=("list_open_slots",))
    _tier(store, "t2")
    store.span("t2", "escalation", "3", text="second miss", meta={"suggested_action": "read the trace"})
    return store


def _booked_ledger(path: Path) -> None:
    """Two bookings written by the real ledger, so the file has the shape the line writes."""
    ledger = Ledger(state_path=path, now=lambda: datetime(2026, 11, 4, 22, 10, tzinfo=UTC))
    ledger.book("ACME-3233", "S1105-0930", "v1")
    ledger.book("ACME-1022", "S1105-1000", "t2")


def test_three_calls_give_every_number_with_its_n(tmp_path: Path) -> None:
    store = _three_calls()
    state = tmp_path / "state.json"
    _booked_ledger(state)
    calls = read_calls(store)
    bookings = ledger_bookings(state)
    assert bookings is not None
    rows = {r.number: r for r in scorecard.scorecard(calls, bookings, invited_at(bookings), read_baseline())}

    assert (rows["calls taken"].value, rows["calls taken"].n) == ("1 voice, 2 text", "3 calls")
    assert rows["verified callers"].value == "2"
    # v1's superseded booking and t2's capped one are taken back; v1's third turn stands.
    assert rows["bookings made"].value == "1"
    assert rows["callback hand-offs"].value == "1" and rows["move hand-offs"].value == "1"
    # Thirteen model spans: eight on Haiku (median 950 ms), five on Sonnet at 2,000 ms.
    brain = rows["median brain time"]
    assert (brain.value, brain.n) == ("1,100 ms", "13 model spans") and brain.method.startswith(
        "worst 2,000 ms"
    )
    assert rows[f"  {HAIKU}"].value == "950 ms" and rows[f"  {SONNET}"].n == "5 model spans"
    gap = rows["median turn gap, phone"]
    assert (gap.value, gap.n) == ("1,700 ms", "2 turns") and "worst 1,900 ms" in gap.method
    # rates.py: Haiku 5.5 at (1000 x 0.10 + 20 x 0.50) per million = 0.00011 a span, cache reads at a tenth;
    # Sonnet 5.5 at (1000 x 2.00 + 20 x 10.00) per million = 0.0022 a span.
    costs = {c.call.call_id: call_cost_usd(c.spans) for c in calls}
    assert costs == {"v1": pytest.approx(0.00066), "t1": pytest.approx(0.00024), "t2": pytest.approx(0.011)}
    cost = rows["brain cost per call"]
    assert (cost.value, cost.n) == ("0.00397 USD", "3 priced calls") and "total 0.01190 USD" in cost.method
    # ACME-3233 invited 2026-10-29 10:10 UTC and ACME-1022 at 17:40 UTC, both booked 2026-11-04 22:10 UTC.
    line = rows["invite-to-booked, this line"]
    assert (line.value, line.n) == ("152.2 h", "2 bookings")
    assert (rows["invite-to-booked, baseline phone"].value, rows["invite-to-booked, baseline phone"].n) == (
        "29.4 h",
        "5 of 5 invites",
    )
    assert rows["invite-to-booked, baseline email"].n == "29 of 35 invites"
    assert all(r.method for r in rows.values())


def test_invite_to_booked_counts_a_booking_it_cannot_time() -> None:
    hours, skipped = invite_to_booked_hours(
        {"ACME-3233": "2026-11-04T22:10:00+00:00", "ACME-0000": "2026-11-04T22:10:00+00:00"},
        {"ACME-3233": "2026-10-29T04:10:00-06:00"},
    )
    assert hours == [156.0] and skipped == 1


def test_a_cap_take_back_and_a_superseded_turn_are_not_bookings() -> None:
    store = _three_calls()
    kept = {c.call.call_id: bookings_kept(c.spans) for c in read_calls(store)}
    assert kept == {"v1": 1, "t1": 0, "t2": 0}


def test_an_unpriced_model_and_a_zero_ms_span_are_left_out() -> None:
    store = TraceStore(":memory:")
    store.start_call("e1", "text", provider="echo", model="echo")
    _model(store, "e1", 0, model="echo")
    store.start_call("k1", "voice")
    store.span("k1", "kill", "switch", text="closed")
    rows = {r.number: r for r in scorecard.scorecard(read_calls(store), {}, {}, read_baseline())}
    assert rows["median brain time"].value == "none" and rows["median brain time"].n == "0 model spans"
    cost = rows["brain cost per call"]
    assert cost.value == "none" and "1 call with a model rates.py has no row for" in cost.method
    assert "1 call with no model span" in cost.method


def test_the_baseline_numbers_come_from_the_csv() -> None:
    baseline = read_baseline()
    assert len(baseline.hours["phone"]) == 5 and baseline.never["phone"] == 0
    assert len(baseline.hours["email"]) == 29 and baseline.never["email"] == 6
    assert sorted(baseline.hours["phone"])[2] == 29.4 and sorted(baseline.hours["email"])[14] == 27.5


def test_an_empty_store_prints_zeros_and_creates_no_file(tmp_path: Path) -> None:
    missing = tmp_path / "traces.sqlite"
    page = build(str(missing), None)
    assert not missing.exists()
    assert "synthetic data, synthetic baseline" in page and "no such file, so no calls" in page
    assert "0 voice, 0 text" in page and "0 model spans" in page and "0 turns" in page
    assert "in memory (STATE_PATH=:memory:), so no bookings" in page


def test_an_unreadable_ledger_is_named_and_never_moved(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    assert ledger_bookings(state) is None
    page = build(":memory:", state)
    assert "could not be read" in page
    assert state.read_text(encoding="utf-8") == "not json" and sorted(p.name for p in tmp_path.iterdir()) == [
        "state.json"
    ]


def test_the_page_names_no_caller(tmp_path: Path) -> None:
    path = tmp_path / "traces.sqlite"
    store = TraceStore(path)
    store.start_call("v9", "voice", caller="+15555550142")
    _model(store, "v9", 900)
    page = build(str(path), None)
    assert "5550142" not in page and "***-***-0142" not in page and "1 voice" in page


def test_main_reads_the_paths_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state.json"
    _booked_ledger(state)
    monkeypatch.setenv("TRACE_STORE_PATH", str(tmp_path / "none.sqlite"))
    monkeypatch.setenv("STATE_PATH", str(state))
    assert scorecard.main() == 0
    out = capsys.readouterr().out
    assert "invite-to-booked, this line" in out and "152.2 h" in out and "2 bookings" in out


def test_a_call_the_daily_cap_closed_is_counted_as_closed_and_not_as_taken() -> None:
    store = _three_calls()
    store.start_call("c1", "voice", caller="+15555550143")
    store.end_call("c1", CLOSED_OUTCOME)
    rows = {r.number: r for r in scorecard.scorecard(read_calls(store), {}, {}, read_baseline())}
    assert (rows["calls taken"].value, rows["calls taken"].n) == ("1 voice, 2 text", "4 calls")
    assert rows["calls closed by the daily cap"].value == "1"
