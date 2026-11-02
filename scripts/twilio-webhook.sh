#!/bin/sh
# Points the Twilio number's voice webhook at "$1$2" ($2 defaults to /voice, arm A; arm B's sample answers on
# /incoming-call). Credentials come from the environment (scripts/env.sh), so the account and number ids never appear
# in this repository. This is the one command of the re-point drill and of the bake-off's arm switch.
set -eu
base="${1:?usage: scripts/twilio-webhook.sh https://public-host [/path]}"
path="${2:-/voice}"
: "${TWILIO_ACCOUNT_SID:?set it with make secret NAME=TWILIO_ACCOUNT_SID}"
: "${TWILIO_AUTH_TOKEN:?set it with make secret NAME=TWILIO_AUTH_TOKEN}"
: "${TWILIO_NUMBER_SID:?set it with make secret NAME=TWILIO_NUMBER_SID}"
curl -sS -X POST "https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/IncomingPhoneNumbers/$TWILIO_NUMBER_SID.json" \
  -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
  --data-urlencode "VoiceUrl=$base$path" --data-urlencode "VoiceMethod=POST" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("voice_url:", d.get("voice_url") or d.get("message"))'
