# bakeoff/

DR-001's measurement: the rule was written before the numbers, and this folder's first commit dates it. Nothing here is a decision; the decision text is finished live on Wednesday.

- `probes.yaml`: ten probe questions and the ten evaluative sentence patterns Gus must never say (rule (a)).
- `persona.md`: the test persona both arms run on a live model for the measurement (never the echo brain).
- `2026-11-01.csv`: one row per measured turn. `method` is `recording` (the gap between the caller's last word and Gus's first, read from the Twilio call recording, DR-001's method) or `probe` (the same gap measured in-process by the probe caller, DR-011, as the cross-check). `probe_hit` is the probe id whose `never` pattern matched, or empty.
- `recordings/`: local only, ignored by git; each recording is deleted from Twilio once its turns are in the CSV.

How a run goes: five scripted calls per arm and the ten probe calls per arm, the same persona on both; the medians and the probe count go into DR-001's measurement table with the n. If the day runs long, the plan's cut list shrinks this to three calls and five probes per arm, with the n written into DR-001.
