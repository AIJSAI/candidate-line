"""What the voice regression runs inside the line's container (DR-024): the ledger snapshot, the reset before each
case, the read of one probe call's spans after it, and the restore at the end.

Why shipped as source and not imported there: the image on the task was built before this file existed, so the
runner sends this file's text through `aws ecs execute-command` and runs `main` on it (regression.py). It uses only
the standard library, PyYAML and the ledger, which every image has. Nothing it prints holds a PIN: a candidate's
state is the ledger's three fields, and the spans are the store's own, with the digit runs masked as the line wrote
them. The answer is one line, compressed and base64-encoded between two markers, so the session's own chatter
around it never breaks the JSON.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys  # noqa: F401  (the line program() appends puts the app on sys.path)
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BEGIN, END = "BEGIN-REGRESSION:", ":END-REGRESSION"
# A call row with no end that started within this window may be a caller on the line right now, and a reset would
# take their booking back. Twice the default call cap (settings.py, 300 s), so a capped call has surely ended.
LIVE_WINDOW = timedelta(seconds=600)


def emit(result: dict[str, Any]) -> str:
    packed = base64.b64encode(zlib.compress(json.dumps(result).encode())).decode()
    return f"{BEGIN}{packed}{END}"


def _store(path: str) -> sqlite3.Connection:
    # Read-only: the session runs as root, and a writable open could leave a journal the line cannot own.
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _calls(db: sqlite3.Connection) -> list[Any]:
    """The calls table's row count and latest start: a real call arriving changes one of them. A probe call never
    writes a row, because only /voice starts one (telephony/app.py)."""
    count, latest = db.execute("SELECT COUNT(*), MAX(started_at) FROM calls").fetchone()
    return [int(count), latest]


def _live_calls(db: sqlite3.Connection, now: datetime) -> int:
    since = (now - LIVE_WINDOW).isoformat(timespec="milliseconds")
    row = db.execute(
        "SELECT COUNT(*) FROM calls WHERE ended_at IS NULL AND started_at > ?", (since,)
    ).fetchone()
    return int(row[0])


def _states(state: Path) -> dict[str, dict[str, Any]]:
    """Every candidate's booked_slot, moves_used and callback_requested, as the line's own ledger reads them."""
    import yaml

    from candidate_line.tools.ledger import CANDIDATES_PATH, Ledger

    ledger = Ledger(state_path=state)
    rows = yaml.safe_load(CANDIDATES_PATH.read_text(encoding="utf-8")).get("candidates", [])
    return {str(row["code"]): ledger.state(str(row["code"])) for row in rows}


def _write_as_line(target: Path, body: bytes) -> None:
    """Writes the file beside and renames it in, so the line never reads half a ledger, owned by whoever owns var/
    (the line's user) and readable only by it, as the ledger writes its own file."""
    tmp = target.with_name(f".{target.name}.regression.tmp")
    tmp.write_bytes(body)
    os.chmod(tmp, 0o600)
    if os.geteuid() == 0:
        owner = os.stat(target.parent)
        os.chown(tmp, owner.st_uid, owner.st_gid)
    os.replace(tmp, target)


def _put_back(snapshot: Path, state: Path) -> None:
    """The ledger as the snapshot holds it. An empty snapshot means there was no ledger file at all."""
    body = snapshot.read_bytes()
    if body:
        _write_as_line(state, body)
    else:
        state.unlink(missing_ok=True)


def main(args: dict[str, Any]) -> dict[str, Any]:
    db = _store(args["store"])
    try:
        return _run(args, db)
    finally:
        db.close()


def _run(args: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    state, snapshot = Path(args["state"]), Path(args["snapshot"])
    token_file = snapshot.with_name(snapshot.name + ".run")
    calls = _calls(db)
    op = args["op"]
    if op == "snapshot":
        # A snapshot left by an earlier run means that run never restored; only a person knows whether a real
        # call came since, so the run stops. A snapshot carrying this run's token is this run's own retry.
        if snapshot.exists() and (not token_file.exists() or token_file.read_text() != args["token"]):
            return {"error": "leftover", "calls": calls}
        if Path(args["kill"]).exists():
            return {"error": "kill", "calls": calls}
        live = _live_calls(db, datetime.now(UTC))
        if live:
            return {"error": "live", "live": live, "calls": calls}
        _write_as_line(snapshot, state.read_bytes() if state.exists() else b"")
        _write_as_line(token_file, str(args["token"]).encode())
        return {"calls": calls, "states": _states(state)}
    if op == "reset":
        if calls != args["calls"]:
            return {"real_call": True, "calls": calls}
        _put_back(snapshot, state)
        seq = db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM spans WHERE call_id = ?", (args["call_id"],)
        ).fetchone()[0]
        return {"real_call": False, "calls": calls, "seq": int(seq)}
    if op == "read":
        rows = db.execute(
            "SELECT seq, kind, name, started_at, ms, text, meta FROM spans WHERE call_id = ? AND seq > ? "
            "ORDER BY seq",
            (args["call_id"], int(args["after"])),
        ).fetchall()
        spans = [
            {
                "seq": r[0],
                "kind": r[1],
                "name": r[2],
                "at": r[3],
                "ms": r[4],
                "text": r[5] or "",
                "meta": r[6],
            }
            for r in rows
        ]
        return {"calls": calls, "spans": spans, "states": _states(state)}
    if op == "restore":
        if not snapshot.exists():
            return {"restored": False, "why": "no snapshot", "calls": calls}
        if calls != args["calls"]:
            return {"restored": False, "why": "real call", "calls": calls}
        _put_back(snapshot, state)
        snapshot.unlink()
        token_file.unlink(missing_ok=True)
        return {"restored": True, "calls": calls}
    return {"error": f"unknown op {op!r}"}


def program(source: str, args: dict[str, Any], app: str = "/app") -> str:
    """This file's text plus the call, as one program for `python -c`. The app directory goes first on the path
    before the ledger is imported (inside _states), so the container's own copy answers. Nothing is put before the
    source, because its `from __future__` line must come first."""
    call = base64.b64encode(json.dumps(args).encode()).decode()
    return (
        f"{source}\nsys.path.insert(0, {app!r})\nprint(emit(main(json.loads(base64.b64decode({call!r})))))\n"
    )
