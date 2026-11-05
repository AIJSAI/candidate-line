# Candidate Line. The targets the build plan names; each one is real now (see PREBUILT.md for when it landed).
# `make trace last` passes `last` as a second goal, so `last` is a no-op target here.

.PHONY: help up down restart dev tunnel webhook cockpit probe probe-dial probe-answer bakeoff test secret eval baseline gate scorecard trace text last image deploy cockpit-forward line-off line-on dial-off dial-on apply forget

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
	@echo "make probe-answer PUBLIC=https://probe-host WATCHED=1 [LINE=https://line-host]   the probe applies for its own number and answers the line's call, met then not met; James watching (DR-025)"
	@echo "make bakeoff PUBLIC=https://probe-host ARM=A|B   every case in bakeoff/cases through a real call"
	@echo "make test        pytest"
	@echo "make secret NAME=VAR   store the clipboard as VAR in the login keychain, then clear it"
	@echo "make eval        run the eval cases"
	@echo "make baseline    run the eval cases and write evals/baseline.json from the run (refused on a boundary failure)"
	@echo "make gate        the tests, the evals and the cost line; required before done"
	@echo "make scorecard   what the line did, each number with its method and n (TRACE_STORE_PATH, STATE_PATH)"
	@echo "make trace last  the latest call's spans, in the terminal"
	@echo "make text        the line in text mode (BRAIN_PROVIDER / BEDROCK_MODEL_ID from the environment)"
	@echo "make image       build the container image for linux/arm64 from the committed head (docs/deploy/PLAN.md)"
	@echo "make deploy STEP=ecr|push|secrets|stack|url|status|probe-url   one step of scripts/deploy.sh against the AWS stack (DR-023)"
	@echo "make line-off / line-on    the kill switch on the task: every call hears the closing line, and the dialler stops"
	@echo "make dial-off / dial-on    the dialler's own stop on the task (var/no-dial); calls in go on (DR-025)"
	@echo "make apply PIN=dddd [URL=http://127.0.0.1:8000] [PHONE=probe] [ROLE=care-aide] [FIRST=Ama] [ZONE=America/Chicago]   a signed synthetic application for a walk"
	@echo "make forget CODE=ACME-dddd [WHERE=local]   a deletion request: the application, its answers, its dials and its number"

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
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.probe.direct --case "$(CASE)" --url "$(or $(URL),ws://127.0.0.1:8000/media)"

probe-dial:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.probe.dial --case "$(CASE)" --public-url "$(PUBLIC)" --arm "$(or $(ARM),A)" --csv "$(or $(CSV),bakeoff/2026-11-01.csv)"

# The outbound call's live check (card 08, lane B). It rings a real line and spends money, so the probe refuses
# to run without --watched, and this target passes that only when the command line says WATCHED=1.
probe-answer:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.probe.dial --answer $(if $(and $(filter command line,$(origin WATCHED)),$(filter 1,$(WATCHED))),--watched) --public-url "$(PUBLIC)" $(if $(LINE),--line-url "$(LINE)")

bakeoff:
	@for c in bakeoff/cases/*.yaml; do echo "== $$c"; $(MAKE) --no-print-directory probe-dial CASE=$$c PUBLIC="$(PUBLIC)" ARM="$(ARM)" || true; done

test:
	uv run pytest -q

secret:
	scripts/secret-set.sh "$(NAME)"

eval:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.evals.runner

baseline:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.evals.runner --write-baseline

gate: test
	@. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.evals.runner && echo "gate: green (tests and evals; the cost line is in the eval report once cases exist)" || { echo "gate: RED. Boundary failures above. From card 02 until card 04 lands they must be exactly the ids named in DR-017 (AGENTS.md rule 8); any other red is a stop."; exit 1; }

# No secrets and no model call: the page reads the trace store, the ledger file, rates.py and the baseline CSV.
scorecard:
	uv run python -m candidate_line.scorecard

trace:
	uv run python -m candidate_line.traces.cli $(filter-out $@,$(MAKECMDGOALS))

text:
	. scripts/env.sh && AWS_PROFILE=$${AWS_PROFILE:-candidate-line} uv run python -m candidate_line.text_mode

last:
	@:

# The container: the image is built from the committed head, never the working tree, so the tag names what runs.
image:
	@sha=$$(git rev-parse --short HEAD); git archive --format=tar HEAD | docker buildx build --platform linux/arm64 --load -t "candidate-line:$$sha" - && echo "candidate-line:$$sha"

deploy:
	scripts/deploy.sh "$(STEP)"

# The operator's controls on the container (DR-023): the cockpit through an SSM port-forward on 127.0.0.1:8011
# (never a public port), and the kill switch, a file the hooks read on every turn and every quiet stretch.
cockpit-forward:
	scripts/deploy.sh cockpit-forward

line-off:
	scripts/deploy.sh line-off

line-on:
	scripts/deploy.sh line-on

# The outbound call's controls (DR-025 section 19). dial-off stops the dialler alone; line-off stops it too.
dial-off:
	scripts/deploy.sh dial-off

dial-on:
	scripts/deploy.sh dial-on

# A signed synthetic application for a walk. PHONE is a fictional 555-01xx number unless given, which no
# allow-list holds, so the line stores it as not dialled; PHONE=probe uses the probe's number from the keychain.
apply:
	@URL="$(URL)" PIN="$(PIN)" PHONE="$(PHONE)" ROLE="$(ROLE)" FIRST="$(FIRST)" ZONE="$(ZONE)" scripts/deploy.sh apply

# A deletion request (spec 9.13), on the task by default, or in this Mac's var/ with WHERE=local.
forget:
	scripts/deploy.sh forget "$(CODE)" "$(WHERE)"
