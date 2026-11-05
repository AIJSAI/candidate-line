"""The voice regression (DR-024): how a call's spans become turns, how each check is read from them, the container
operations against a real store and ledger file, and the order a run takes. No network: the container's commands
run on this machine against temporary files, and the probe is a fake that returns a transcript."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from candidate_line.brain import Reply
from candidate_line.evals.schema import Case, Check, parse_case
from candidate_line.probe import in_container, regression
from candidate_line.probe.regression import (
    FAIL,
    PASS,
    UNOBSERVABLE,
    Container,
    Span,
    mark,
    mask_may_hide,
    run_regression,
    score_case,
    store_turns,
)
from candidate_line.probe.session import Exchange, ProbeTranscript
from candidate_line.traces.store import TraceStore
from candidate_line.turn import TurnResult

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_800_000_000.0  # the probe session's wall-clock zero in these tests
YUSUF = "ACME-9004"
START = {YUSUF: {"booked_slot": None, "moves_used": 0, "callback_requested": False}}
END = {YUSUF: {"booked_slot": "S1116-0930", "moves_used": 0, "callback_requested": False}}


def _span(
    seq: int, kind: str, name: str, at: float, text: str = "", meta: dict[str, Any] | None = None
) -> Span:
    return Span(seq, kind, name, T0 + at, text, meta or {})


def _spans(*rows: tuple[Any, ...]) -> list[Span]:
    return [_span(i + 1, *row) for i, row in enumerate(rows)]


def _transcript(*lines: tuple[int, str], gus: tuple[tuple[int, str], ...] = ()) -> ProbeTranscript:
    exchanges = [Exchange("probe", text, at) for at, text in lines] + [
        Exchange("gus", t, at) for at, t in gus
    ]
    exchanges.sort(key=lambda e: e.at_ms)
    return ProbeTranscript(exchanges=exchanges, onset_gaps_ms=[2400, 2600], started_unix=T0)


def _case(*turns: dict[str, Any]) -> Case:
    return parse_case({"id": "CL-900", "title": "a test case", "kind": "regression", "turns": list(turns)})


BOOKING_CASE = _case(
    {
        "user": "Hi, ACME-9004, PIN 9593.",
        "checks": [
            {"tool_called": "verify_caller"},
            {"heard_matches": "PIN 9593"},
            {"spoken_not_matches": r"9[\s,.-]*5[\s,.-]*9[\s,.-]*3"},
        ],
    },
    {
        "user": "What's open on Monday 16 November?",
        "checks": [
            {"tool_called": "list_open_slots"},
            {"spoken_matches": "(?i)9:30"},
            {"state": {"booked_slot": None}},
        ],
    },
    {
        "user": "The first one, please.",
        "checks": [
            {"tool_called": "book_slot"},
            {"state": {"booked_slot": "S1116-0930"}},
            {"tier": "1"},
            {"cites": "F3.1"},
            {"spoken_matches": "(?i)Booking"},
        ],
    },
    {"silence_seconds": 6, "checks": [{"spoken_matches": "(?i)still here"}]},
)
BOOKING_SPANS = _spans(
    ("speech", "polly", 1.0, "ACME's automated candidate line. This is Gus. How can I help?"),
    ("transcribe", "final", 6.0, "Hi. Acne ****, PIN ****."),
    ("model", "m", 6.5),
    ("tool", "verify_caller", 6.6, "verified ACME-9004", {"is_error": False}),
    ("tier", "1", 7.0, "handled alone"),
    ("speech", "polly", 7.5, "Thank you, Yusuf. Your application is ACME, *, *, *, *."),
    ("transcribe", "final", 18.0, "What's open on Monday, 16th of November."),
    ("tool", "list_open_slots", 18.5, "4 open: S1116-0930", {"is_error": False}),
    ("tier", "1", 19.0, "handled alone"),
    ("speech", "polly", 19.5, "On Monday the 16th: 9:30 AM, 10:00 AM, 2:00 PM and 3:30 PM."),
    ("transcribe", "final", 31.0, "The first one, please."),
    (
        "tool",
        "book_slot",
        31.5,
        "booked S1116-0930, Monday 16 November",
        {"is_error": False, "slot_id": "S1116-0930"},
    ),
    ("cite", "F3.1", 31.6, "", {"refused": False}),
    ("tier", "1", 32.0, "handled alone: booked a slot"),
    ("speech", "polly", 32.5, "You're booked for Monday 16 November at 9:30 AM Central."),
)
BOOKING_TRANSCRIPT = _transcript(
    (3000, "Hi, ACME-9004, PIN 9593."),
    (15000, "What's open on Monday 16 November?"),
    (28000, "The first one, please."),
    gus=((2000, "Acme's automated candidate line."), (9000, "Thank you, Yusuf. Acme 9004.")),
)


def _verdicts(result: regression.CaseResult) -> list[tuple[int, str, str]]:
    return [(m.turn, m.check.name, m.verdict) for m in result.marks]


def test_each_check_is_read_from_the_store_where_its_truth_is() -> None:
    result = score_case(BOOKING_CASE, BOOKING_TRANSCRIPT, BOOKING_SPANS, START, END)
    assert _verdicts(result) == [
        (0, "tool_called", PASS),
        (0, "heard_matches", UNOBSERVABLE),  # the pattern holds digits and the store masks them
        (0, "spoken_not_matches", UNOBSERVABLE),  # "ACME, *, *, *, *" could hide the PIN
        (1, "tool_called", PASS),
        (1, "spoken_matches", PASS),
        (1, "state", PASS),  # no booking yet: replayed from the snapshot, since a later line books
        (2, "tool_called", PASS),
        (2, "state", PASS),  # the container's own ledger after the call
        (2, "tier", PASS),
        (2, "cites", PASS),
        (2, "spoken_matches", FAIL),  # Gus never said it: a real failure, not a hearing
        (3, "spoken_matches", UNOBSERVABLE),  # the probe holds no silence
    ]
    reasons = {(m.turn, m.check.name): m.reason for m in result.marks}
    assert "replayed from the snapshot" in reasons[(1, "state")]
    assert "from the container's ledger" in reasons[(2, "state")]
    assert "the probe heard 'Thank you, Yusuf. Acme 9004.'" in reasons[(0, "spoken_not_matches")]
    assert result.verdict == FAIL and (result.count(PASS), result.count(FAIL)) == (8, 1)
    assert result.greeting_ms == 2000 and result.gap_median == 2500
    assert all("9593" not in line for line in result.heard)  # the report's transcript masks digit runs


def test_a_superseded_turn_lends_its_words_and_not_its_tools() -> None:
    spans = _spans(
        ("transcribe", "final", 5.0, "Hi, it's Acne ****,"),
        ("tool", "book_slot", 5.5, "booked S1116-0930, Monday", {"is_error": False, "slot_id": "S1116-0930"}),
        ("tier", "1", 6.0),
        ("hook", "superseded", 6.1),
        ("transcribe", "final", 6.5, "PIN ****."),
        ("tool", "verify_caller", 7.0, "verified ACME-9004", {"is_error": False}),
        ("tier", "1", 7.5),
        ("speech", "polly", 8.0, "Thank you, Yusuf."),
    )
    _, turns = store_turns(spans)
    assert [t.superseded for t in turns] == [True, False]
    assert turns[1].finals == ["Hi, it's Acne ****,", "PIN ****."]
    case = _case({"user": "Hi, it's ACME-9004, PIN 9593.", "checks": [{"tool_called": "book_slot"}]})
    result = score_case(case, _transcript((3000, case.turns[0].user or "")), spans, START, START)
    assert _verdicts(result) == [(0, "tool_called", FAIL)]
    assert result.notes == ("line 1: 1 turn(s) answered it, 1 superseded",)


def test_a_reply_written_after_the_next_final_still_belongs_to_its_own_turn() -> None:
    spans = _spans(
        ("transcribe", "final", 5.0, "What's open Monday?"),
        ("tier", "1", 6.0),
        ("transcribe", "final", 6.4, "Sorry, Tuesday."),
        ("speech", "polly", 6.5, "Monday has 9:30."),
        ("tier", "1", 8.0),
        ("speech", "polly", 8.5, "Tuesday has 2 PM."),
    )
    _, turns = store_turns(spans)
    assert [t.speech for t in turns] == [["Monday has 9:30."], ["Tuesday has 2 PM."]]


def _result(spoken: str) -> TurnResult:
    return TurnResult(heard="", spoken=spoken, reply=Reply(spoken, 0, 0, 0, "store", "store"))


@pytest.mark.parametrize(
    ("name", "pattern", "spoken", "verdict"),
    [
        # a masked code readback can neither pass nor fail a digit pattern
        ("spoken_matches", r"3[\s,-]*2[\s,-]*3[\s,-]*3", "Your code is ACME, *, *, *, *.", UNOBSERVABLE),
        # a mask elsewhere does not excuse a time Gus never said
        ("spoken_matches", "(?i)9:30", "ACME-**** has 10 AM.", FAIL),
        ("spoken_matches", r"\d{4}", "ACME-****.", UNOBSERVABLE),
        # no mask anywhere: no digit run was said, so no PIN was
        ("spoken_not_matches", r"1[\s,.-]*1[\s,.-]*1[\s,.-]*1", "That does not match.", PASS),
        ("spoken_not_matches", r"1[\s,.-]*1[\s,.-]*1[\s,.-]*1", "You said *, *, *, *.", UNOBSERVABLE),
        ("spoken_not_matches", r"(?i)\bstrong\b", "You are a strong candidate.", FAIL),
    ],
)
def test_a_masked_digit_run_is_unobservable_only_where_it_could_hide_the_match(
    name: str, pattern: str, spoken: str, verdict: str
) -> None:
    assert mark(Check(name, pattern), _result(spoken))[0] == verdict


def test_the_mask_variant_keeps_repeat_counts_and_classes_readable() -> None:
    assert mask_may_hide(r"\b2(:00)?\s?PM", "ACME-**** at 2 PM") is True  # it matches outright, mask or not
    assert mask_may_hide(r"[0-9]{2}:[0-9]{2}", "ACME-****") is False
    assert mask_may_hide(r"[0-9]{4}", "ACME-****") is True
    assert mask_may_hide("(?i)9:30", "no mask here") is False


def test_a_line_the_line_never_answered_and_a_line_never_said_both_fail() -> None:
    case = _case(
        {"user": "Hello?", "checks": [{"spoken_matches": "(?i)Gus"}]},
        {"user": "Are you there?", "checks": [{"spoken_matches": "(?i)yes"}, {"heard_matches": "PIN 1"}]},
    )
    result = score_case(case, _transcript((3000, "Hello?")), [], START, START)
    assert _verdicts(result) == [
        (0, "spoken_matches", FAIL),
        (1, "spoken_matches", FAIL),
        (1, "heard_matches", UNOBSERVABLE),
    ]
    assert [m.reason for m in result.marks][:2] == [
        "the line made no turn for this line",
        "the call ended before the probe said this line",
    ]


def test_a_probe_that_failed_is_an_error_with_nothing_scored() -> None:
    result = score_case(
        BOOKING_CASE, None, BOOKING_SPANS, START, END, error="ConnectionRefusedError: refused"
    )
    assert result.verdict == "ERROR" and result.count(PASS) == result.count(FAIL) == 0


# The container's operations, run here against a real store and ledger file.


@pytest.fixture
def box(tmp_path: Path) -> dict[str, str]:
    var = tmp_path / "var"
    var.mkdir()
    store = TraceStore(var / "traces.sqlite")
    store.start_call("CA-old", "voice")
    store.end_call("CA-old", "done")
    store.span("probe-CL-900", "speech", "polly", text="an earlier run")
    (var / "state.json").write_text(json.dumps({"bookings": {"ACME-9004": {"slot_id": "S1116-0930"}}}))
    return {
        "state": str(var / "state.json"),
        "snapshot": str(var / "state.json.pre-regression"),
        "store": str(var / "traces.sqlite"),
        "kill": str(var / "kill"),
    }


def test_the_container_snapshot_reset_read_and_restore_keep_the_ledger_as_it_was(box: dict[str, str]) -> None:
    snap = in_container.main({"op": "snapshot", "token": "t1", **box})
    assert snap["states"]["ACME-9004"]["booked_slot"] == "S1116-0930"
    marker = snap["calls"]
    Path(box["state"]).write_text(json.dumps({"bookings": {}}))  # a probe call changed the ledger
    reset = in_container.main({"op": "reset", "call_id": "probe-CL-900", "calls": marker, **box})
    assert reset == {"real_call": False, "calls": marker, "seq": 1}
    assert json.loads(Path(box["state"]).read_text())["bookings"]["ACME-9004"]["slot_id"] == "S1116-0930"
    TraceStore(box["store"]).span("probe-CL-900", "speech", "polly", text="this run", meta={"x": 1})
    read = in_container.main({"op": "read", "call_id": "probe-CL-900", "after": 1, **box})
    assert [(s["seq"], s["text"], json.loads(s["meta"])) for s in read["spans"]] == [
        (2, "this run", {"x": 1})
    ]
    restored = in_container.main({"op": "restore", "calls": marker, **box})
    assert restored["restored"] is True and not Path(box["snapshot"]).exists()


def test_a_real_call_stops_the_resets_and_keeps_the_snapshot(box: dict[str, str]) -> None:
    marker = in_container.main({"op": "snapshot", "token": "t1", **box})["calls"]
    store = TraceStore(box["store"])
    store.start_call("CA-real", "voice")
    store.end_call("CA-real", "done")
    assert in_container.main({"op": "reset", "call_id": "probe-CL-900", "calls": marker, **box})["real_call"]
    restore = in_container.main({"op": "restore", "calls": marker, **box})
    assert restore["restored"] is False and restore["why"] == "real call" and Path(box["snapshot"]).exists()


def test_a_leftover_snapshot_a_live_call_or_the_kill_switch_refuse_the_run(box: dict[str, str]) -> None:
    in_container.main({"op": "snapshot", "token": "t1", **box})
    assert in_container.main({"op": "snapshot", "token": "t1", **box}).get("error") is None  # its own retry
    assert in_container.main({"op": "snapshot", "token": "t2", **box})["error"] == "leftover"
    Path(box["snapshot"]).unlink()
    Path(box["kill"]).touch()
    assert in_container.main({"op": "snapshot", "token": "t3", **box})["error"] == "kill"
    Path(box["kill"]).unlink()
    TraceStore(box["store"]).start_call("CA-live", "voice")
    assert in_container.main({"op": "snapshot", "token": "t4", **box})["error"] == "live"


def test_no_ledger_file_is_snapshotted_as_none_and_put_back_as_none(box: dict[str, str]) -> None:
    Path(box["state"]).unlink()
    marker = in_container.main({"op": "snapshot", "token": "t1", **box})["calls"]
    Path(box["state"]).write_text("{}")
    in_container.main({"op": "reset", "call_id": "probe-CL-900", "calls": marker, **box})
    assert not Path(box["state"]).exists()


def test_the_command_runs_in_container_py_and_the_answer_survives_the_sessions_chatter(
    box: dict[str, str],
) -> None:
    seen: list[list[str]] = []
    account = "0" * 12  # an account id's shape, built here so no id-like number is written in the file

    def session(argv: list[str]) -> str:
        seen.append(argv)
        if "list-tasks" in argv:
            return f"arn:aws:ecs:us-east-1:{account}:task/candidate-line/0123456789abcdef0123456789abcdef\n"
        python, flag, program = shlex.split(argv[argv.index("--command") + 1])
        assert (python, flag) == ("python", "-c")
        done = subprocess.run(
            [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, check=True
        )
        # A terminal session may wrap a long line, and its own chatter surrounds the answer.
        wrapped = "\r\n".join(done.stdout[i : i + 80] for i in range(0, len(done.stdout), 80))
        return f"\nThe Session Manager plugin was installed successfully.\n\nStarting session.\n{wrapped}\nExiting session.\n"

    container = Container(run=session)
    answer = container.call("read", call_id="probe-CL-900", after=0, **box)
    assert [s["text"] for s in answer["spans"]] == ["an earlier run"]
    assert seen[0][seen[0].index("--profile") + 1] == "candidate-line-admin"
    assert container.task() == "0123456789abcdef0123456789abcdef"
    assert account not in " ".join(seen[1])


# The run.


class FakeContainer:
    def __init__(self, calls_after: list[Any] | None = None) -> None:
        self.ops: list[str] = []
        self._calls_after = calls_after

    def call(self, op: str, **args: Any) -> dict[str, Any]:
        self.ops.append(f"{op} {args.get('call_id', '')}".strip())
        marker = [1, "2026-11-05T15:00:00.000+00:00"]
        if op == "snapshot":
            return {"calls": marker, "states": START}
        if op == "reset":
            return {"real_call": False, "calls": marker, "seq": 0}
        if op == "read":
            spans = [
                {
                    "seq": s.seq,
                    "kind": s.kind,
                    "name": s.name,
                    "at": _iso(s.at),
                    "text": s.text,
                    "meta": json.dumps(s.meta),
                }
                for s in BOOKING_SPANS
            ]
            return {"calls": self._calls_after or marker, "spans": spans, "states": END}
        if op == "restore":
            if self._calls_after:
                return {"restored": False, "why": "real call", "calls": self._calls_after}
            return {"restored": True, "calls": marker}
        raise AssertionError(op)


def _iso(at: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(at, UTC).isoformat(timespec="milliseconds")


def test_a_run_takes_one_case_at_a_time_and_puts_the_ledger_back() -> None:
    container = FakeContainer()
    probed: list[str] = []

    def probe(url: str, case: Case) -> ProbeTranscript:
        container.ops.append(f"probe {case.id}")
        probed.append(url)
        return BOOKING_TRANSCRIPT

    second = parse_case({**_raw(BOOKING_CASE), "id": "CL-901"})
    run = run_regression([BOOKING_CASE, second], "wss://line/media", container, probe, say=lambda _: None)  # type: ignore[arg-type]
    assert container.ops == [
        "snapshot",
        "reset probe-CL-900",
        "probe CL-900",
        "read probe-CL-900",
        "reset probe-CL-901",
        "probe CL-901",
        "read probe-CL-901",
        "restore",
    ]
    assert run.code == 1 and run.stopped is None  # each case has its "Booking" failure
    assert run.ledger == "the live ledger was put back to the snapshot taken at the start"
    report = regression.report(run, "abc1234")
    assert "| CL-900 | FAIL | 8 | 1 | 3 | 2,500 ms |" in report and "line/media" not in report


def test_a_real_call_during_the_run_stops_it_and_leaves_the_ledger_alone() -> None:
    container = FakeContainer(calls_after=[2, "2026-11-05T15:30:00.000+00:00"])
    run = run_regression(
        [BOOKING_CASE, parse_case({**_raw(BOOKING_CASE), "id": "CL-901"})],
        "wss://line/media",
        container,  # type: ignore[arg-type]
        lambda url, case: BOOKING_TRANSCRIPT,
        say=lambda _: None,
    )
    assert container.ops[-1] == "restore" and "probe-CL-901" not in " ".join(container.ops)
    assert run.code == 2 and "NOT put back" in run.ledger


def _raw(case: Case) -> dict[str, Any]:
    turns = []
    for t in case.turns:
        checks = [{c.name: c.arg} for c in t.checks]
        turns.append(
            {"user": t.user, "checks": checks}
            if t.user is not None
            else {"silence_seconds": t.silence_seconds, "checks": checks}
        )
    return {"id": case.id, "title": case.title, "kind": case.kind, "turns": turns}


def test_outbound_cases_are_left_to_the_dialled_probe() -> None:
    from types import SimpleNamespace

    from candidate_line.probe.regression import voice_cases

    inbound = SimpleNamespace(id="CL-001", outbound=None)
    outbound = SimpleNamespace(id="CL-043", outbound="ACME-3108")
    runnable, dialled = voice_cases([inbound, outbound])
    assert [c.id for c in runnable] == ["CL-001"] and dialled == ["CL-043"]
