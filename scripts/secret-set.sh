#!/bin/sh
# Stores the clipboard's contents in the login keychain as service candidate-line, account $1, then clears the
# clipboard. The value is never echoed and never passes through a file.
set -eu
name="${1:?usage: scripts/secret-set.sh NAME}"
value="$(pbpaste | tr -d '\r\n')"
[ -n "$value" ] || { echo "the clipboard is empty; copy the value first" >&2; exit 1; }
security add-generic-password -U -s candidate-line -a "$name" -w "$value"
printf '' | pbcopy
echo "stored $name (${#value} characters) in the login keychain; clipboard cleared"
