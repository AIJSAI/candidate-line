"""The contacts store: the one place a raw phone number is kept (spec 9.13, DR-025 section 9).

Why a store of its own and not a field in the ledger: the ledger's state file is read by the cockpit, the
scorecard and anyone debugging a booking, and none of them needs a number. Here a number is written only for an
application with a dial scheduled, read only by the dialler, deleted on the first dialler tick after
CONTACTS_RETENTION_DAYS, and deleted at once on an opt-out or a deletion request. The file sits on the encrypted
volume with mode 600 and is written whole and atomically under its own lock, so a reader never sees half of it.
Nothing here logs, prints or repr()s a number; every other path holds only `mask_number`'s form.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from candidate_line.settings import DEFAULT_CONTACTS_RETENTION_DAYS, US_E164

log = logging.getLogger("candidate_line.contacts")

VERSION = 1
FILE_MODE = 0o600
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    """One lock per file in this process, so two stores over one file still take turns."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path.resolve()), threading.RLock())


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


def _parse(stamp: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class Contacts:
    """`put`, `number`, `delete` and `purge` over one JSON file. `number` is the only way a number comes out."""

    def __init__(self, path: Path | str, retention_days: int = DEFAULT_CONTACTS_RETENTION_DAYS) -> None:
        if retention_days < 1:
            raise ValueError("CONTACTS_RETENTION_DAYS must be at least 1")
        self._path = Path(path)
        self._retention = timedelta(days=retention_days)
        self._lock = _lock_for(self._path)
        self._corrupt = False  # set by a read that found damage, so the next purge rewrites the file

    def __repr__(self) -> str:
        # The path and the count are safe to show; the numbers never are.
        return f"Contacts({str(self._path)!r})"

    @property
    def path(self) -> Path:
        return self._path

    def put(self, code: str, e164: str, now: datetime) -> None:
        """Keeps one application's number until the retention runs out. Only a US E.164 number is kept, because
        intake validated it and anything else here is a bug that would dial a stranger."""
        if not US_E164.match(e164):
            raise ValueError("a contact's number must be a US number in E.164 form")
        with self._exclusive() as contacts:
            contacts[code] = {
                "number": e164,
                "added_at": _stamp(now),
                "delete_after": _stamp(now + self._retention),
            }
            self._write(contacts)

    def number(self, code: str) -> str | None:
        """The raw number for one application, for the dialler's Calls.json and nothing else."""
        with self._exclusive() as contacts:
            row = contacts.get(code)
            number = row.get("number") if isinstance(row, dict) else None
            return number if isinstance(number, str) and US_E164.match(number) else None

    def has(self, code: str) -> bool:
        with self._exclusive() as contacts:
            return code in contacts

    def codes(self) -> tuple[str, ...]:
        """The application codes that have a number here, and never the numbers: the sweep's way to find a
        contact whose application has since opted out or been forgotten."""
        with self._exclusive() as contacts:
            return tuple(sorted(contacts))

    def delete(self, code: str) -> bool:
        """Removes one contact at once: an opt-out, a deletion request, or a number found off the allow-list."""
        with self._exclusive() as contacts:
            if code not in contacts:
                return False
            del contacts[code]
            self._write(contacts)
            return True

    def purge(self, now: datetime) -> int:
        """Deletes every contact past its time, by the stamp written at `put` or by the retention this store has
        now, whichever is sooner, so shortening CONTACTS_RETENTION_DAYS takes effect on the next tick. A row whose
        stamps cannot be read goes too: a number with no readable date has no date to be kept until."""
        with self._exclusive() as contacts:
            expired: list[str] = []
            for code, row in contacts.items():
                added = _parse(row.get("added_at")) if isinstance(row, dict) else None
                until = _parse(row.get("delete_after")) if isinstance(row, dict) else None
                if added is None or until is None or now >= min(until, added + self._retention):
                    expired.append(code)
            for code in expired:
                del contacts[code]
            if expired or self._corrupt:
                self._write(contacts)
            return len(expired)

    # Inside the lock.

    @contextmanager
    def _exclusive(self) -> Iterator[dict[str, Any]]:
        """The thread lock and an advisory lock on a file beside the store, then the store read afresh."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path.with_name(f"{self._path.name}.lock"), "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield self._read()
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        self._corrupt = False
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            # The file is written whole and renamed into place, so this is damage, not a race. It is not set
            # aside: a copy would hold numbers that no purge would ever reach. The next write replaces it, and a
            # dial with no number is cancelled rather than placed.
            log.warning("the contacts store could not be read; it is treated as empty until the next write")
            self._corrupt = True
            return {}
        contacts = raw.get("contacts") if isinstance(raw, dict) else None
        if not isinstance(contacts, dict):
            self._corrupt = True
            return {}
        return {str(code): row for code, row in contacts.items() if isinstance(row, dict)}

    def _write(self, contacts: dict[str, Any]) -> None:
        parent = self._path.parent
        # mkstemp creates the file with mode 600, so the number is never readable by others, not even for the
        # moment before the rename.
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=f".{self._path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": VERSION, "contacts": contacts}, f, indent=2, sort_keys=True)
                f.write("\n")
            os.chmod(tmp, FILE_MODE)
            os.replace(tmp, self._path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._corrupt = False
