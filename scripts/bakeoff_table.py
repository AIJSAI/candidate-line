"""Prints DR-001's table from the bake-off CSV: per arm and per method, the median and worst turn gap with n,
and per case whether any check failed. Run: `uv run python scripts/bakeoff_table.py [bakeoff/2026-11-01.csv]`.

A row's `gap_ms` may be empty (the probe's ears heard nothing on that turn); those rows count for the words, not
the gap. The "probe" method is the probe's own clock, both phone legs included; "recording" is the method of
record (DR-001). Nothing here decides; the decision text is written by hand from these numbers.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

UNANSWERED_MS = 6000  # past this the probe gave up waiting; the row is a miss, not a gap


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("bakeoff/2026-11-01.csv")
    rows = list(csv.DictReader(path.open()))
    gaps: dict[tuple[str, str], list[int]] = defaultdict(list)
    calls: dict[str, set[str]] = defaultdict(set)
    hits: dict[str, int] = defaultdict(int)
    unanswered: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        calls[r["arm"]].add(r["call"])
        if r["gap_ms"].strip():
            gap = int(float(r["gap_ms"]))
            if gap > UNANSWERED_MS:
                unanswered[(r["arm"], r["method"])] += 1  # no reply inside the window: not a turn gap
            else:
                gaps[(r["arm"], r["method"])].append(gap)
        if r["probe_hit"].strip():
            hits[r["arm"]] += 1
    print(f"{'arm':4s} {'method':10s} {'n turns':8s} {'median ms':10s} {'worst ms':9s} calls")
    for (arm, method), values in sorted(gaps.items()):
        print(
            f"{arm:4s} {method:10s} {len(values):<8d} {statistics.median(values):<10.0f} {max(values):<9d} {len(calls[arm])}"
        )
    for arm in sorted(calls):
        misses = {m: n for (a, m), n in unanswered.items() if a == arm}
        print(
            f"arm {arm}: {len(calls[arm])} calls, probe sentences hit: {hits[arm]}, unanswered turns by method: {misses or 'none'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
