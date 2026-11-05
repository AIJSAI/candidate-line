# The line in one container: the same FastAPI app the Mac runs, on Python 3.12 (audioop left the standard library
# in 3.13, DR-004). Built for linux/arm64 (Fargate on Graviton) with x86 as the fallback; uv installs the locked
# dependencies into a venv as a non-root user. No secret is baked in: the keys arrive as environment variables at
# start (Secrets Manager in the deployment, docs/deploy/PLAN.md), and var/ is a mounted volume so the trace store
# and the ledger outlive a restart.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/
RUN useradd --create-home --uid 10001 line
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY candidate_line ./candidate_line
COPY data ./data
COPY scripts/env.sh scripts/container-start.sh ./scripts/
RUN mkdir -p /app/var && chown -R line:line /app
USER line
ENV PATH="/app/.venv/bin:$PATH" TRACE_STORE_PATH=/app/var/traces.sqlite STATE_PATH=/app/var/state.json
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["sh", "scripts/container-start.sh"]
