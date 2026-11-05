import csv
import re
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parent.parent / "data"
# Every file scripts/make_synthetic_data.py writes; the outbound three since card 08 (DR-025).
GENERATED = (
    "candidates.yaml",
    "slots.yaml",
    "baseline_invites.csv",
    "roles.yaml",
    "applications.yaml",
    "baseline_screens.csv",
)


def test_every_file_is_marked_synthetic() -> None:
    for name in (*GENERATED, "faq.md", "PROMPT.md"):
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
    assert [f"## F{i}." in text for i in range(1, 10)] == [True] * 9
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
    for name in GENERATED:
        assert (tmp_path / name).read_text() == (DATA / name).read_text(), name


def test_outbound_fixtures_hold_no_number_and_only_closed_rules() -> None:
    roles = yaml.safe_load((DATA / "roles.yaml").read_text())
    apps = yaml.safe_load((DATA / "applications.yaml").read_text())
    assert roles["synthetic"] is True and apps["synthetic"] is True
    role_ids = {r["id"] for r in roles["roles"]}
    forms = {"yes_no": {"equals"}, "choice": {"one_of"}, "range": {"at_least", "at_most", "between"}}
    for role in roles["roles"]:
        assert 4 <= len(role["questions"]) <= 6
        for q in role["questions"]:
            assert set(q["rule"]) <= forms[q["kind"]] and len(q["rule"]) == 1, (role["id"], q["id"])
            assert q["asks"] and q["reason"] and q["say"]
    cand_codes = {c["code"] for c in yaml.safe_load((DATA / "candidates.yaml").read_text())["candidates"]}
    codes = [a["code"] for a in apps["applications"]]
    assert len(set(codes)) == len(codes) == 6 and not set(codes) & cand_codes
    for a in apps["applications"]:
        assert re.fullmatch(r"ACME-\d{4}", a["code"]) and a["role"] in role_ids
        assert isinstance(a["pin"], str) and re.fullmatch(r"\d{4}", a["pin"])
        assert a["consent"]["version"] in apps["consent_texts"]
        assert not {"phone", "number", "email"} & set(a)
    first_round = {s["id"] for s in yaml.safe_load((DATA / "slots.yaml").read_text())["slots"]}
    interview = {s["id"] for s in roles["interview_slots"]}
    assert len(interview) == 40 and not interview & first_round


def test_baseline_screens_has_forty_rows_all_synthetic() -> None:
    lines = (DATA / "baseline_screens.csv").read_text().splitlines()
    rows = list(csv.DictReader(lines[1:]))
    assert len(rows) == 40 and all(r["synthetic"] == "true" for r in rows)
    assert all(float(r["minutes"]) > 0 for r in rows)
