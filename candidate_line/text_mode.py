"""Text mode: the line without a phone. `make text`.

Why it exists: the failure drill (kill the tunnel, keep talking), a check that costs no call, and the eval
runner's harness. It runs the same brain and the same hooks as the voice path; only the ears and mouth differ.
Commands: `/silence N` runs the silence hook as if N seconds passed; `/quit` ends it.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable, Iterable

from candidate_line.brain import Brain, make_brain
from candidate_line.hooks import Hooks, default_hooks
from candidate_line.persona import PLACEHOLDER_SYSTEM
from candidate_line.settings import Settings
from candidate_line.traces.store import DEFAULT_PATH, TraceStore
from candidate_line.turn import TurnContext, run_silence, run_turn


def repl(
    brain: Brain,
    hooks: Hooks,
    lines: Iterable[str],
    write: Callable[[str], None],
    system: str = PLACEHOLDER_SYSTEM,
    store: TraceStore | None = None,
) -> TurnContext:
    """Feeds `lines` through the turn loop and writes each answer with its provider, model and latency."""
    ctx = TurnContext(call_id=f"text-{uuid.uuid4().hex[:8]}", channel="text", system=system, store=store)
    if store is not None:
        store.start_call(ctx.call_id, "text", provider=brain.name, model=brain.model)
    turns = 0
    write(f"[{brain.name} {brain.model}] text mode, call {ctx.call_id}. /silence N, /quit.")
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line == "/quit":
            break
        if line.startswith("/silence"):
            parts = line.split()
            seconds = float(parts[1]) if len(parts) > 1 else 5.0
            said = run_silence(hooks, ctx, seconds)
            write(f"gus> {said}" if said else "(silence hook said nothing)")
            continue
        result = run_turn(brain, hooks, ctx, line)
        turns += 1
        write(f"gus> {result.spoken}" if result.spoken else "(gus said nothing)")
        write(
            f"     {result.reply.latency_ms} ms, {result.reply.input_tokens} in, {result.reply.output_tokens} out"
        )
    if store is not None:
        store.end_call(ctx.call_id, f"{turns} turns")
    return ctx


def main() -> int:
    settings = Settings.from_env()
    brain = make_brain(settings)
    try:
        store = TraceStore(settings.trace_store_path or DEFAULT_PATH)
        repl(
            brain,
            default_hooks(),
            sys.stdin,
            lambda s: print(s, flush=True),
            system=settings.system_prompt(),
            store=store,
        )
    except Exception as error:  # noqa: BLE001  (a closed quota or a missing key is one line, not a traceback)
        print(f"{brain.name} {brain.model} failed: {error}", file=sys.stderr)
        print(
            "Switch with BRAIN_PROVIDER=anthropic|bedrock|echo or BEDROCK_MODEL_ID=... (DR-003).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
