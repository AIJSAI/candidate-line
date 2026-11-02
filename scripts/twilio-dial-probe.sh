#!/bin/sh
# Places the probe's call: Twilio dials the line's number from the probe's own number (a second number, James's
# money call, DR-011) and connects the call's media to the probe's WebSocket at "$1/probe-media".
# Credentials and numbers come from the environment (scripts/env.sh); nothing here is in the repository.
set -eu
probe_base="${1:?usage: scripts/twilio-dial-probe.sh https://probe-public-host}"
: "${TWILIO_ACCOUNT_SID:?}" "${TWILIO_AUTH_TOKEN:?}" "${TWILIO_LINE_NUMBER:?E.164 number of the line}" "${TWILIO_PROBE_NUMBER:?E.164 number the probe calls from}"
wss="$(printf '%s' "$probe_base" | sed -e 's#^https://#wss://#' -e 's#^http://#ws://#')"
curl -sS -X POST "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Calls.json" \
  -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  --data-urlencode "To=$TWILIO_LINE_NUMBER" --data-urlencode "From=$TWILIO_PROBE_NUMBER" \
  --data-urlencode "Twiml=<Response><Connect><Stream url=\"$wss/probe-media\" /></Connect></Response>" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("call:", d.get("status") or d.get("message"))'
