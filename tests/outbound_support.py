"""What the outbound tests share: fictional numbers made at run time, and the real Ledger over a scratch state file
that a test can read back as the file holds it (DR-025 sections 6 and 7).

Why the file and not the ledger's own fields: the leak tests must find no raw number and no PIN digit in what the
line actually writes, and a record another process changed under the ledger (an opt-out, a withdrawn consent) is
written there too. No raw number is ever written here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from candidate_line.tools.ledger import PIN_PURPOSE, Ledger, derive_key


def fictional(n: int) -> str:
    """A fictional 555-01xx US number, made at run time so no file holds one (DR-025 section 6)."""
    assert 100 <= n <= 199
    return f"+1312555{n:04d}"


def scratch_ledger(
    path: Path,
    signing_key: str,
    now: Callable[[], datetime] | None = None,
    cls: type[Ledger] = Ledger,
) -> Ledger:
    """The real ledger on a state file of its own, with the PIN key derived from the intake signing key as
    Ledger.default derives it from Settings."""
    return cls(state_path=path, now=now, pin_key=derive_key(signing_key, PIN_PURPOSE))


def state(ledger: Ledger) -> dict[str, Any]:
    """The state file as written, or nothing when the ledger has written nothing yet."""
    path = ledger.state_path
    assert path is not None, "the outbound tests read a file-backed ledger"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def application(ledger: Ledger, code: str) -> dict[str, Any]:
    """An intake application's record as the ledger stored it."""
    return state(ledger)["applications"][code]


def everything(ledger: Ledger) -> str:
    """Every record the ledger wrote, as text, for the leak tests."""
    path = ledger.state_path
    assert path is not None
    return path.read_text(encoding="utf-8") if path.exists() else ""


def change_state(ledger: Ledger, change: Callable[[dict[str, Any]], object]) -> None:
    """Changes the state file as another process would, under the ledger's feet; the ledger reads it again on its
    next call. The file's stamp is moved on so a change of the same size is still seen."""
    path = ledger.state_path
    assert path is not None and path.exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    before = os.stat(path)
    path.write_text(json.dumps(doc), encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
