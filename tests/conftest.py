"""Every test traces in memory. A test that builds the phone app, text mode or the eval runner without naming a
store path would otherwise open the room's var/traces.sqlite and leave a call there, and `make trace last`
after `make test` would show that call instead of the room's (card 03's dry run, 2026-11-03)."""

import pytest

from candidate_line import text_mode
from candidate_line.evals import runner
from candidate_line.telephony import app


@pytest.fixture(autouse=True)
def _trace_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "DEFAULT_PATH", ":memory:")
    monkeypatch.setattr(text_mode, "DEFAULT_PATH", ":memory:")
    monkeypatch.setattr(runner, "EVAL_DEFAULT_PATH", ":memory:")
    monkeypatch.setenv("TRACE_STORE_PATH", ":memory:")
    monkeypatch.setenv("EVAL_TRACE_STORE_PATH", ":memory:")
