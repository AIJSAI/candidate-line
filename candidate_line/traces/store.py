"""Where every call's record lands: one SQLite file, text and metadata only, never audio.

Why SQLite: one file under var/ (ignored by git), no server, readable with any tool, and the cockpit's list view
is one query. Why masking lives here: the store is the only writer, so a caller's number is masked in the one
function that accepts it and no span can carry a raw number by accident. A span's metadata loses any PIN the same
way, in the one function that writes spans (the second dry run of card 04). The spans themselves are written live
on Wednesday from the turn loop; today the store, its schema and its page exist.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = (
    ROOT / "var" / "traces.sqlite"
)  # Settings.trace_store_path overrides it; no os.environ here (DR-004)
EVAL_DEFAULT_PATH = DEFAULT_PATH.with_name(
    "eval-traces.sqlite"
)  # the eval runner's own store, never the room's
_BYTES = (bytes, bytearray, memoryview)
PIN_MASK = "****"

# The kinds the pre-built store knows plus the ones the room's cards write (cite from card 03, tier, override and
# kill from card 06; card 03 writes a tier placeholder), so no card has to touch this file to name its span.
SPAN_KINDS = (
    "transcribe",
    "model",
    "tool",
    "speech",
    "hook",
    "escalation",
    "cite",
    "tier",
    "override",
    "kill",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY, channel TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
  caller_masked TEXT, provider TEXT, model TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS spans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL REFERENCES calls(call_id), seq INTEGER NOT NULL,
  kind TEXT NOT NULL, name TEXT NOT NULL, started_at TEXT NOT NULL, ms INTEGER, tokens_in INTEGER, tokens_out INTEGER,
  chars INTEGER, seconds REAL, text TEXT, meta TEXT);
CREATE INDEX IF NOT EXISTS spans_call ON spans(call_id, seq);
CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL, created_at TEXT NOT NULL, tier TEXT NOT NULL,
  reason TEXT NOT NULL, suggested_action TEXT NOT NULL, channel TEXT NOT NULL, posted_at TEXT, post_error TEXT,
  reply TEXT, replied_by TEXT, replied_at TEXT);
"""


def _holds_bytes(value: Any) -> bool:
    """Bytes anywhere in the metadata, however nested; the refusal is explicit, not json.dumps's accident."""
    if isinstance(value, _BYTES):
        return True
    if isinstance(value, dict):
        return any(_holds_bytes(k) or _holds_bytes(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(_holds_bytes(v) for v in value)
    return False


def _mask_pins(value: Any) -> Any:
    """A copy of the metadata with the value of every key that names a PIN replaced, however deeply nested.

    Why nested: a tool span's meta holds the tool's arguments, and the arguments of the call that checks a caller
    carry the PIN the caller just said (the second dry run of card 04). Why a substring of the lowercase name:
    `pin`, `PIN` and `caller_pin` are all caught, and a key caught by accident only loses its value from a trace.
    """
    if isinstance(value, dict):
        return {k: PIN_MASK if "pin" in str(k).lower() else _mask_pins(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_pins(v) for v in value]
    return value


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def mask_number(number: str | None) -> str | None:
    """Keeps the last four digits, which is enough to tell two callers apart on the cockpit and nothing more."""
    if number is None:
        return None
    digits = re.sub(r"\D", "", number)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


@dataclass(frozen=True)
class CallRow:
    call_id: str
    channel: str
    started_at: str
    ended_at: str | None
    caller_masked: str | None
    provider: str | None
    model: str | None
    outcome: str | None
    span_count: int
    model_ms: int
    escalations: int
    tier: str | None = None  # the name of the call's last tier span (card 06), None before its first turn


@dataclass(frozen=True)
class SpanRow:
    seq: int
    kind: str
    name: str
    started_at: str
    ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    chars: int | None
    seconds: float | None
    text: str | None
    meta: dict[str, Any]


@dataclass(frozen=True)
class EscalationRow:
    id: int
    call_id: str
    created_at: str
    tier: str
    reason: str
    suggested_action: str
    channel: str
    posted_at: str | None
    post_error: str | None
    reply: str | None
    replied_by: str | None
    replied_at: str | None


# The list view and the single-row lookup read the same columns, so a CallRow means the same thing from both.
_CALL_SELECT = """SELECT c.*, (SELECT COUNT(*) FROM spans s WHERE s.call_id = c.call_id) AS span_count,
   (SELECT COALESCE(SUM(ms), 0) FROM spans s WHERE s.call_id = c.call_id AND s.kind = 'model') AS model_ms,
   (SELECT COUNT(*) FROM escalations e WHERE e.call_id = c.call_id) AS escalations,
   (SELECT s.name FROM spans s WHERE s.call_id = c.call_id AND s.kind = 'tier' ORDER BY s.seq DESC LIMIT 1) AS tier
   FROM calls c"""


class TraceStore:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def start_call(
        self,
        call_id: str,
        channel: str,
        caller: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO calls (call_id, channel, started_at, caller_masked, provider, model) VALUES (?,?,?,?,?,?)",
                (call_id, channel, now(), mask_number(caller), provider, model),
            )
            self._conn.commit()

    def end_call(self, call_id: str, outcome: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE calls SET ended_at = ?, outcome = ? WHERE call_id = ?", (now(), outcome, call_id)
            )
            self._conn.commit()

    def span(
        self,
        call_id: str,
        kind: str,
        name: str,
        *,
        ms: int | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        chars: int | None = None,
        seconds: float | None = None,
        text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        if kind not in SPAN_KINDS:
            raise ValueError(f"span kind must be one of {SPAN_KINDS}, not {kind!r}")
        if isinstance(text, _BYTES) or isinstance(name, _BYTES) or _holds_bytes(meta):
            raise TypeError("a span carries text and metadata, never audio bytes")
        with self._lock:
            seq = (
                self._conn.execute("SELECT COUNT(*) FROM spans WHERE call_id = ?", (call_id,)).fetchone()[0]
                + 1
            )
            self._conn.execute(
                "INSERT INTO spans (call_id, seq, kind, name, started_at, ms, tokens_in, tokens_out, chars, seconds, text, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    call_id,
                    seq,
                    kind,
                    name,
                    now(),
                    ms,
                    tokens_in,
                    tokens_out,
                    chars,
                    seconds,
                    text,
                    json.dumps(_mask_pins(meta or {})),
                ),
            )
            self._conn.commit()
        return seq

    def calls(self, limit: int = 100) -> list[CallRow]:
        with self._lock:
            rows = self._conn.execute(
                f"{_CALL_SELECT} ORDER BY c.started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [CallRow(**dict(r)) for r in rows]

    def call(self, call_id: str) -> CallRow | None:
        """One call by id, or None. The hand-off reads its masked caller here, and a scan of `calls(limit)` would
        miss a call that is not among the latest ones."""
        with self._lock:
            row = self._conn.execute(f"{_CALL_SELECT} WHERE c.call_id = ?", (call_id,)).fetchone()
        return None if row is None else CallRow(**dict(row))

    def spans(self, call_id: str) -> list[SpanRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM spans WHERE call_id = ? ORDER BY seq", (call_id,)
            ).fetchall()
        return [
            SpanRow(
                **{k: v for k, v in dict(r).items() if k not in ("id", "call_id", "meta")},
                meta=json.loads(r["meta"]),
            )
            for r in rows
        ]

    def add_escalation(
        self, call_id: str, tier: str, reason: str, suggested_action: str, channel: str
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO escalations (call_id, created_at, tier, reason, suggested_action, channel) VALUES (?,?,?,?,?,?)",
                (call_id, now(), tier, reason, suggested_action, channel),
            )
            self._conn.commit()
        return int(cur.lastrowid)

    def mark_posted(self, escalation_id: int, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE escalations SET posted_at = ?, post_error = ? WHERE id = ?",
                (None if error else now(), error, escalation_id),
            )
            self._conn.commit()

    def reply(self, escalation_id: int, text: str, by: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE escalations SET reply = ?, replied_by = ?, replied_at = ? WHERE id = ?",
                (text, by, now(), escalation_id),
            )
            self._conn.commit()

    def delete_call(self, call_id: str) -> int:
        """Removes one call's row, spans and hand-offs, for a deletion request or the end of an application's
        retention (spec 9.13): the screening call's spans hold the applicant's masked words and the values
        recorded, which the ledger's deletion would otherwise leave behind. Returns the rows removed."""
        with self._lock:
            removed = 0
            for table in ("spans", "escalations", "calls"):
                removed += self._conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,)).rowcount
            self._conn.commit()
        return removed

    def escalations(self, call_id: str | None = None) -> list[EscalationRow]:
        with self._lock:
            if call_id is None:
                rows = self._conn.execute("SELECT * FROM escalations ORDER BY id DESC").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM escalations WHERE call_id = ? ORDER BY id", (call_id,)
                ).fetchall()
        return [EscalationRow(**dict(r)) for r in rows]
