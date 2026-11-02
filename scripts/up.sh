#!/bin/sh
# One command for a build day: the quick tunnel, the line on the Identity Center profile, the Twilio number
# re-pointed at the new hostname, and a health check on both ends. Pids and logs live under var/ (ignored by git).
# `scripts/down.sh` stops what this started. Secrets come from the login keychain (scripts/env.sh).
set -eu
cd "$(dirname "$0")/.."
. scripts/env.sh
mkdir -p var
if [ -f var/tunnel.pid ] && kill -0 "$(cat var/tunnel.pid)" 2>/dev/null; then echo "tunnel already up (pid $(cat var/tunnel.pid)); run scripts/down.sh first"; exit 1; fi
cloudflared tunnel --url http://127.0.0.1:8000 > var/tunnel.log 2>&1 &
echo $! > var/tunnel.pid
host=""
for _ in $(seq 1 30); do host="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' var/tunnel.log | head -1 || true)"; [ -n "$host" ] && break; sleep 1; done
[ -n "$host" ] || { echo "no tunnel hostname in 30 s; see var/tunnel.log"; exit 1; }
AWS_PROFILE="${AWS_PROFILE:-candidate-line}" PUBLIC_BASE_URL="$host" BRAIN_PROVIDER="${BRAIN_PROVIDER:-anthropic}" \
  uv run uvicorn candidate_line.telephony.app:app --host 127.0.0.1 --port 8000 > var/line.log 2>&1 &
echo $! > var/line.pid
for _ in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8000/health && break; sleep 0.5; done
echo "line:   $(curl -s http://127.0.0.1:8000/health)"
for _ in $(seq 1 20); do code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$host/health" || true)"; [ "$code" = "200" ] && break; sleep 3; done
echo "public: $code at $host"
[ "$code" = "200" ] || { echo "the tunnel is not answering yet; try again in a minute or run make webhook URL=$host by hand"; exit 1; }
scripts/twilio-webhook.sh "$host" /voice
echo "dial:   ${TWILIO_LINE_NUMBER:-the line's number (not in the keychain)}"
