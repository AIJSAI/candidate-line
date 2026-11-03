"""The recruiter's cockpit: one page that lists the calls, one per call, and a reply box per escalation.

Why its own app on its own port: it is for the recruiter, never for a candidate, so it is served on the loopback
(`make cockpit`, 127.0.0.1:8001) and never behind the tunnel. Why no template engine: two pages, every value
escaped by hand in one place.
"""

from __future__ import annotations

from html import escape

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from candidate_line.settings import Settings
from candidate_line.traces.store import DEFAULT_PATH, TraceStore

STYLE = (
    "<style>body{font:14px/1.4 -apple-system,system-ui,sans-serif;margin:2rem;color:#222}"
    "table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:.3rem .6rem;text-align:left;vertical-align:top}"
    "th{background:#f4f4f4}code{font-size:12px}.muted{color:#777}form{margin:0}</style>"
)


def page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>{STYLE}</head><body><h1>{escape(title)}</h1>{body}</body></html>"


def create_cockpit(store: TraceStore) -> FastAPI:
    app = FastAPI(title="Candidate Line cockpit", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def calls() -> str:
        rows = store.calls()
        if not rows:
            return page(
                "Calls",
                "<p class='muted'>No calls yet. The spans are written live from the turn loop (DR-012).</p>",
            )
        cells = "".join(
            f"<tr><td>{escape(r.started_at)}</td><td><a href='/calls/{escape(r.call_id)}'><code>{escape(r.call_id)}</code></a></td>"
            f"<td>{escape(r.channel)}</td><td>{escape(r.caller_masked or '')}</td><td>{escape(r.provider or '')} {escape(r.model or '')}</td>"
            f"<td>{r.span_count}</td><td>{r.model_ms}</td><td>{r.escalations}</td><td>{escape(r.outcome or '')}</td></tr>"
            for r in rows
        )
        return page(
            "Calls",
            "<table><tr><th>Started (UTC)</th><th>Call</th><th>Channel</th><th>Caller</th><th>Brain</th><th>Spans</th><th>Model ms</th><th>Escalations</th><th>Outcome</th></tr>"
            + cells
            + "</table>",
        )

    @app.get("/calls/{call_id}", response_class=HTMLResponse)
    def call(call_id: str) -> str:
        spans = store.spans(call_id)
        escalations = store.escalations(call_id)
        if not spans and not escalations:
            raise HTTPException(status_code=404, detail="no such call")
        span_rows = "".join(
            f"<tr><td>{s.seq}</td><td>{escape(s.kind)}</td><td>{escape(s.name)}</td><td>{s.ms if s.ms is not None else ''}</td>"
            f"<td>{s.tokens_in if s.tokens_in is not None else ''}/{s.tokens_out if s.tokens_out is not None else ''}</td>"
            f"<td>{s.chars if s.chars is not None else ''}</td><td>{s.seconds if s.seconds is not None else ''}</td>"
            f"<td>{escape(s.text or '')}</td><td class='muted'><code>{escape(str(s.meta)) if s.meta else ''}</code></td></tr>"
            for s in spans
        )
        esc_rows = "".join(
            f"<tr><td>{e.id}</td><td>{escape(e.tier)}</td><td>{escape(e.reason)}</td><td>{escape(e.suggested_action)}</td>"
            f"<td>{escape(e.channel)} {escape(e.posted_at or '')} {escape(e.post_error or '')}</td>"
            + (
                f"<td>{escape(e.reply)} <span class='muted'>({escape(e.replied_by or '')}, {escape(e.replied_at or '')})</span></td>"
                if e.reply
                else f"<td><form method='post' action='/escalations/{e.id}/reply'><input name='reply' placeholder='what you did' required> "
                f"<input name='by' placeholder='your name' required> <button>Log reply</button></form></td>"
            )
            + "</tr>"
            for e in escalations
        )
        body = (
            "<p><a href='/'>All calls</a></p><h2>Spans</h2>"
            "<table><tr><th>#</th><th>Kind</th><th>Name</th><th>ms</th><th>Tokens in/out</th><th>Chars</th><th>Seconds</th><th>Text</th><th>Meta</th></tr>"
            + span_rows
            + "</table><h2>Escalations</h2>"
            + (
                "<table><tr><th>#</th><th>Tier</th><th>Why</th><th>Suggested action</th><th>Posted</th><th>Reply</th></tr>"
                + esc_rows
                + "</table>"
                if esc_rows
                else "<p class='muted'>None.</p>"
            )
        )
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
