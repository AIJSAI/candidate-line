#!/bin/sh
# Restarts only the line process and keeps the tunnel and the Twilio webhook as they are: the quick tunnel
# forwards to port 8000, so a new uvicorn on 8000 is public the moment /health answers. In the room the cards
# land while the line is up, and `make up` runs without --reload on purpose (a reload on every file the tool
# saves would drop a caller mid-call), so this one command is how new code reaches the phone. Pids and logs
# live under var/ as scripts/up.sh leaves them; `uv run` keeps uvicorn as a child, so the child goes first.
set -eu
cd "$(dirname "$0")/.."
. scripts/env.sh
mkdir -p var
host="${PUBLIC_BASE_URL:-}"
[ -n "$host" ] || host="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' var/tunnel.log 2>/dev/null | head -1 || true)"
[ -n "$host" ] || { echo "no public host: run make up first, or set PUBLIC_BASE_URL"; exit 1; }
if [ -f var/line.pid ]; then
  pid="$(cat var/line.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    echo "stopped line ($pid)"
  fi
  rm -f var/line.pid
fi
for _ in $(seq 1 20); do lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.25; done
# A listener that is not ours would answer the health check below and pass off the old code as the new.
holder="$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
[ -z "$holder" ] || { echo "port 8000 is held by pid $holder, which make up did not start; stop it first"; exit 1; }
AWS_PROFILE="${AWS_PROFILE:-candidate-line}" PUBLIC_BASE_URL="$host" BRAIN_PROVIDER="${BRAIN_PROVIDER:-anthropic}" \
  uv run uvicorn candidate_line.telephony.app:app --host 127.0.0.1 --port 8000 >> var/line.log 2>&1 &
echo $! > var/line.pid
for _ in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8000/health && break; sleep 0.5; done
echo "line:   $(curl -s http://127.0.0.1:8000/health) (pid $(cat var/line.pid), public $host)"
