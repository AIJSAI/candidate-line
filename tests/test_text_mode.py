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


class CallEndRecorder(NoHooks):
    """Records each call-end hook with whether the store had already recorded the end at that moment."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store
        self.seen: list[tuple[str, str | None, bool]] = []

    def on_call_end(self, ctx, outcome):
        row = self.store.call(ctx.call_id)
        self.seen.append((ctx.call_id, outcome, row is not None and row.ended_at is not None))


def test_text_mode_runs_the_call_end_hook_once_just_before_the_store_ends_the_call() -> None:
    store = TraceStore(":memory:")
    hooks = CallEndRecorder(store)
    ctx = repl(EchoBrain(), hooks, ["hello", "again", "/quit"], [].append, store=store)
    assert hooks.seen == [(ctx.call_id, "2 turns", False)]  # the store had not ended the call yet
    assert store.call(ctx.call_id).ended_at is not None


def test_a_call_end_hook_that_raises_never_breaks_the_end_of_a_text_call(caplog) -> None:
    class Broken(NoHooks):
        def on_call_end(self, ctx, outcome):
            raise RuntimeError("summary job down")

    store = TraceStore(":memory:")
    ctx = repl(EchoBrain(), Broken(), ["hello", "/quit"], [].append, store=store)
    assert store.call(ctx.call_id).outcome == "1 turns"
    assert any("on_call_end failed" in r.getMessage() for r in caplog.records)


def test_a_silence_hook_that_asks_for_the_hang_up_ends_the_text_session() -> None:
    class Holding(NoHooks):
        def on_silence(self, ctx, seconds):
            ctx.data["hang_up"] = True
            return "I'll let you go. Call back any time."

    out: list[str] = []
    repl(EchoBrain(), Holding(), ["/silence 30", "never reached"], out.append)
    assert out[1:] == ["gus> I'll let you go. Call back any time.", "(gus hung up)"]
