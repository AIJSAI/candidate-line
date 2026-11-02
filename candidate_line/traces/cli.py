"""`make trace last`: the latest call's spans in the terminal, for the room's projector when the cockpit is not open."""

from __future__ import annotations

import sys

from candidate_line.traces.store import TraceStore


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    store = TraceStore()
    calls = store.calls(limit=1)
    if not calls:
        print("no calls in the trace store yet (the spans are written live from the turn loop, DR-012)")
        return 0
    call = calls[0]
    if args and args[0] != "last":
        call = next((c for c in store.calls(limit=1000) if c.call_id == args[0]), call)
    print(
        f"call {call.call_id} ({call.channel}) started {call.started_at} caller {call.caller_masked or '-'} brain {call.provider or '-'} {call.model or '-'} outcome {call.outcome or '-'}"
    )
    for s in store.spans(call.call_id):
        numbers = " ".join(
            f"{label} {value}"
            for label, value in (
                ("ms", s.ms),
                ("in", s.tokens_in),
                ("out", s.tokens_out),
                ("chars", s.chars),
                ("s", s.seconds),
            )
            if value is not None
        )
        print(f"  {s.seq:>3} {s.kind:<10} {s.name:<18} {numbers:<32} {s.text or ''}")
    for e in store.escalations(call.call_id):
        print(
            f"  escalation #{e.id} {e.tier}: {e.reason} -> {e.suggested_action} [{e.channel} {'posted' if e.posted_at else e.post_error or 'pending'}] reply: {e.reply or '-'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
