#!/bin/sh
# Stops what scripts/up.sh started, by the pids it wrote; nothing public stays running.
cd "$(dirname "$0")/.."
for f in var/line.pid var/tunnel.pid; do
  [ -f "$f" ] || continue
  pid="$(cat "$f")"; kill "$pid" 2>/dev/null && echo "stopped $(basename "$f" .pid) ($pid)" || echo "$(basename "$f" .pid) was not running"
  rm -f "$f"
done
pgrep -fl 'uvicorn candidate_line|cloudflared tunnel --url http://127.0.0.1:8000' || echo "nothing of the line left running"
