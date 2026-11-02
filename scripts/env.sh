# Exports the line's secrets from the macOS login keychain into the current shell. Source it; never print it.
# Store a value first with `make secret NAME=<VAR>` (reads the clipboard, then clears it). 1Password holds the
# human copy; the keychain is the machine copy; nothing is ever in a file (AGENTS.md rule 7).
for name in ANTHROPIC_API_KEY TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_NUMBER_SID SLACK_WEBHOOK_URL; do
  value="$(security find-generic-password -s candidate-line -a "$name" -w 2>/dev/null)" || continue
  [ -n "$value" ] && export "$name=$value"
done
unset name value
