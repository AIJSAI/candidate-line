# DR-007: Arm B, the AWS sample as-is

Status: DRAFT
Built: pre-built (PREBUILT.md row 4)
Commit: (filled when the item lands)

## What it is

The speech-to-speech arm: AWS's own Twilio-to-Nova-Sonic sample, run unmodified as its own process beside this repository, so the bake-off compares two real paths and this week never rewrites a bidirectional-stream client in Python.

## The decision

- **The sample lives beside the repository, not in it:** `aws-samples/sample-amazon-nova-sonic-twilio-integration` (MIT-0), cloned to `~/projects/sample-amazon-nova-sonic-twilio-integration` and pinned at commit `2d441b34c380` ("Fix the assets directory", 2025-10-09, the latest on `main` when read on 2026-11-01). Nothing of it is committed here; this record carries the commit.
- **Its runtime is Node** (fastify, `@fastify/websocket`, `@aws-sdk/client-bedrock-runtime`, `alawmulaw` for the codec, `twilio` 5.5.2). Node 23.11 is on this Mac. `npm run build` is `tsc`; `npm start` runs `dist/server.js` on port 3000 with `/incoming-call` as the webhook and `/media-stream` as the WebSocket.
- **Only its persona and settings change.** The persona is the `SYSTEM_PROMPT` constant in `src/server.ts` (a car-rental agent in the sample) and `DefaultSystemPrompt` in `src/consts.ts`; the voice is `matthew` at 8000 Hz; the model id is hard-coded in `src/nova-client.ts` as `amazon.nova-sonic-v1:0` and is changed to `amazon.nova-2-5-sonic` for the measurement, which is the one line of code the arm touches, recorded here. Credentials come from an AWS profile (`AWS_PROFILE`, default `bedrock-test`, read with `fromIni`), so the Identity Center profile from DR-002 serves it once it exists; Twilio wants an API key SID and secret, not the auth token, as `TWILIO_ACCOUNT_SID`, `TWILIO_API_SID` and `TWILIO_API_SECRET`.
- **Pointing the webhook selects the arm:** `make webhook URL=...` at the sample's tunnel for B, at this app's for A. The sample's README uses localtunnel; the same cloudflared quick tunnel works and keeps one tunnel tool.

## The alternative rejected, and why

- **Porting the sample to Python.** AWS's Python example for the bidirectional stream uses the experimental `aws_sdk_bedrock_runtime` client, not boto3; a port is a week's risk for a measurement that needs one evening.
- **Vendoring the sample into this repository.** Then its MIT-0 code, its lockfile and its node_modules policy become this repository's, and the "as-is" claim gets harder to keep. A pinned commit beside it is the same reproducibility with none of that.
- **Nova 2 Sonic, the sample's default.** Its end of life is no sooner than Dec 2, 2026 (DR-001); 2.5 is the model being decided about.

## What would change the decision

Sonic failing DR-001's rule in the bake-off (then arm B is a measured footnote and the sample is left where it is); the 8-minute session limit documented for Nova 2 Sonic also binding 2.5 (an open check; the sample does not reconnect, and a first-round booking call is under 8 minutes); the sample's `fromIni` not reading an SSO profile (then `AWS_ACCESS_KEY_ID` and friends from `aws sso login`'s cached credentials via `aws configure export-credentials --profile candidate-line`, exported into the sample's environment only).

## Evidence

- Clone and pin, 2026-11-01: `git log --oneline -1` at `2d441b3 Fix the assets directory`.
- `package.json` read 2026-11-01: dependencies and scripts as above; no `engines` field.
- `grep` over `src/` on 2026-11-01: `sampleRateHertz: 8000` and `voiceId: "matthew"` in `consts.ts`; `modelId: "amazon.nova-sonic-v1:0"` at `nova-client.ts:258`; `SYSTEM_PROMPT` at `server.ts:28`; `AWS_PROFILE ?? 'bedrock-test'` at `server.ts:40`; mu-law decode and encode around `server.ts:170` and `:220`.
- `npm install` and `npm run build` were not run by the build session: its command runner refused installing third-party code ("Code from External"). James runs, in his own shell: `! npm --prefix ~/projects/sample-amazon-nova-sonic-twilio-integration install --ignore-scripts` then `! npm --prefix ~/projects/sample-amazon-nova-sonic-twilio-integration run build`, and the output lands here.
- First call through arm B: (filled when James's phone rings it)

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
