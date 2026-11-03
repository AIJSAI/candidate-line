# Candidate Line. The targets the build plan names. Each is a stub that says "not yet" and
# exits non-zero, so no tool can read a stub as a pass, until its Sunday item replaces it.
# `make trace last` passes `last` as a second goal, so `last` is a no-op target here.

.PHONY: help up down restart dev tunnel webhook cockpit probe probe-dial bakeoff test secret eval gate trace text last

help:
	@echo "make up          a build day in one command: tunnel, line on the Identity Center profile, number re-pointed, health"
	@echo "make down        stops what make up started"
	@echo "make restart     restarts only the line process on the new code; the tunnel and the webhook stay"
	@echo "make dev         the webhook on 127.0.0.1:8000, secrets from the login keychain"
	@echo "make tunnel      a quick cloudflared tunnel to port 8000 (prints the public hostname)"
	@echo "make webhook URL=https://host [PATH_=/incoming-call]   point the Twilio number at URL/voice (arm A) or URL/incoming-call (arm B)"
	@echo "make cockpit     the recruiter's list of calls on 127.0.0.1:8001 (loopback only)"
	@echo "make probe CASE=evals/cases/x.yaml [URL=ws://127.0.0.1:8000/media]   a synthetic candidate talks to the line as speech"
	@echo "make probe-dial CASE=bakeoff/cases/x.yaml PUBLIC=https://probe-host ARM=A|B   the probe places a real call, records it, measures both ways"
	@echo "make bakeoff PUBLIC=https://probe-host ARM=A|B   every case in bakeoff/cases through a real call"
	@echo "make test        pytest"
	@echo "make secret NAME=VAR   store the clipboard as VAR in the login keychain, then clear it"
	@echo "make eval        run the eval cases"
	@echo "make gate        the tests, the evals and the cost line; required before done"
	@echo "make trace last  the latest call's spans, in the terminal"
	@echo "make text        the line in text mode (BRAIN_PROVIDER / BEDROCK_MODEL_ID from the environment)"

up:
	scripts/up.sh

down:
	scripts/down.sh

restart:
	scripts/restart-line.sh

dev:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run uvicorn candidate_line.telephony.app:app --host 127.0.0.1 --port 8000 --reload

tunnel:
	cloudflared tunnel --url http://127.0.0.1:8000

webhook:
	. scripts/env.sh && scripts/twilio-webhook.sh "$(URL)" "$(or $(PATH_),/voice)"

cockpit:
	uv run uvicorn --factory candidate_line.traces.cockpit:app --host 127.0.0.1 --port 8001

probe:
	. scripts/env.sh && uv run python -m candidate_line.probe.direct --case "$(CASE)" --url "$(or $(URL),ws://127.0.0.1:8000/media)"

probe-dial:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.probe.dial --case "$(CASE)" --public-url "$(PUBLIC)" --arm "$(or $(ARM),A)" --csv "$(or $(CSV),bakeoff/2026-11-01.csv)"

bakeoff:
	@for c in bakeoff/cases/*.yaml; do echo "== $$c"; $(MAKE) --no-print-directory probe-dial CASE=$$c PUBLIC="$(PUBLIC)" ARM="$(ARM)" || true; done

test:
	uv run pytest -q

secret:
	scripts/secret-set.sh "$(NAME)"

eval:
	. scripts/env.sh && uv run python -m candidate_line.evals.runner

gate: test
	@. scripts/env.sh && uv run python -m candidate_line.evals.runner && echo "gate: green (tests and evals; the cost line is in the eval report once cases exist)" || { echo "gate: RED. Boundary failures above. From card 02 until card 04 lands they must be exactly the ids named in DR-017 (AGENTS.md rule 8); any other red is a stop."; exit 1; }

trace:
	uv run python -m candidate_line.traces.cli $(filter-out $@,$(MAKECMDGOALS))

text:
	. scripts/env.sh && uv run python -m candidate_line.text_mode

last:
	@:
