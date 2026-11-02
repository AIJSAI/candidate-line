# DR-005: Telephony and the tunnel

Status: DRAFT
Built: pre-built (PREBUILT.md row 2, with DR-004)
Commit: (filled when the item lands)

## What it is

How a phone call reaches the laptop: a Twilio number, its voice webhook, the TwiML that answers, the media stream that carries audio both ways from item 3 on, the tunnel that gives the laptop a public hostname, and the one command that re-points the number.

## The decision

- **Twilio, on an upgraded account.** The saved trial page (read 2026-11-01) says a trial account can call or message only verified recipients, up to five per account, and ends 30 days after sign-up; the room's phones are not on a verified list, so the upgrade is a condition of Wednesday, not a nicety. The upgrade is James's money call and his click; the credentials do not change with it (same page: there are no separate trial credentials).
- **The stream verb.** `<Connect><Stream>` opens a bidirectional stream (the TwiML page: `<Start><Stream>` is one-way, `<Connect><Stream>` two-way); the only way to stop a bidirectional stream is to end the call. Media goes both ways as base64 `audio/x-mulaw` at 8000 Hz, and a `clear` message from the server empties Twilio's audio buffer and returns the outstanding `mark` messages (the WebSocket messages page), which is how barge-in interrupts Gus mid-sentence in item 3.
- **The webhook:** `POST /voice` on the FastAPI app (`candidate_line/telephony/app.py`). In `say` mode it answers one spoken line with `<Say>`; in `stream` mode, the default since item 6 landed, it answers `<Connect><Stream>` to the same app's `/media` WebSocket (DR-006) and refuses with 503 when no public host is set, because the stream URL must be a public `wss://` address. Every request is checked against Twilio's signature scheme (HMAC-SHA1 over the public URL plus the sorted form fields, keyed with the auth token; the security page, read 2026-11-01) and the check fails closed: with no `TWILIO_AUTH_TOKEN` in the environment the webhook answers 503, unless `ALLOW_UNSIGNED_WEBHOOKS=1`, which is for a local `curl`. Behind the tunnel the app sees `127.0.0.1`, so the URL it signs is rebuilt from `PUBLIC_BASE_URL`. The page's own worked example is a unit test.
- **The tunnel: a cloudflared quick tunnel** (`make tunnel`), which needs no account and prints a random `trycloudflare.com` hostname. Because the hostname changes on every start, re-pointing the number is one command, `make webhook URL=https://<host>`, which calls Twilio's REST API with the account, number and token from the keychain. That command is Tuesday's re-point drill.
- **Credentials:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_NUMBER_SID` live in 1Password and the login keychain (DR-004) and reach the process through `scripts/env.sh`. The account id and the phone number appear in no file in this repository.

## The alternative rejected, and why

- **ngrok.** Needs an account and an auth token on the laptop before the first byte; cloudflared's quick tunnel needs neither, and the re-point drill is the same one command either way.
- **A named Cloudflare tunnel with a fixed hostname now.** Needs a zone in Cloudflare and a credentials file on the laptop; the churn it removes costs one command per restart this week. It is the "what would change" below.
- **Twilio's helper library for the signature.** The security page recommends the helpers; the scheme is six lines, the page's worked example pins them as a test, and the webhook carries no other Twilio dependency. If the two ever disagree, the helper wins and the test says so.
- **Accepting unsigned webhooks in development.** A public URL behind a tunnel is public; the fail-closed default costs one environment variable for a local `curl`.
- **`<Start><Stream>` with a separate `<Say>` path.** One-way media cannot carry Gus's audio back; `<Connect><Stream>` is the only verb that does.

## What would change the decision

A hostname churn that costs more than the one command (then a named tunnel, which also fixes the webhook URL for the probe caller); a second `Stream` per call being needed (the one-stream-per-call limit the plan mentions was not found on the saved TwiML page, so it is not asserted here; if it exists, it binds arm B's sample too); the room's phones being few and known (then a trial account would do, and the upgrade waits).

## Evidence

- `docs/refs/2026-11-01-twilio-free-trial.txt`: verified recipients only, up to five; 30-day expiration; same credentials after the upgrade.
- `docs/refs/2026-11-01-twilio-twiml-stream.txt`: `<Connect><Stream>` is bidirectional; it ends only with the call.
- `docs/refs/2026-11-01-twilio-media-streams-websocket-messages.txt`: media is base64 `audio/x-mulaw` at 8000 Hz; `clear` empties the buffer and returns the pending marks.
- `docs/refs/2026-11-01-twilio-security-request-validation.txt`: the signature scheme and its worked example (auth token `12345`, expected `L/OH5YylLD5NRKLltdqwSvS0BnU=`), which `tests/test_webhook.py` reproduces.
- `docs/refs/2026-11-01-twilio-voice-pricing-us.txt`: call recording is 0.0025 USD per minute; the per-minute inbound rate is read from the page's table at item 9.
- Local run, 2026-11-01: `ALLOW_UNSIGNED_WEBHOOKS=1 BRAIN_PROVIDER=echo uv run uvicorn candidate_line.telephony.app:app` answered `GET /health` with `{"status":"ok","brain":"echo"}` and `POST /voice` with the TwiML `<Say voice="Polly.Matthew-Neural">` hello line, `text/xml`, 200, in 0.5 ms on the loopback. Without the flag the same request returns 503; with a token and a wrong signature, 403 (`tests/test_webhook.py`).
- Tunnel proof, 2026-11-01: not yet. The build session's command runner refused `cloudflared tunnel --url http://127.0.0.1:8000` as an external ingress tunnel, so `make tunnel` is run from James's own shell the first time (`! make tunnel`), and the public `/health` and `/voice` results are pasted here with the hostname redacted.

- **Tunnel started by the session, 2026-11-02 about 13:45 CT:** `cloudflared tunnel --url http://127.0.0.1:8000` as a background process, after James approved the command in permissions (it had been refused as an external ingress tunnel on 2026-11-01). The hostname is a random `trycloudflare.com` name that changes on every start, so it is set on the Twilio number by `make webhook URL=...` each build day and never written into this repository.

- **Twilio account built 2026-11-02, 14:55 to 15:25 CT.** No account existed for James's address (the login page shows a password step for any email, which misled the session for ten minutes; the absent reset mail settled it). James created the account and its 2FA himself, chose "Full access" and the Individual account type, and loaded a 20 USD balance; the session cannot create accounts or enter payment details. From the console the Account SID and the Auth Token went page to login keychain through the clipboard (`make secret NAME=TWILIO_ACCOUNT_SID`, `make secret NAME=TWILIO_AUTH_TOKEN`), never through a file or the session's context. The line started with the token present and the public `/voice` route now answers 403 to an unsigned request instead of 503: signature checking is live.
- **The number is blocked on Twilio's identity check.** `POST /IncomingPhoneNumbers` for a local number returned 401 with code 20003, "Primary compliance profile is not approved ... complete the KYC process in Trust Hub" (the purchase itself had James's explicit yes and his permission approval, at 1.15 USD a month from the balance). Twilio's error page for 20003 (read 2026-11-02) lists "A Primary Compliance Profile hasn't been submitted and approved for the account" as a cause; the Trust Hub Individual profile asks for a name, address and contact, then an identity verification by Persona (government ID and selfie). That step is James's. Twilio's 32203 page (read the same day) says an Individual profile approved after October 2025 does not satisfy the requirement for outbound +1 SIP calls, so the dial-mode probe (DR-011) may also need a Business profile; inbound calls to the line's number are not named by either page. Review time: not stated on the pages that could be read; a support article on outbound blocks (not readable by the session) is reported elsewhere to say 7 to 8 days for profile reviews. [inference] The Persona step is automated and usually resolves in minutes, which is why the Individual profile was chosen over a Business one for Wednesday.
- **If the profile is not approved by Tuesday 2026-11-03 10:00 CT,** Wednesday's phone path needs a fallback. The session's pick: a browser soft phone served by the line itself (microphone to 8 kHz mu-law in the Twilio frame shape over the same `/media` socket, Gus's audio played back), so the room talks to Gus from a phone's browser through the tunnel on the same media path, barge-in and traces included; declared in PREBUILT as its own row if built. The alternative, another carrier, costs a day of protocol work (DR-006's media session is shaped by Twilio's stream messages). James picks.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
