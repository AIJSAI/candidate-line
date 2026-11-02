# Candidate Line. The targets the build plan names. Each is a stub that says "not yet" and
# exits non-zero, so no tool can read a stub as a pass, until its Sunday item replaces it.
# `make trace last` passes `last` as a second goal, so `last` is a no-op target here.

.PHONY: help dev tunnel webhook test secret eval gate trace text last

help:
	@echo "make dev         the webhook on 127.0.0.1:8000, secrets from the login keychain"
	@echo "make tunnel      a quick cloudflared tunnel to port 8000 (prints the public hostname)"
	@echo "make webhook URL=https://host   point the Twilio number at URL/voice"
	@echo "make test        pytest"
	@echo "make secret NAME=VAR   store the clipboard as VAR in the login keychain, then clear it"
	@echo "make eval        run the eval cases"
	@echo "make gate        the tests, the evals and the cost line; required before done"
	@echo "make trace last  the latest call's trace"
	@echo "make text        the line in text mode (BRAIN_PROVIDER / BEDROCK_MODEL_ID from the environment)"

dev:
	. scripts/env.sh && uv run uvicorn candidate_line.telephony.app:app --host 127.0.0.1 --port 8000 --reload

tunnel:
	cloudflared tunnel --url http://127.0.0.1:8000

webhook:
	. scripts/env.sh && scripts/twilio-webhook.sh "$(URL)"

test:
	uv run pytest -q

secret:
	scripts/secret-set.sh "$(NAME)"

eval:
	@echo "not yet: the eval runner lands Sunday (KICKOFF.md, item 12)"; exit 1

gate:
	@echo "not yet: make gate lands with the eval runner (KICKOFF.md, item 12)"; exit 1

trace:
	@echo "not yet: the trace store lands Sunday (KICKOFF.md, item 14); its spans are written live"; exit 1

text:
	. scripts/env.sh && uv run python -m candidate_line.text_mode

last:
	@:
