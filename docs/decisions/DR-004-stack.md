# DR-004: The stack

Status: DRAFT
Built: pre-built (PREBUILT.md row 2, with DR-005)
Commit: (filled when the item lands)

## What it is

The language, runtime, web framework, SDKs and secret store the line runs on, and the `make` targets that run it.

## The decision

- **Python 3.12 under uv, pinned below 3.13** (`pyproject.toml`: `requires-python = ">=3.12,<3.13"`, `.python-version`). The reason is one module: `audioop`, the standard library's mu-law codec, left the standard library in 3.13, and the phone path converts `audio/x-mulaw` at 8000 Hz to PCM for Transcribe on every frame. On 3.12 it is an import; on 3.13 it is a dependency.
- **FastAPI on uvicorn** for the voice webhook now and the media-stream WebSocket from item 3 (one ASGI app, one port, one tunnel). `python-multipart` reads Twilio's form posts.
- **boto3** for Bedrock, Transcribe and Polly; **the `anthropic` SDK** for the fallback brain (DR-003's switch rule). Both brains sit behind `candidate_line/brain/provider.py`'s `Brain` protocol, chosen by `BRAIN_PROVIDER`.
- **Typed settings in one module** (`candidate_line/settings.py`): a frozen dataclass read once from the environment, which refuses an unknown provider at start-up. No other module reads `os.environ`.
- **Secrets:** the human copy lives in 1Password; the machine copy lives in the macOS login keychain under the service name `candidate-line`, one item per variable (`make secret NAME=ANTHROPIC_API_KEY` reads the clipboard into the keychain and clears the clipboard); `scripts/env.sh` exports them into the process that `make dev` or `make webhook` starts. No value is ever in a file, and `.gitignore` refuses `.env` anyway (AGENTS.md rule 7).
- **pytest and ruff**; `make test`. The tests build the app around their own settings and inject fake clients, so no test touches the network or a secret.

## The alternative rejected, and why

- **Python 3.13 or 3.14 with a third-party mu-law codec.** One more dependency to carry for eight lines of standard library; the removal is the only thing 3.13 changes for this line.
- **Node for arm A, because the AWS Sonic sample is Node.** The sample runs as its own process, unmodified (item 7), so arm B needs no port; a Node arm A would split one week's codebase across two runtimes.
- **A `.env` file.** Rule 7, and the trace, the prompt and the logs are easier to keep clean when no file holds a value to leak.
- **The 1Password CLI as the machine store.** The `op` service account on this Mac is scoped to another project's vault; James's personal vault is not reachable from the terminal, and widening a service account's scope is a security decision of its own. The keychain is the operating system's store and is already there.
- **Flask.** No native WebSocket or ASGI; the media stream needs both.
- **pydantic-settings.** Thirty lines of dataclass do the job and show every default in one screen; the schema validation the boundary needs is on Twilio's form and the model's output, not on six environment variables.

## What would change the decision

A dependency that needs Python 3.13 (then the mu-law tables, 256 entries each way, are vendored and `audioop` goes); a second machine or a server (then a secrets manager or a 1Password shell plugin replaces the keychain, and the env script is the only thing that changes); a tool that needs the app importable as a package (then `[tool.uv] package = false` goes and a build backend arrives).

## Evidence

- `uv run python -c "import sys, audioop, fastapi, boto3, anthropic; ..."` on 2026-11-01: Python 3.12.13; `audioop` imports with its deprecation warning ("slated for removal in Python 3.13"); anthropic 2.3.0; boto3 1.43.123; fastapi 0.162.0.
- `uv run ruff check candidate_line tests scripts`: all checks passed (2026-11-01).
- `uv run pytest -q` (2026-11-01): 13 passed in 0.14 s (settings, the signature scheme against Twilio's worked example, the fail-closed webhook, both brains against fake clients).
- `security find-generic-password -s candidate-line`: no item on 2026-11-01 before the first `make secret`; the store is empty until a secret is placed in it by hand.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
