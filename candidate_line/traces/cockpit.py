"""The recruiter's cockpit: one page that lists the calls, one per call, and a reply box per escalation; one page
that lists the applications and one per applicant with the answers the line recorded (DR-025 section 16).

Why its own app on its own port: it is for the recruiter, never for a candidate, so it is served on the loopback
(`make cockpit`, 127.0.0.1:8001) and never behind the tunnel. Why no template engine: a few pages, every value
escaped by hand in one place. The styling is inline and the pages carry no script, so the cockpit works with no
network at all; the handlers and the form are what card 06 wires into, so they stay as they are.

Why the applicant pages read the state file and never the Ledger: a ledger that opens a broken file moves it
aside, and a page that only reads must never move the live line's file (as scorecard.ledger_bookings). Why the list
has no sort, no filter, no colour and no count by answer: the line compares no applicant with another, and a page
that ranked or tallied them by answer would do it for the line (spec 5.1, DR-025 section 16).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from candidate_line.settings import Settings
from candidate_line.tools.ledger import APPLICATIONS_PATH, ROLES_PATH, load_applications, load_role_plans
from candidate_line.traces.store import DEFAULT_PATH, CallRow, EscalationRow, SpanRow, TraceStore

CENTRAL = ZoneInfo("America/Chicago")
_CODE = re.compile(r"ACME-[0-9]{4}")
# The applicant's words are masked by the tool before they are written; a run of four digits or more is masked
# again here, so a slip upstream never shows a PIN or a number on the page.
_DIGIT_RUN = re.compile(r"(?<![0-9])[0-9](?:[ ,.-]?[0-9]){3,}(?![0-9])")
# A reader who leaves the page open overnight is not an hour of reading; the minutes-saved row reads this cap.
MAX_READ_SECONDS = 3600
_REACHED = frozenset(
    {"screened", "screen_unfinished", "opted_out", "wrong_person", "pin_missed", "hung_up_before_pin"}
)
_NOT_DIALLED = {
    "no_consent": "not dialled: no consent",
    "not_allowed": "not dialled: number not on the allow-list",
    "opted_out": "not dialled: the number had opted out",
}

STYLE = (
    "<style>"
    ":root{--ink:#1d1d1f;--muted:#6e6e73;--line:#e3e4e8;--tint:#f6f7f9;--accent:#b45309;--accent-tint:#fff4e6}"
    "body{font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;margin:0;padding:28px 32px 48px;"
    "color:var(--ink);background:#fff;max-width:1200px}"
    "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;color:var(--accent);text-transform:uppercase;letter-spacing:.04em}"
    "p{margin:4px 0}.muted{color:var(--muted)}.sub{color:var(--muted);margin-bottom:18px}"
    "a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}"
    "table{border-collapse:collapse;width:100%;margin-top:10px}"
    "th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);text-align:left;"
    "padding:8px 10px;border-bottom:2px solid var(--line);white-space:nowrap}"
    "td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}"
    "tr:nth-child(even) td{background:var(--tint)}"
    "td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th.num{text-align:right}"
    "code,.mono{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}"
    ".when,.caller{white-space:nowrap}.text{max-width:420px}"
    ".pill{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;"
    "padding:2px 8px;border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--muted)}"
    ".pill.voice{color:var(--accent);border-color:var(--accent);background:var(--accent-tint)}"
    ".empty{color:var(--muted);padding:18px 0}"
    ".header{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:14px 24px;margin:14px 0 6px;"
    "padding:14px 16px;background:var(--tint);border:1px solid var(--line);border-radius:8px}"
    ".header .k{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}"
    ".header .v{margin-top:2px}"
    "form{margin:0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}"
    "label{font-size:12px;color:var(--muted)}"
    "input{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;min-width:160px}"
    "button{font:inherit;font-weight:600;padding:6px 14px;border-radius:6px;border:1px solid var(--accent);"
    "background:var(--accent);color:#fff;cursor:pointer}button:hover{filter:brightness(1.05)}"
    "</style>"
)


def page(title: str, body: str, subtitle: str | None = None) -> str:
    sub = f"<p class='sub'>{escape(subtitle)}</p>" if subtitle else ""
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title>{STYLE}</head><body><h1>{escape(title)}</h1>{sub}{body}</body></html>"
    )


def when(stamp: str | None) -> str:
    """An ISO UTC stamp from the store as readable text: 2026-11-03 21:03 UTC. Rendering only; the store keeps ISO."""
    if not stamp:
        return ""
    head = stamp.replace("T", " ")
    for sep in ("+", "Z"):
        if sep in head:
            head = head.split(sep, 1)[0]
    if "." in head:
        head = head.split(".", 1)[0]
    return f"{head[:16]} UTC" if len(head) >= 16 else head


def pill(channel: str) -> str:
    cls = "pill voice" if channel == "voice" else "pill"
    return f"<span class='{cls}'>{escape(channel)}</span>"


def brain(row: CallRow) -> str:
    provider = escape(row.provider or "")
    model = escape(row.model or "")
    if provider and model:
        return f"{provider} <span class='muted mono'>{model}</span>"
    return provider or f"<span class='muted mono'>{model}</span>"


def num(value: float | None, empty: str = "") -> str:
    if value is None:
        return f"<span class='muted'>{escape(empty)}</span>" if empty else ""
    return escape(str(value))


def call_cells(r: CallRow) -> str:
    steps = num(r.span_count) if r.span_count else "<span class='muted'>none yet</span>"
    model_ms = f"{r.model_ms} ms" if r.span_count else ""
    hand_offs = str(r.escalations) if r.escalations else "<span class='muted'>none</span>"
    tier = escape(r.tier) if r.tier else "<span class='muted'>none yet</span>"
    return (
        f"<tr><td class='when'>{escape(when(r.started_at))}</td>"
        f"<td><a href='/calls/{escape(r.call_id)}'><code>{escape(r.call_id)}</code></a></td>"
        f"<td>{pill(r.channel)}</td><td class='mono caller'>{escape(r.caller_masked or '')}</td><td>{brain(r)}</td>"
        f"<td class='num'>{steps}</td><td class='num'>{model_ms}</td><td class='num'>{tier}</td>"
        f"<td class='num'>{hand_offs}</td>"
        f"<td>{escape(r.outcome or '')}</td></tr>"
    )


def span_cells(s: SpanRow) -> str:
    tokens = ""
    if s.tokens_in is not None or s.tokens_out is not None:
        tokens = f"{s.tokens_in if s.tokens_in is not None else ''} / {s.tokens_out if s.tokens_out is not None else ''}"
    meta = f"<code class='muted'>{escape(str(s.meta))}</code>" if s.meta else ""
    return (
        f"<tr><td class='num'>{s.seq}</td><td>{escape(s.kind)}</td><td>{escape(s.name)}</td>"
        f"<td class='text'>{escape(s.text or '')}</td>"
        f"<td class='num'>{num(s.ms)}</td><td class='num'>{escape(tokens)}</td>"
        f"<td class='num'>{num(s.chars)}</td><td class='num'>{num(s.seconds)}</td><td>{meta}</td></tr>"
    )


def escalation_cells(e: EscalationRow) -> str:
    posted = escape(e.channel)
    if e.posted_at:
        posted += f" <span class='muted'>{escape(when(e.posted_at))}</span>"
    if e.post_error:
        posted += f" <span class='muted'>{escape(e.post_error)}</span>"
    if e.reply:
        reply = (
            f"{escape(e.reply)} <span class='muted'>({escape(e.replied_by or '')}, "
            f"{escape(when(e.replied_at))})</span>"
        )
    else:
        reply = (
            f"<form method='post' action='/escalations/{e.id}/reply'>"
            f"<label for='reply-{e.id}'>What you did</label>"
            f"<input id='reply-{e.id}' name='reply' placeholder='what you did' required> "
            f"<label for='by-{e.id}'>Your name</label>"
            f"<input id='by-{e.id}' name='by' placeholder='your name' required> "
            f"<button>Log reply</button></form>"
        )
    return (
        f"<tr><td class='num'>{e.id}</td><td>{escape(e.tier)}</td><td>{escape(e.reason)}</td>"
        f"<td>{escape(e.suggested_action)}</td><td>{posted}</td><td>{reply}</td></tr>"
    )


def read_state(state_path: Path | None) -> dict[str, Any] | None:
    """The ledger's state file as written; {} when there is none, None when it cannot be read. Never moved and
    never written here."""
    if state_path is None or not state_path.exists():
        return {}
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _records(state: Mapping[str, Any], key: str, kind: type) -> Any:
    value = state.get(key)
    return value if isinstance(value, kind) else kind()


def read_roles(path: Path = ROLES_PATH) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """The roles as posted, by id, and every interview slot's spoken label by id (data/roles.yaml)."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}, {}
    roles = {str(r["id"]): r for r in doc.get("roles") or []}
    return roles, {sid: s.label for sid, s in load_role_plans(path)[1].items()}


def applications(
    state: Mapping[str, Any], applications_path: Path = APPLICATIONS_PATH
) -> list[dict[str, Any]]:
    """Every application, the fixtures and those from intake, in arrival order (received time, oldest first). A
    removed application (a deletion or the end of retention) is gone from the list."""
    fixtures, _, _ = load_applications(applications_path)
    rows: dict[str, dict[str, Any]] = {
        code: {
            "code": a.code,
            "first_name": a.first_name,
            "role": a.role,
            "zone": a.zone,
            "received_at": a.received_at,
            "consent": dict(a.consent),
            "number_masked": None,
            "number_hmac": None,
            "not_dialled": None,
        }
        for code, a in fixtures.items()
    }
    for code, record in _records(state, "applications", dict).items():
        if isinstance(record, dict) and record.get("removed"):
            rows.pop(str(code), None)
        elif isinstance(record, dict) and record.get("code") == code:
            rows[str(code)] = record
    return sorted(rows.values(), key=lambda r: (_instant(r.get("received_at")) or _EPOCH, str(r.get("code"))))


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def central(stamp: object) -> str:
    """An ISO stamp in Central time, as the recruiter's day runs: "Wed 4 Nov 2026, 9:35 AM Central"."""
    when = _instant(stamp)
    if when is None:
        return str(stamp or "")
    local = when.astimezone(CENTRAL)
    return local.strftime("%a %-d %b %Y, %-I:%M %p Central")


def _dials(state: Mapping[str, Any], code: str) -> list[dict[str, Any]]:
    return [d for d in _records(state, "dials", list) if isinstance(d, dict) and d.get("code") == code]


def _opt_out(state: Mapping[str, Any], app: Mapping[str, Any]) -> dict[str, Any] | None:
    hashed = app.get("number_hmac")
    for record in _records(state, "opt_outs", list):
        if isinstance(record, dict) and (
            record.get("code") == app.get("code") or (hashed and record.get("number_hmac") == hashed)
        ):
            return record
    return None


def _answers(state: Mapping[str, Any], code: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    entry = _records(state, "answers", dict).get(code)
    if not isinstance(entry, dict):
        return {}, None
    by_question = entry.get("by_question") if isinstance(entry.get("by_question"), dict) else {}
    screen = entry.get("screen") if isinstance(entry.get("screen"), dict) else None
    return by_question, screen


def _booked(state: Mapping[str, Any], code: str) -> str | None:
    booking = _records(state, "bookings", dict).get(code)
    return str(booking["slot_id"]) if isinstance(booking, dict) and booking.get("slot_id") else None


def line_status(
    state: Mapping[str, Any], app: Mapping[str, Any], slot_labels: Mapping[str, str], now: datetime
) -> str:
    """The line's status for one application, in words, never a verdict on the applicant."""
    code = str(app.get("code"))
    reason = app.get("not_dialled")
    if reason:
        return _NOT_DIALLED.get(str(reason), f"not dialled: {reason}")
    consent = app.get("consent") if isinstance(app.get("consent"), dict) else {}
    if consent.get("accepted") is not True:
        return _NOT_DIALLED["no_consent"]
    if _opt_out(state, app) is not None:
        return "opted out"
    booked = _booked(state, code)
    if booked:
        return f"booked: {slot_labels.get(booked, booked)}"
    _, screen = _answers(state, code)
    if screen is not None and screen.get("promised_by"):
        return f"recruiter call promised by {central(screen['promised_by'])}"
    if screen is not None:
        return "reached: interview times offered, none booked yet"
    dials = _dials(state, code)
    statuses = {d.get("status") for d in dials}
    if statuses & {"claimed", "placed"}:
        return "dialling"
    if "in-progress" in statuses or any(d.get("outcome") in _REACHED for d in dials):
        return "reached"
    due = [_instant(d.get("due_at")) for d in dials if d.get("status") == "due"]
    if any(due):
        nearest = min(d for d in due if d is not None)
        return (
            f"waiting for the window: next dial {central(nearest.isoformat())}"
            if nearest > now
            else "due to dial"
        )
    if dials:
        return f"not reached after {len(dials)} {'attempt' if len(dials) == 1 else 'attempts'}"
    return "no dial scheduled"


def spoken_answer(question: Mapping[str, Any], value: object) -> str:
    """A recorded value in the words the line said it back with (spec 9.9)."""
    words = {"yes": "yes", "no": "no", "declined": "skipped", "unclear": "not clear"}
    text = str(value or "")
    if text in words:
        return words[text]
    for option in question.get("options") or []:
        if str(option.get("id")) == text:
            return str(option.get("say") or text)
    unit = (question.get("range") or {}).get("unit")
    return f"{text} {unit}" if unit and text.isdigit() else text


def _screening_call(state: Mapping[str, Any], code: str) -> str | None:
    """The call a read or a call-back is logged against: the screen's call, or the latest answer's."""
    by_question, screen = _answers(state, code)
    if screen is not None and screen.get("call_id"):
        return str(screen["call_id"])
    calls = [r.get("call_id") for r in sorted(by_question.values(), key=lambda r: str(r.get("at")))]
    return next((str(c) for c in reversed(calls) if c), None)


def outcome_words(
    state: Mapping[str, Any], app: Mapping[str, Any], role: Mapping[str, Any], slot_labels: Mapping[str, str]
) -> str:
    """What the line did, in plain words for the recruiter. Never passed, failed, qualified or rejected: a person
    reads the answers and decides the application."""
    code = str(app.get("code"))
    by_question, screen = _answers(state, code)
    posted = [str(q.get("id")) for q in role.get("questions") or []]
    answered = sum(1 for q in posted if q in by_question)
    opted = _opt_out(state, app)
    stop = (
        f" The applicant asked for no more calls ({opted.get('how')}, {central(opted.get('at'))})."
        if opted
        else ""
    )
    if screen is None:
        if not answered:
            return "No answers recorded yet." + stop
        return (
            f"{answered} of {len(posted)} posted questions answered; the questions were not finished." + stop
        )
    booked = _booked(state, code)
    head = "Every posted question was answered."
    if booked:
        return f"{head} The line booked an interview: {slot_labels.get(booked, booked)}.{stop}"
    promised = screen.get("promised_by")
    if screen.get("result") == "met" and promised:
        return f"{head} No interview time was open, so the line promised a recruiter call by {central(promised)}.{stop}"
    if screen.get("result") == "met":
        return f"{head} The line offered interview times; none is booked yet.{stop}"
    return (
        f"{head} The line booked nothing and promised a recruiter call by {central(promised)}. A person reads these "
        f"answers and decides the application.{stop}"
    )


def _masked_words(text: object) -> str:
    return _DIGIT_RUN.sub("****", str(text or ""))


def _cell(label: str, value: str) -> str:
    return f"<div><div class='k'>{escape(label)}</div><div class='v'>{value}</div></div>"


def applicants_page(
    state: Mapping[str, Any] | None,
    roles: Mapping[str, Mapping[str, Any]],
    slot_labels: Mapping[str, str],
    applications_path: Path,
    now: datetime,
) -> str:
    subtitle = (
        "Every application in the order it arrived, oldest first. Open one for the posted questions and the "
        "answers the line recorded; a person decides every application."
    )
    nav = "<p><a href='/'>All calls</a></p>"
    if state is None:
        return page(
            "Applicants", f"{nav}<p class='empty'>The line's state file could not be read.</p>", subtitle
        )
    rows = applications(state, applications_path)
    if not rows:
        return page("Applicants", f"{nav}<p class='empty'>No applications yet.</p>", subtitle)
    cells = []
    for app in rows:
        code = str(app.get("code"))
        role = roles.get(str(app.get("role")), {})
        consent = app.get("consent") if isinstance(app.get("consent"), dict) else {}
        agreed = "accepted" if consent.get("accepted") is True else "not accepted"
        attempts = len(_dials(state, code))
        cells.append(
            f"<tr><td><a href='/applicants/{escape(code)}'><code>{escape(code)}</code></a></td>"
            f"<td>{escape(str(app.get('first_name') or ''))}</td>"
            f"<td>{escape(str(role.get('title') or app.get('role') or ''))}</td>"
            f"<td class='when'>{escape(central(app.get('received_at')))}</td>"
            f"<td>{escape(str(consent.get('version') or ''))}, {agreed}</td>"
            f"<td>{escape(line_status(state, app, slot_labels, now))}</td>"
            f"<td class='num'>{attempts}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Code</th><th>First Name</th><th>Role</th><th>Received</th><th>Consent</th>"
        f"<th>The Line's Status</th><th class='num'>Attempts</th></tr></thead><tbody>{''.join(cells)}</tbody></table>"
    )
    return page("Applicants", nav + table, subtitle)


def applicant_page(
    state: Mapping[str, Any],
    app: Mapping[str, Any],
    roles: Mapping[str, Mapping[str, Any]],
    slot_labels: Mapping[str, str],
    now: datetime,
) -> str:
    code = str(app.get("code"))
    role = roles.get(str(app.get("role")), {})
    consent = app.get("consent") if isinstance(app.get("consent"), dict) else {}
    agreed = "accepted" if consent.get("accepted") is True else "not accepted"
    consent_text = (
        f"{escape(str(consent.get('version') or ''))}, {agreed}"
        f" <span class='muted'>{escape(central(consent.get('at')))}, {escape(str(consent.get('source') or ''))}</span>"
    )
    number = escape(str(app.get("number_masked") or "")) or "<span class='muted'>none on record</span>"
    header = (
        "<div class='header'>"
        + _cell("First Name", escape(str(app.get("first_name") or "")))
        + _cell("Code", f"<code>{escape(code)}</code>")
        + _cell("Role", escape(str(role.get("title") or app.get("role") or "")))
        + _cell("Site", escape(str(role.get("site") or "")))
        + _cell("Recruiter", escape(str(role.get("recruiter") or "")))
        + _cell("Received", escape(central(app.get("received_at"))))
        + _cell("Consent", consent_text)
        + _cell("Number", f"<span class='mono'>{number}</span>")
        + "</div>"
    )
    by_question, _ = _answers(state, code)
    rows = []
    for question in role.get("questions") or []:
        qid = str(question.get("id"))
        record = by_question.get(qid)
        if isinstance(record, dict):
            answer = escape(spoken_answer(question, record.get("value")))
            words = escape(_masked_words(record.get("heard")))
            at = escape(central(record.get("at")))
        else:
            answer, words, at = "<span class='muted'>not asked yet</span>", "", ""
        rows.append(
            f"<tr><td><code>{escape(qid)}</code></td><td class='text'>{escape(str(question.get('say') or ''))}</td>"
            f"<td>{escape(str(question.get('asks') or ''))}</td><td>{escape(str(question.get('reason') or ''))}</td>"
            f"<td>{answer}</td><td class='text'>{words}</td><td class='when'>{at}</td></tr>"
        )
    questions = (
        "<table><thead><tr><th>#</th><th>The Question As Said</th><th>The Posting Asks For</th>"
        "<th>The Posted Reason</th><th>Answer</th><th>The Applicant's Words</th><th>When</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    outcome = f"<p>{escape(outcome_words(state, app, role, slot_labels))}</p>"
    dial_rows = []
    for d in sorted(_dials(state, code), key=lambda d: int(d.get("attempt") or 0)):
        sid = d.get("call_sid")
        link = f"<a href='/calls/{escape(str(sid))}'><code>{escape(str(sid))}</code></a>" if sid else ""
        dial_rows.append(
            f"<tr><td class='num'>{escape(str(d.get('attempt') or ''))}</td>"
            f"<td class='when'>{escape(central(d.get('due_at')))}</td><td>{escape(str(d.get('status') or ''))}</td>"
            f"<td>{escape(str(d.get('outcome') or ''))}</td><td>{escape(str(d.get('answered_by') or ''))}</td>"
            f"<td>{'yes' if d.get('voicemail_left') else 'no'}</td><td>{link}</td></tr>"
        )
    dials = (
        "<table><thead><tr><th class='num'>Attempt</th><th>Due</th><th>Status</th><th>Outcome</th>"
        f"<th>Answered By</th><th>Voicemail</th><th>Call</th></tr></thead><tbody>{''.join(dial_rows)}</tbody></table>"
        if dial_rows
        else "<p class='empty'>No dials.</p>"
    )
    call_id = _screening_call(state, code)
    if call_id is None:
        forms = "<p class='empty'>No screening call yet, so there is nothing to log a read or a call-back against.</p>"
    else:
        opened = now.astimezone(UTC).isoformat(timespec="seconds")
        forms = (
            f"<form method='post' action='/applicants/{escape(code)}/read'>"
            f"<input type='hidden' name='opened_at' value='{escape(opened)}'>"
            "<label for='read-by'>Your name</label>"
            "<input id='read-by' name='by' placeholder='your name' maxlength='80' required> "
            "<button>I read the answers</button></form>"
            f"<form method='post' action='/applicants/{escape(code)}/called-back' style='margin-top:10px'>"
            "<label for='called-by'>Your name</label>"
            "<input id='called-by' name='by' placeholder='your name' maxlength='80' required> "
            "<button>I called the applicant back</button></form>"
        )
    body = (
        "<p><a href='/applicants'>All applicants</a> · <a href='/'>All calls</a></p>"
        f"{header}<h2>The Posted Questions</h2>{questions}<h2>What The Line Did</h2>{outcome}"
        f"<h2>Dials</h2>{dials}<h2>Log It</h2>{forms}"
    )
    return page(f"{app.get('first_name') or 'Applicant'} ({code})", body)


def create_cockpit(
    store: TraceStore,
    state_path: Path | None = None,
    applications_path: Path = APPLICATIONS_PATH,
    roles_path: Path = ROLES_PATH,
    now: Callable[[], datetime] | None = None,
) -> FastAPI:
    app = FastAPI(title="Candidate Line cockpit", docs_url=None, redoc_url=None, openapi_url=None)
    clock = now or (lambda: datetime.now(UTC))

    @app.get("/", response_class=HTMLResponse)
    def calls() -> str:
        rows = store.calls()
        subtitle = "Every call the line has taken, newest first. Open a call for its steps and its hand-offs."
        if not rows:
            return page(
                "Calls",
                "<p class='empty'>No calls yet. The steps are written live from the turn loop (DR-012).</p>",
                subtitle,
            )
        cells = "".join(call_cells(r) for r in rows)
        return page(
            "Calls",
            "<p><a href='/applicants'>Applicants</a></p>"
            "<table><thead><tr><th>Started</th><th>Call</th><th>Channel</th><th>Caller</th><th>Brain</th>"
            "<th class='num'>Steps</th><th class='num'>Model Time</th><th class='num'>Tier</th>"
            "<th class='num'>Hand-Offs</th><th>Outcome</th></tr></thead>"
            f"<tbody>{cells}</tbody></table>",
            subtitle,
        )

    @app.get("/calls/{call_id}", response_class=HTMLResponse)
    def call(call_id: str) -> str:
        spans = store.spans(call_id)
        escalations = store.escalations(call_id)
        row = store.call(call_id)
        if row is None and not spans and not escalations:
            raise HTTPException(status_code=404, detail="no such call")
        header = ""
        if row is not None:
            ended = when(row.ended_at) if row.ended_at else "still open"
            header = (
                "<div class='header'>"
                f"<div><div class='k'>Started</div><div class='v'>{escape(when(row.started_at))}</div></div>"
                f"<div><div class='k'>Ended</div><div class='v'>{escape(ended)}</div></div>"
                f"<div><div class='k'>Channel</div><div class='v'>{pill(row.channel)}"
                + (
                    f" <span class='mono muted'>{escape(row.caller_masked)}</span>"
                    if row.caller_masked
                    else ""
                )
                + "</div></div>"
                f"<div><div class='k'>Brain</div><div class='v'>{brain(row)}</div></div>"
                f"<div><div class='k'>Outcome</div><div class='v'>{escape(row.outcome or '') or '<span class=muted>not recorded</span>'}</div></div>"
                "</div>"
            )
        if spans:
            steps = (
                "<table><thead><tr><th class='num'>#</th><th>Kind</th><th>Name</th><th>Text</th><th class='num'>Ms</th>"
                "<th class='num'>Tokens In / Out</th><th class='num'>Chars</th><th class='num'>Seconds</th><th>Meta</th></tr></thead>"
                f"<tbody>{''.join(span_cells(s) for s in spans)}</tbody></table>"
            )
        else:
            steps = "<p class='empty'>No steps recorded yet. The steps are written live from the turn loop (DR-012).</p>"
        if escalations:
            hand_offs = (
                "<table><thead><tr><th class='num'>#</th><th>Tier</th><th>Why</th><th>Suggested Action</th><th>Posted</th><th>Reply</th></tr></thead>"
                f"<tbody>{''.join(escalation_cells(e) for e in escalations)}</tbody></table>"
            )
        else:
            hand_offs = "<p class='empty'>None.</p>"
        body = f"<p><a href='/'>All calls</a></p>{header}<h2>Steps</h2>{steps}<h2>Hand-Offs</h2>{hand_offs}"
        return page(f"Call {call_id}", body)

    @app.post("/escalations/{escalation_id}/reply")
    def reply(escalation_id: int, reply: str = Form(...), by: str = Form(...)) -> RedirectResponse:
        matching = [e for e in store.escalations() if e.id == escalation_id]
        if not matching:
            raise HTTPException(status_code=404, detail="no such escalation")
        store.reply(escalation_id, reply.strip(), by.strip())
        return RedirectResponse(url=f"/calls/{matching[0].call_id}", status_code=303)

    def _one(code: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not _CODE.fullmatch(code):
            raise HTTPException(status_code=404, detail="no such applicant")
        state = read_state(state_path)
        if state is None:
            raise HTTPException(status_code=503, detail="the state file could not be read")
        found = next((a for a in applications(state, applications_path) if a.get("code") == code), None)
        if found is None:
            raise HTTPException(status_code=404, detail="no such applicant")
        return state, found

    def _by(by: str) -> str:
        name = re.sub(r"\s+", " ", by).strip()
        if not name or len(name) > 80:
            raise HTTPException(status_code=422, detail="your name, at most 80 characters")
        return name

    @app.get("/applicants", response_class=HTMLResponse)
    def applicants_list() -> str:
        roles, labels = read_roles(roles_path)
        return applicants_page(read_state(state_path), roles, labels, applications_path, clock())

    @app.get("/applicants/{code}", response_class=HTMLResponse)
    def applicant(code: str) -> str:
        state, found = _one(code)
        roles, labels = read_roles(roles_path)
        return applicant_page(state, found, roles, labels, clock())

    @app.post("/applicants/{code}/read")
    def read(code: str, by: str = Form(...), opened_at: str = Form(...)) -> RedirectResponse:
        """A read logged as a hook span on the screening call, with how long the page was open, for the
        minutes-saved row of the scorecard (DR-025 section 17)."""
        state, _ = _one(code)
        call_id = _screening_call(state, code)
        opened = _instant(opened_at)
        if call_id is None or opened is None:
            raise HTTPException(status_code=422, detail="no screening call to log a read against")
        seconds = min(max(round((clock() - opened).total_seconds()), 0), MAX_READ_SECONDS)
        name = _by(by)
        store.span(
            call_id,
            "hook",
            "read",
            text=f"{name} read the answers of {code}",
            seconds=float(seconds),
            meta={"code": code, "by": name, "opened_at": opened.isoformat(), "read_seconds": seconds},
        )
        return RedirectResponse(url=f"/applicants/{code}", status_code=303)

    @app.post("/applicants/{code}/called-back")
    def called_back(code: str, by: str = Form(...)) -> RedirectResponse:
        """A call-back logged as a hook span on the screening call, and as the reply to its screening hand-off, so
        the promise row can read whether the call came inside the promised time (DR-025 section 17)."""
        state, _ = _one(code)
        call_id = _screening_call(state, code)
        if call_id is None:
            raise HTTPException(status_code=422, detail="no screening call to log a call-back against")
        name, at = _by(by), clock().astimezone(UTC).isoformat(timespec="seconds")
        store.span(
            call_id,
            "hook",
            "called_back",
            text=f"{name} called {code} back",
            meta={"code": code, "by": name, "called_at": at},
        )
        for e in store.escalations(call_id):
            if e.reason.startswith("screening hand-off") and not e.reply:
                store.reply(e.id, "called the applicant back", name)
        return RedirectResponse(url=f"/applicants/{code}", status_code=303)

    return app


def app() -> FastAPI:
    settings = Settings.from_env()
    state = Path(settings.state_path) if settings.state_path else None
    return create_cockpit(TraceStore(settings.trace_store_path or DEFAULT_PATH), state_path=state)
