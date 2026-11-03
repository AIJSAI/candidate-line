#!/bin/sh
# Stops what scripts/up.sh started, by the pids it wrote; nothing public stays running. `uv run` forwards the
# signal to uvicorn, which takes a second or two to let go of port 8000; the last line waits for that, so the
# listing it prints is what is still running, not what is still exiting (the first drill of 2026-11-03 printed
# the dying child and read as a leak).
cd "$(dirname "$0")/.."
for f in var/line.pid var/tunnel.pid; do
  [ -f "$f" ] || continue
  pid="$(cat "$f")"; kill "$pid" 2>/dev/null && echo "stopped $(basename "$f" .pid) ($pid)" || echo "$(basename "$f" .pid) was not running"
  rm -f "$f"
done
for _ in $(seq 1 40); do lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.25; done
pgrep -fl 'uvicorn candidate_line|cloudflared tunnel --url http://127.0.0.1:8000' || echo "nothing of the line left running"
