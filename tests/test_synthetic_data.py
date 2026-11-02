import csv
import re
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parent.parent / "data"


def test_every_file_is_marked_synthetic() -> None:
    for name in ("candidates.yaml", "slots.yaml", "baseline_invites.csv", "faq.md", "PROMPT.md"):
        head = (DATA / name).read_text().splitlines()[0].lower()
        assert "synthetic" in head, name


def test_eight_candidates_with_unique_codes_and_string_pins() -> None:
    doc = yaml.safe_load((DATA / "candidates.yaml").read_text())
    cands = doc["candidates"]
    assert doc["synthetic"] is True and len(cands) == 8
    assert len({c["code"] for c in cands}) == 8
    for c in cands:
        assert re.fullmatch(r"ACME-\d{4}", c["code"])
        assert isinstance(c["pin"], str) and re.fullmatch(r"\d{4}", c["pin"])
        assert "phone" not in c and "email" not in c
    assert sorted(c["stage"] for c in cands) == sorted(
        ["invited"] * 4 + ["booked"] * 2 + ["moved_once", "first_round_done"]
    )


def test_slots_cover_two_weeks_of_business_days_and_match_the_candidates() -> None:
    slots = yaml.safe_load((DATA / "slots.yaml").read_text())["slots"]
    cands = yaml.safe_load((DATA / "candidates.yaml").read_text())["candidates"]
    assert len(slots) == 10 * 4
    assert all(s["start"].endswith("-06:00") for s in slots)
    held = {s["held_by"]: s["id"] for s in slots if s["status"] == "booked"}
    booked = {c["code"]: c["booked_slot"] for c in cands if c["booked_slot"]}
    assert held == booked


def test_baseline_has_forty_rows_all_synthetic() -> None:
    lines = (DATA / "baseline_invites.csv").read_text().splitlines()
    rows = list(csv.DictReader(lines[1:]))
    assert len(rows) == 40 and all(r["synthetic"] == "true" for r in rows)
    booked = [float(r["hours_to_book"]) for r in rows if r["hours_to_book"]]
    assert 25 <= len(booked) <= 40 and all(h > 0 for h in booked)


def test_faq_has_eight_sections_with_ids_and_no_scoring_language() -> None:
    text = (DATA / "faq.md").read_text()
    assert [f"## F{i}." in text for i in range(1, 9)] == [True] * 8
    assert len(re.findall(r"^### F\d\.\d ", text, flags=re.MULTILINE)) >= 24
    for word in ("top candidate", "strong candidate", "ranked", "score of"):
        assert word not in text.lower()


def test_generator_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen", Path(__file__).resolve().parent.parent / "scripts" / "make_synthetic_data.py"
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    monkeypatch.setattr(gen, "DATA", tmp_path)
    gen.make()
    for name in ("candidates.yaml", "slots.yaml", "baseline_invites.csv"):
        assert (tmp_path / name).read_text() == (DATA / name).read_text(), name
