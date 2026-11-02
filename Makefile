# Candidate Line. The targets the build plan names. Each is a stub that says "not yet" and
# exits non-zero, so no tool can read a stub as a pass, until its Sunday item replaces it.
# `make trace last` passes `last` as a second goal, so `last` is a no-op target here.

.PHONY: help dev tunnel webhook cockpit test secret eval gate trace text last

help:
	@echo "make dev         the webhook on 127.0.0.1:8000, secrets from the login keychain"
	@echo "make tunnel      a quick cloudflared tunnel to port 8000 (prints the public hostname)"
	@echo "make webhook URL=https://host   point the Twilio number at URL/voice"
	@echo "make cockpit     the recruiter's list of calls on 127.0.0.1:8001 (loopback only)"
	@echo "make test        pytest"
	@echo "make secret NAME=VAR   store the clipboard as VAR in the login keychain, then clear it"
	@echo "make eval        run the eval cases"
	@echo "make gate        the tests, the evals and the cost line; required before done"
	@echo "make trace last  the latest call's spans, in the terminal"
	@echo "make text        the line in text mode (BRAIN_PROVIDER / BEDROCK_MODEL_ID from the environment)"

dev:
	. scripts/env.sh && uv run uvicorn candidate_line.telephony.app:app --host 127.0.0.1 --port 8000 --reload

tunnel:
	cloudflared tunnel --url http://127.0.0.1:8000

webhook:
	. scripts/env.sh && scripts/twilio-webhook.sh "$(URL)"

cockpit:
	uv run uvicorn --factory candidate_line.traces.cockpit:app --host 127.0.0.1 --port 8001

test:
	uv run pytest -q

secret:
	scripts/secret-set.sh "$(NAME)"

eval:
	. scripts/env.sh && uv run python -m candidate_line.evals.runner

gate: test eval
	@echo "gate: tests and evals green; the cost line is in the eval report above"

trace:
	uv run python -m candidate_line.traces.cli $(filter-out $@,$(MAKECMDGOALS))

text:
	. scripts/env.sh && uv run python -m candidate_line.text_mode

last:
	@:
