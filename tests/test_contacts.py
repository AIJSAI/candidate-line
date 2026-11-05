"""The contacts store: the one store of raw numbers (spec 9.13, DR-025 section 9, fix 16)."""

import json
import logging
import stat
from datetime import UTC, datetime, timedelta

import pytest

from candidate_line.outbound.contacts import Contacts

NOW = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)


def fictional(n: int) -> str:
    """A fictional 555-01xx number, made at run time so no file holds one (DR-025 section 6)."""
    return f"+1312555{n:04d}"


def test_a_number_goes_in_and_comes_out_only_through_number(tmp_path) -> None:
    contacts = Contacts(tmp_path / "contacts.json")
    contacts.put("ACME-1234", fictional(142), NOW)
    assert contacts.number("ACME-1234") == fictional(142)
    assert contacts.number("ACME-9999") is None
    # Nothing else on the object hands a number back, and its repr shows none.
    public = [name for name in dir(contacts) if not name.startswith("_")]
    assert sorted(public) == ["codes", "delete", "has", "number", "path", "purge", "put"]
    assert "0142" not in repr(contacts)
    assert contacts.has("ACME-1234") and not contacts.has("ACME-9999")


def test_the_file_is_mode_600_and_holds_the_contract_shape(tmp_path) -> None:
    path = tmp_path / "contacts.json"
    Contacts(path).put("ACME-1234", fictional(142), NOW)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    doc = json.loads(path.read_text())
    assert doc == {
        "version": 1,
        "contacts": {
            "ACME-1234": {
                "number": fictional(142),
                "added_at": "2026-11-05T16:00:00+00:00",
                "delete_after": "2026-12-05T16:00:00+00:00",
            }
        },
    }
    assert not list(tmp_path.glob(".contacts.json.*.tmp"))  # the write left no temporary copy behind


def test_a_number_that_is_not_us_e164_is_never_kept(tmp_path) -> None:
    contacts = Contacts(tmp_path / "contacts.json")
    national = fictional(142)[2:]
    for bad in (national, "+44" + national, "", fictional(142)[:-1]):
        with pytest.raises(ValueError):
            contacts.put("ACME-1234", bad, NOW)
    assert not (tmp_path / "contacts.json").exists()


def test_delete_removes_a_contact_at_once(tmp_path) -> None:
    contacts = Contacts(tmp_path / "contacts.json")
    contacts.put("ACME-1234", fictional(142), NOW)
    contacts.put("ACME-5678", fictional(143), NOW)
    assert contacts.delete("ACME-1234") is True
    assert contacts.delete("ACME-1234") is False
    assert contacts.number("ACME-1234") is None and contacts.number("ACME-5678") == fictional(143)
    assert "0142" not in (tmp_path / "contacts.json").read_text()


def test_purge_deletes_a_number_on_the_first_tick_after_the_retention(tmp_path) -> None:
    contacts = Contacts(tmp_path / "contacts.json", retention_days=30)
    contacts.put("ACME-1234", fictional(142), NOW)
    contacts.put("ACME-5678", fictional(143), NOW + timedelta(days=1))
    assert contacts.purge(NOW + timedelta(days=30) - timedelta(seconds=1)) == 0
    assert contacts.purge(NOW + timedelta(days=30)) == 1
    assert contacts.number("ACME-1234") is None and contacts.number("ACME-5678") == fictional(143)
    assert "0142" not in (tmp_path / "contacts.json").read_text()


def test_a_shorter_retention_takes_effect_on_the_next_purge(tmp_path) -> None:
    path = tmp_path / "contacts.json"
    Contacts(path, retention_days=30).put("ACME-1234", fictional(142), NOW)
    assert Contacts(path, retention_days=7).purge(NOW + timedelta(days=7)) == 1


def test_two_stores_over_one_file_see_each_others_writes(tmp_path) -> None:
    a, b = Contacts(tmp_path / "c.json"), Contacts(tmp_path / "c.json")
    a.put("ACME-1234", fictional(142), NOW)
    assert b.number("ACME-1234") == fictional(142)
    b.delete("ACME-1234")
    assert a.number("ACME-1234") is None


def test_a_damaged_file_is_read_as_empty_and_replaced_by_the_next_purge(tmp_path, caplog) -> None:
    path = tmp_path / "contacts.json"
    path.write_text("{not json " + fictional(142))
    contacts = Contacts(path)
    with caplog.at_level(logging.WARNING):
        assert contacts.number("ACME-1234") is None
        contacts.purge(NOW)
    assert "0142" not in path.read_text()  # the damaged copy is gone, not set aside with its number in it
    assert not list(tmp_path.glob("contacts.json.bad*"))
    assert all("0142" not in r.getMessage() for r in caplog.records)


def test_a_row_with_no_readable_dates_is_purged(tmp_path) -> None:
    path = tmp_path / "contacts.json"
    row = {"number": fictional(142), "added_at": "soon", "delete_after": None}
    path.write_text(json.dumps({"version": 1, "contacts": {"ACME-1234": row}}))
    assert Contacts(path).purge(NOW) == 1


def test_purge_of_a_missing_file_creates_nothing(tmp_path) -> None:
    assert Contacts(tmp_path / "contacts.json").purge(NOW) == 0
    assert not (tmp_path / "contacts.json").exists()


def test_a_retention_below_one_day_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        Contacts(tmp_path / "c.json", retention_days=0)
