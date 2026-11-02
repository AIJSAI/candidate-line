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

- **Built 2026-11-02, about 13:40 CT:** `npm --prefix ~/projects/sample-amazon-nova-sonic-twilio-integration install --ignore-scripts` (exit 0, an audit notice only) and `npm run build` (`tsc`, exit 0); `dist/` holds `server.js`, `nova-client.js`, `mock-tools.js`, `consts.js`, `types.js`. Both commands had been refused to the session the day before and ran after James approved them in permissions. Not yet run: it needs the Twilio values and an AWS profile name in its environment, which land with PREBUILT row 2.

- **The two setting changes, applied 2026-11-02 about 16:10 CT and saved as `bakeoff/arm-b-settings.patch`** (a `git diff` of the sample's `src/`, so the "as-is" claim stays checkable): `SYSTEM_PROMPT` in `src/server.ts` is now the bake-off persona from `bakeoff/persona.md`, word for word, and `modelId` in `src/nova-client.ts` is `amazon.nova-2-5-sonic`, the model DR-003 names for this arm (the sample shipped with `amazon.nova-sonic-v1:0`; this account has both AVAILABLE and AUTHORIZED, and the Nova 2 Sonic concurrency quota is 1, raised from 0 on 2026-11-01). The compiled `dist/` files carry the same two edits so no rebuild was needed. Voice `matthew` and 8 kHz stay as shipped.
- **First run attempt, 2026-11-02 about 16:05 CT:** `node dist/server.js` on the `candidate-line` profile was refused to the session by its command classifier as external code, as the install had been the day before; it runs once James approves that exact command. The route is `/incoming-call` on port 3000, so the number is pointed at it with `make webhook URL=<tunnel> PATH_=/incoming-call`.

- **Arm B ran for the first time, 2026-11-02 about 16:05 CT,** after James approved the exact `node dist/server.js` command: `AWS_PROFILE=candidate-line`, `AWS_REGION=us-east-1`, port 3000 behind its own cloudflared quick tunnel, the number re-pointed with `make webhook URL=<tunnel> PATH_=/incoming-call`. James called from his phone. From the sample's own log, the session was created, the persona reached Nova 2.5 Sonic (the model answered "Hello. I am Gus.", offered to "book or move an interview slot" and, asked "aren't you a screener", said "I do not evaluate people", which is `bakeoff/persona.md` speaking, not the sample's car-rental agent), the model emitted an `interrupted: true` event when James talked over it, and the call closed cleanly on Twilio's `stop`. Thirteen text events in six exchanges. James's ear: "he has like no context about anything, but he sounds good"; the narrowness is the bake-off persona's four facts, by design, and the voice quality is the arm's case. No latency numbers yet: the sample logs no timings, and DR-001's method is the recording.
- **One more setting change, made right after that call and folded into `bakeoff/arm-b-settings.patch`:** the sample's `/incoming-call` TwiML began with a `<Say>` line, "Please wait while we connect your call to Amazon Nova Sonic", spoken by Polly before the stream opened. It names the vendor to the caller and adds seconds before the first turn that arm A does not pay (arm A's greeting travels through the stream), so it is removed from `src/server.ts` and `dist/server.js`; the stream opens at once, as in arm A. Voice, sample rate and everything else stay as shipped.
- **Two arms, one prompt, still to do:** today arm A ran the placeholder prompt and arm B the bake-off persona, so the two calls do not compare. DR-001 needs both arms on `bakeoff/persona.md`; arm A gets it through a `SYSTEM_PROMPT_FILE` setting (DR-008's hooks and the media dependencies read it), added the same evening.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
