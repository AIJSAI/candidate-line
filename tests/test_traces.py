import pytest
from fastapi.testclient import TestClient

from candidate_line.traces import TraceStore, mask_number
from candidate_line.traces.cockpit import create_cockpit


def test_mask_keeps_four_digits_at_most() -> None:
    assert mask_number("+1 (402) 555-0142") == "***-***-0142"
    assert mask_number("+15555550100") == "***-***-0100"
    assert mask_number("12") == "***"
    assert mask_number(None) is None


def test_the_store_masks_the_caller_before_writing() -> None:
    store = TraceStore(":memory:")
    store.start_call("c1", "voice", caller="+15555550100", provider="bedrock", model="haiku")
    row = store.calls()[0]
    assert row.caller_masked == "***-***-0100"
    assert "5555550100" not in repr(row)


def test_spans_number_in_order_and_refuse_audio_and_unknown_kinds() -> None:
    store = TraceStore(":memory:")
    store.start_call("c1", "text")
    assert (
        store.span("c1", "model", "haiku", ms=612, tokens_in=170, tokens_out=24, text="Tuesday at ten.") == 1
    )
    assert store.span("c1", "speech", "polly", ms=240, chars=16) == 2
    with pytest.raises(TypeError):
        store.span("c1", "speech", "polly", text=b"\x00\x01")
    with pytest.raises(ValueError):
        store.span("c1", "audio", "x")
    spans = store.spans("c1")
    assert [s.seq for s in spans] == [1, 2] and spans[0].text == "Tuesday at ten."
    assert store.calls()[0].model_ms == 612


def test_cockpit_lists_calls_escapes_text_and_logs_a_reply() -> None:
    store = TraceStore(":memory:")
    store.start_call("c1", "voice", caller="+15555550100")
    store.span("c1", "model", "haiku", text="<script>alert(1)</script>")
    eid = store.add_escalation("c1", "notify", "second move asked", "call back within the hour", "slack")
    client = TestClient(create_cockpit(store))
    home = client.get("/")
    assert home.status_code == 200 and "***-***-0100" in home.text and "5555550100" not in home.text
    detail = client.get("/calls/c1")
    assert "&lt;script&gt;" in detail.text and "<script>alert" not in detail.text
    assert "Log reply" in detail.text
    done = client.post(
        f"/escalations/{eid}/reply", data={"reply": "called them", "by": "Sam"}, follow_redirects=True
    )
    assert done.status_code == 200 and "called them" in done.text and "Log reply" not in done.text
    assert client.get("/calls/nope").status_code == 404
    assert client.post("/escalations/999/reply", data={"reply": "x", "by": "y"}).status_code == 404


def test_empty_cockpit_says_so() -> None:
    assert "No calls yet" in TestClient(create_cockpit(TraceStore(":memory:"))).get("/").text


def test_trace_cli_prints_the_latest_call(monkeypatch, capsys) -> None:
    from candidate_line.traces import cli

    store = TraceStore(":memory:")
    store.start_call("c9", "voice", caller="+15555550199")
    store.span("c9", "model", "haiku", ms=500, text="hello")
    monkeypatch.setattr(
        cli, "TraceStore", lambda path: store
    )  # the path Settings names; the test keeps its own store
    assert cli.main(["last"]) == 0
    out = capsys.readouterr().out
    assert "call c9" in out and "***-***-0199" in out and "model      haiku" in out and "hello" in out


def test_bytes_in_the_name_or_the_metadata_or_a_memoryview_are_refused() -> None:
    import pytest

    store = TraceStore(":memory:")
    store.start_call("CA1", "voice")
    with pytest.raises(TypeError):
        store.span("CA1", "speech", "spoken", text=memoryview(b"\x00\x01"))
    with pytest.raises(TypeError):
        store.span("CA1", "speech", b"spoken")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.span("CA1", "speech", "spoken", meta={"audio": {"frames": [b"\xff"]}})
    assert store.spans("CA1") == []


def test_a_meta_key_that_names_a_pin_is_stored_masked_at_any_depth() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA2", "text")
    meta = {
        "pin": "9593",
        "args": {"code": "ACME-9004", "PIN": "1234"},
        "calls": [{"caller_pin": 4321}],
        "slot": "S1105-0930",
    }
    store.span("CA2", "tool", "verify_caller", text="verified", meta=meta)
    [span] = store.spans("CA2")
    assert span.meta == {
        "pin": "****",
        "args": {"code": "ACME-9004", "PIN": "****"},
        "calls": [{"caller_pin": "****"}],
        "slot": "S1105-0930",
    }
    assert not any(pin in repr(span) for pin in ("9593", "1234", "4321"))
    assert meta["pin"] == "9593"  # the caller's own dict is left as it was


def test_one_call_is_looked_up_by_id_and_an_unknown_id_is_none() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA3", "voice", caller="+15555550133", provider="anthropic", model="haiku")
    store.span("CA3", "model", "haiku", ms=400)
    store.start_call("CA4", "text")
    row = store.call("CA3")
    assert row is not None and row.call_id == "CA3" and row.caller_masked == "***-***-0133"
    assert row.span_count == 1 and row.model_ms == 400  # the same columns as the list view
    assert row == next(r for r in store.calls() if r.call_id == "CA3")
    assert store.call("nope") is None
