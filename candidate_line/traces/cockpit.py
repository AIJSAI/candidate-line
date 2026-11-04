"""The recruiter's cockpit: one page that lists the calls, one per call, and a reply box per escalation.

Why its own app on its own port: it is for the recruiter, never for a candidate, so it is served on the loopback
(`make cockpit`, 127.0.0.1:8001) and never behind the tunnel. Why no template engine: two pages, every value
escaped by hand in one place. The styling is inline and the pages carry no script, so the cockpit works with no
network at all; the handlers and the form are what card 06 wires into, so they stay as they are.
"""

from __future__ import annotations

from html import escape

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from candidate_line.settings import Settings
from candidate_line.traces.store import DEFAULT_PATH, CallRow, EscalationRow, SpanRow, TraceStore

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
    return (
        f"<tr><td class='when'>{escape(when(r.started_at))}</td>"
        f"<td><a href='/calls/{escape(r.call_id)}'><code>{escape(r.call_id)}</code></a></td>"
        f"<td>{pill(r.channel)}</td><td class='mono caller'>{escape(r.caller_masked or '')}</td><td>{brain(r)}</td>"
        f"<td class='num'>{steps}</td><td class='num'>{model_ms}</td><td class='num'>{hand_offs}</td>"
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


def create_cockpit(store: TraceStore) -> FastAPI:
    app = FastAPI(title="Candidate Line cockpit", docs_url=None, redoc_url=None, openapi_url=None)

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
            "<table><thead><tr><th>Started</th><th>Call</th><th>Channel</th><th>Caller</th><th>Brain</th>"
            "<th class='num'>Steps</th><th class='num'>Model Time</th><th class='num'>Hand-Offs</th><th>Outcome</th></tr></thead>"
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
                + (f" <span class='mono muted'>{escape(row.caller_masked)}</span>" if row.caller_masked else "")
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

    return app


def app() -> FastAPI:
    return create_cockpit(TraceStore(Settings.from_env().trace_store_path or DEFAULT_PATH))
