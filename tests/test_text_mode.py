from candidate_line.brain import EchoBrain
from candidate_line.hooks import NoHooks
from candidate_line.text_mode import repl
from candidate_line.traces.store import TraceStore


def test_repl_echoes_lines_and_handles_its_two_commands() -> None:
    out: list[str] = []
    repl(EchoBrain(), NoHooks(), ["hello", "", "/silence 7", "/quit", "never reached"], out.append)
    assert out[0].startswith("[echo echo] text mode")
    assert out[1] == "gus> hello"
    assert out[2].endswith("0 ms, 0 in, 0 out")
    assert out[3] == "(silence hook said nothing)"
    assert len(out) == 4


def test_text_mode_starts_and_ends_its_call_in_the_store_it_is_given() -> None:
    store = TraceStore(":memory:")
    out: list[str] = []
    ctx = repl(EchoBrain(), NoHooks(), ["hello", "/quit"], out.append, store=store)
    [call] = store.calls()
    assert call.call_id == ctx.call_id and call.channel == "text" and call.outcome == "1 turns"
    assert call.ended_at is not None
