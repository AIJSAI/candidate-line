"""Writes the bake-off's case files from `bakeoff/probes.yaml` and the five scripted scenarios (DR-001, DR-011).

Run from the repository root: `uv run python scripts/make_bakeoff_cases.py`. The ten probe cases each open
with one ordinary line, then ask the probe question; the check is the `never` pattern on what Gus says. The
five scenario cases walk the persona's four facts and three slots. Synthetic throughout; the candidate codes
are the persona's example shape, not rows of data/candidates.yaml.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bakeoff" / "cases"

SCENARIOS = [
    {
        "id": "s1-first-round",
        "title": "what the first round is; Gus names the section",
        "turns": [
            {
                "user": "Hi, I got an invite. What should I expect in the first round?",
                "checks": [{"spoken_matches": "(?i)thirty|30|video"}],
            },
            {
                "user": "Is there a coding exercise?",
                "checks": [{"spoken_not_matches": "(?i)\\byes\\b.*coding"}],
            },
            {"user": "Thanks, that is all.", "checks": []},
        ],
    },
    {
        "id": "s2-book-a-slot",
        "title": "book an open slot with a code and a PIN",
        "turns": [
            {
                "user": "I would like to book my first round. My code is ACME four eight two one.",
                "checks": [],
            },
            {"user": "My PIN is one two three four.", "checks": []},
            {"user": "Thursday at nine thirty please.", "checks": [{"spoken_matches": "(?i)thursday"}]},
            {"user": "Yes, confirmed. Goodbye.", "checks": []},
        ],
    },
    {
        "id": "s3-move-once",
        "title": "move a slot once without a reason",
        "turns": [
            {
                "user": "I need to move my interview. Code ACME four eight two one, PIN one two three four.",
                "checks": [],
            },
            {"user": "Can I take Tuesday at two instead?", "checks": [{"spoken_matches": "(?i)tuesday"}]},
            {
                "user": "No reason, something came up.",
                "checks": [{"spoken_not_matches": "(?i)why|reason required"}],
            },
        ],
    },
    {
        "id": "s4-second-move",
        "title": "a second move goes to the coordinator",
        "turns": [
            {
                "user": "I already moved my slot once and I need to move it again. Code ACME four eight two one, PIN one two three four.",
                "checks": [],
            },
            {"user": "Can you just move it for me?", "checks": [{"spoken_matches": "(?i)coordinator"}]},
        ],
    },
    {
        "id": "s5-callback",
        "title": "a question the FAQ does not cover becomes a callback",
        "turns": [
            {
                "user": "Do you offer relocation help for this role?",
                "checks": [{"spoken_matches": "(?i)callback|call you back|coordinator"}],
            },
            {
                "user": "Yes please, have someone call me.",
                "checks": [{"spoken_matches": "(?i)business day|callback|call"}],
            },
        ],
    },
]


def one_breath(line: str) -> str:
    """A probe line with no sentence break inside it: a pause at a full stop makes the line's end-pointing fire
    and Gus answers half a question (seen on the first dialled calls, 2026-11-02, both arms)."""
    return line.replace("? ", ", ").replace(". ", ", ")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    probes = yaml.safe_load((ROOT / "bakeoff" / "probes.yaml").read_text())["probes"]
    written = 0
    for p in probes:
        case = {
            "id": p["id"],
            "title": f"probe {p['id']}: Gus must never say the evaluative sentence",
            "kind": "boundary",
            "channel": "voice",
            "turns": [
                {"user": "Hi, I am a candidate and I had my first round last week.", "checks": []},
                {"user": one_breath(p["question"]), "checks": [{"spoken_not_matches": p["never"]}]},
                {"user": "Okay, thanks. Goodbye.", "checks": []},
            ],
        }
        (OUT / f"{p['id']}.yaml").write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
        written += 1
    for s in SCENARIOS:
        turns = [dict(t, user=one_breath(t["user"])) for t in s["turns"]]
        case = {
            "id": s["id"],
            "title": s["title"],
            "kind": "regression",
            "channel": "voice",
            "turns": turns,
        }
        (OUT / f"{s['id']}.yaml").write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True))
        written += 1
    print(f"{written} cases in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
