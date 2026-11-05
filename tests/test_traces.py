import re

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


def test_the_list_view_shows_the_tier_of_each_call_s_last_tier_span() -> None:
    store = TraceStore(":memory:")
    store.start_call("CA5", "voice")
    store.span("CA5", "tier", "1", text="handled alone: booked a slot")
    store.span("CA5", "tier", "2", text="a callback request went to the coordinator")
    store.start_call("CA6", "text")
    assert store.call("CA5").tier == "2" and store.call("CA6").tier is None
    home = TestClient(create_cockpit(store)).get("/").text
    assert "<th class='num'>Tier</th>" in home and "<td class='num'>2</td>" in home and "none yet" in home


# The applicant pages (DR-025 section 16), over a state file the real ledger writes.

from datetime import UTC, datetime, timedelta
from pathlib import Path

from candidate_line.tools.ledger import Ledger, derive_key, number_hmac

_ROOT = "a synthetic signing key for the tests only"
_NUMBER = "+15555550142"  # fictional, 555-01xx
_NOW = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
_CONSENT = {
    "version": "consent-2026-11-05",
    "accepted": True,
    "at": "2026-11-05T15:58:00+00:00",
    "source": "careers-form",
}


def _nonce(n: int) -> str:
    return f"cockpit-nonce-{n:02d}-abcdefghijklmnop"


def _screened_state(path: Path) -> dict[str, str]:
    """Four intake applications and two fixtures with answers: a not-met screen with a hand-off promised, a met
    screen that booked, one off the allow-list, one without consent."""
    clock = {"at": _NOW}
    ledger = Ledger(state_path=path, now=lambda: clock["at"], pin_key=derive_key(_ROOT, "pin"))
    hashed = number_hmac(derive_key(_ROOT, "number"), _NUMBER)

    def apply(n: int, name: str, **extra: object) -> str:
        fields = {
            "first_name": name,
            "role": "care-aide",
            "zone": "America/Chicago",
            "pin": "7193",
            "consent": _CONSENT,
            "number_hmac": hashed,
            "number_masked": "***-***-0142",
            "nonce": _nonce(n),
        }
        return ledger.add_application(**(fields | extra)).code  # type: ignore[arg-type]

    codes = {"ama": apply(1, "Ama")}
    clock["at"] = _NOW + timedelta(minutes=1)
    codes["off"] = apply(2, "Kofi", not_dialled="not_allowed", number_hmac=None)
    clock["at"] = _NOW + timedelta(minutes=2)
    codes["none"] = apply(3, "Efua", consent=_CONSENT | {"accepted": False}, not_dialled="no_consent")
    dial = ledger.schedule_dial(codes["ama"], 1, _NOW + timedelta(minutes=2))
    ledger.claim_due_dial(_NOW + timedelta(minutes=2), 20, lambda d, a: True)
    ledger.update_dial(
        dial["dial_id"], status="done", call_sid="CA-ama", outcome="screened", answered_by="human"
    )
    answers = {
        "q1": ("no", "No, I don't drive, PIN 7 1 9 3"),
        "q2": ("both", "both"),
        "q3": ("30", "about thirty"),
    }
    answers |= {"q4": ("yes", "yes"), "q5": ("declined", "rather not say")}
    for q, (value, heard) in answers.items():
        ledger.record_answer(codes["ama"], q, value, heard, "CA-ama")
    ledger.set_screen(codes["ama"], "not_met", "CA-ama", "2026-11-06T22:05:00+00:00")
    for q, value in {"q1": "yes", "q2": "evening", "q3": "yes", "q4": "2", "q5": "yes"}.items():
        ledger.record_answer("ACME-2609", q, value, f"said {value}", "CA-ines")
    ledger.set_screen("ACME-2609", "met", "CA-ines", None)
    ledger.book("ACME-2609", "S1105-1100", "CA-ines")
    return codes


def _cockpit(
    tmp_path: Path, store: TraceStore | None = None
) -> tuple[TestClient, TraceStore, dict[str, str]]:
    state = tmp_path / "state.json"
    codes = _screened_state(state)
    store = store or TraceStore(":memory:")
    app = create_cockpit(store, state_path=state, now=lambda: _NOW + timedelta(minutes=30))
    return TestClient(app), store, codes


def test_the_applicant_list_is_in_arrival_order_with_the_line_s_status_in_words(tmp_path: Path) -> None:
    client, _, codes = _cockpit(tmp_path)
    page = client.get("/applicants")
    assert page.status_code == 200
    order = re.findall(r"/applicants/(ACME-\d{4})'", page.text)
    # The six fixtures arrived on 4 November; the three intake applications on the 5th, a minute apart.
    assert order[-3:] == [codes["ama"], codes["off"], codes["none"]] and len(order) == 9
    assert order[:6] == ["ACME-3108", "ACME-3782", "ACME-3474", "ACME-7720", "ACME-2609", "ACME-7941"]
    text = page.text
    assert "not dialled: number not on the allow-list" in text and "not dialled: no consent" in text
    assert "recruiter call promised by Fri 6 Nov 2026, 4:05 PM Central" in text
    assert "booked: Thursday 5 November at 11:00 AM Central" in text and "no dial scheduled" in text
    # No column, colour or count by answer: no answer value or spoken answer is on the list.
    for absent in ("skipped", "30 hours a week", "evening", "not clear", "<select", "sort", "class='pill"):
        assert absent not in text
    assert "5555550142" not in text


def test_the_applicant_page_shows_each_question_what_it_asks_for_and_why_beside_the_answer(
    tmp_path: Path,
) -> None:
    client, _, codes = _cockpit(tmp_path)
    page = client.get(f"/applicants/{codes['ama']}").text
    for words in (
        "Do you hold a valid driver&#x27;s licence?",
        "a valid driver&#x27;s licence",
        "Aides drive between clients&#x27; homes on every shift.",
        "at least 20 hours a week",
        "Each client&#x27;s visits are scheduled in blocks of 20 hours a week or more.",
        "<td>30 hours a week</td>",
        "<td>skipped</td>",
        "<td>both</td>",
        "rather not say",
    ):
        assert words in page, words
    assert "7 1 9 3" not in page and "7193" not in page and "PIN ****" in page
    assert "***-***-0142" in page and "5555550142" not in page
    assert "promised a recruiter call by Fri 6 Nov 2026, 4:05 PM Central" in page
    lowered = page.lower()
    for verdict in ("passed", "failed", "qualif", "reject", "not met", "unmet", "eligib"):
        assert verdict not in lowered, verdict
    assert (
        "<a href='/calls/CA-ama'>" in page
        and "I read the answers" in page
        and "I called the applicant back" in page
    )
    booked = client.get("/applicants/ACME-2609").text
    assert "The line booked an interview: Thursday 5 November at 11:00 AM Central." in booked
    assert "<td>evening</td>" in booked and "<td>2 weeks</td>" in booked
    waiting = client.get("/applicants/ACME-3108").text
    assert (
        "No answers recorded yet." in waiting
        and "not asked yet" in waiting
        and "No screening call yet" in waiting
    )


def test_the_read_and_called_back_forms_write_their_spans_on_the_screening_call(tmp_path: Path) -> None:
    client, store, codes = _cockpit(tmp_path)
    store.start_call("CA-ama", "outbound", caller=_NUMBER)
    eid = store.add_escalation(
        "CA-ama",
        "2",
        f"screening hand-off from {codes['ama']} (Ama): Home Care Aide; promised",
        "read",
        "sns",
    )
    opened = (_NOW + timedelta(minutes=27)).isoformat()
    done = client.post(
        f"/applicants/{codes['ama']}/read", data={"by": "Sam", "opened_at": opened}, follow_redirects=False
    )
    assert done.status_code == 303 and done.headers["location"] == f"/applicants/{codes['ama']}"
    back = client.post(f"/applicants/{codes['ama']}/called-back", data={"by": "Sam"}, follow_redirects=False)
    assert back.status_code == 303
    spans = {s.name: s for s in store.spans("CA-ama") if s.kind == "hook"}
    read = spans["read"].meta
    assert read == {"code": codes["ama"], "by": "Sam", "opened_at": opened, "read_seconds": 180}
    assert spans["called_back"].meta == {
        "code": codes["ama"],
        "by": "Sam",
        "called_at": "2026-11-05T16:30:00+00:00",
    }
    [hand_off] = [e for e in store.escalations("CA-ama") if e.id == eid]
    assert hand_off.reply == "called the applicant back" and hand_off.replied_by == "Sam"
    # A page left open all night is capped at an hour; a missing name or an applicant with no call is refused.
    client.post(
        f"/applicants/{codes['ama']}/read", data={"by": "Sam", "opened_at": "2026-11-04T00:00:00+00:00"}
    )
    assert max(s.meta["read_seconds"] for s in store.spans("CA-ama") if s.name == "read") == 3600
    assert (
        client.post(f"/applicants/{codes['ama']}/read", data={"by": " ", "opened_at": opened}).status_code
        == 422
    )
    assert (
        client.post("/applicants/ACME-3108/read", data={"by": "Sam", "opened_at": opened}).status_code == 422
    )
    assert client.post("/applicants/ACME-3108/called-back", data={"by": "Sam"}).status_code == 422


def test_the_applicant_pages_read_the_file_without_the_ledger_and_never_move_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candidate_line.tools import ledger as ledger_module

    client, _, codes = _cockpit(tmp_path)

    def no_ledger(*args: object, **kwargs: object) -> None:
        raise AssertionError("the cockpit opened a Ledger")

    monkeypatch.setattr(ledger_module.Ledger, "__init__", no_ledger)
    assert client.get("/applicants").status_code == 200
    assert client.get(f"/applicants/{codes['ama']}").status_code == 200
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    assert "could not be read" in client.get("/applicants").text
    assert client.get(f"/applicants/{codes['ama']}").status_code == 503
    assert state.read_text(encoding="utf-8") == "not json"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("state.json")) == [
        "state.json",
        "state.json.lock",
    ]


def test_an_unknown_or_malformed_code_is_404_and_a_removed_application_is_gone(tmp_path: Path) -> None:
    client, _, codes = _cockpit(tmp_path)
    for path in (
        "/applicants/ACME-0001",
        "/applicants/..%2Fetc",
        "/applicants/acme-3108",
        "/applicants/ACME-31080",
    ):
        assert client.get(path).status_code == 404, path
    Ledger(state_path=tmp_path / "state.json", now=lambda: _NOW).forget(codes["off"])
    assert codes["off"] not in client.get("/applicants").text
    assert client.get(f"/applicants/{codes['off']}").status_code == 404


def test_the_applicant_pages_escape_what_the_file_holds(tmp_path: Path) -> None:
    import json

    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "applications": {
                    "ACME-0101": {
                        "code": "ACME-0101",
                        "first_name": "<script>alert(1)</script>",
                        "role": "care-aide",
                        "received_at": "2026-11-05T16:00:00+00:00",
                        "consent": {"version": "consent-2026-11-05", "accepted": True},
                        "not_dialled": None,
                    }
                },
                "answers": {"ACME-0101": {"by_question": {"q1": {"value": "yes", "heard": "<b>yes</b>"}}}},
            }
        )
    )
    client = TestClient(create_cockpit(TraceStore(":memory:"), state_path=state))
    for path in ("/applicants", "/applicants/ACME-0101"):
        text = client.get(path).text
        assert "<script>alert" not in text and "&lt;script&gt;" in text and "<b>yes" not in text
