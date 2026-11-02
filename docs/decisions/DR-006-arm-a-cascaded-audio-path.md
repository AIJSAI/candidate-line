# DR-006: Arm A, the cascaded audio path

Status: DRAFT
Built: pre-built (PREBUILT.md row 3); the first real phone call is pending the Twilio number (DR-005)
Commit: (filled when the item lands)

## What it is

The phone path that keeps every word as text before it becomes sound: Twilio's media stream in, Transcribe streaming, one turn through the same loop as text mode, Polly out by sentence, and barge-in. Before Wednesday the brain only echoes, so nothing that decides about a caller exists.

## The decision

- **The media stream lands on `/media` on the same FastAPI app as the webhook** (`candidate_line/telephony/media.py`, `app.py`). `/voice` answers `<Connect><Stream url="wss://<public host>/media">` in `stream` mode (the default), or item 5's one spoken line in `say` mode (`VOICE_MODE`). The greeting is spoken through the stream, not by `<Say>`, so a caller can talk over it.
- **Ears: the official AWS SDK for Python v4 client, `aws-sdk-transcribe-streaming` 0.12.0, over the CRT transport.** The client the plan named, `amazon-transcribe`, says in its own README (read 2026-11-01) that it is deprecated, a proof of concept, and points here. The v4 client is marked experimental before 1.0, so it is pinned, and its duplex stream refuses the default aiohttp transport and needs `smithy_http.aio.crt.AWSCRTHTTPClient` passed as `transport` when the config is resolved; both facts were found by running it, and are in the adapter's comments. Audio goes in as 8 kHz 16-bit PCM (Transcribe takes PCM, FLAC or Ogg Opus, not mu-law), converted frame by frame with `audioop.ulaw2lin`, with partial-results stabilization on.
- **Mouth: Polly, `OutputFormat=mulaw` at 8000 Hz, voice Matthew (neural), one call per sentence.** The reply is cut at sentence ends (`split_sentences`), each sentence synthesized in a thread and sent as half-second mu-law chunks followed by a `mark`, so the first sentence plays while the second is still being made. No codec sits between Polly and the phone (the Polly API reference, DR-003).
- **One turn, the same function as text mode.** A final transcript is one utterance; it goes through `run_turn` with the configured brain and hooks, so the guard written on Wednesday holds on the phone the moment it holds in text. The brain is `BRAIN_PROVIDER`'s; the system prompt is `ECHO_SYSTEM` ("repeat the caller's words back") until the persona is written live, and `BRAIN_PROVIDER=echo` removes the model entirely.
- **Barge-in is a `clear`.** Gus counts as speaking from the first media chunk until Twilio returns the last `mark`. A partial transcript with words during that window sends `clear` (Twilio empties its buffer and returns the pending marks), sets an interrupt flag that stops the remaining sentences, and counts one barge-in. A partial while Gus is quiet is ignored.
- **Ears, mouth and brain are injected** (`Deps`), so the whole loop is tested with a scripted transcriber and a fake speaker and no network; `make dev` builds the real pair from settings.

## The alternative rejected, and why

- **`amazon-transcribe`, the package the plan named.** Deprecated by its own README, with documented high-CPU issues; the official client exists and streams, measured below.
- **Transcribe's WebSocket API by hand (presigned URL and event-stream framing).** A week's worth of edge cases to save one dependency; it stays the fallback if the experimental client breaks under us before 1.0.
- **Sending the whole reply to Polly at once.** The first sound waits for the last sentence; by sentence, the first sound waits for the first sentence.
- **Energy-based barge-in (volume on the inbound frames).** Breath, line noise and the caller's own television trigger it; a partial transcript with words is a cheaper and stricter signal, and the plan's cut list already puts barge-in polish first.
- **A separate process for the media stream.** One port, one tunnel, one app to kill in the failure drill.

## What would change the decision

The first real call (then the turn gap is measured from the recording, DR-001's method, and the sentence cut, the stabilization setting and the barge-in rule are tuned against it); the v4 client breaking before 1.0 (then the hand-rolled WebSocket, or the deprecated package pinned, for the week); Transcribe hearing "code" as "coat" (seen below: then the `on_turn` hook normalizes codes and digits, or a custom vocabulary with `ACME` is added, both measured against the eval cases); tracing landing live (then `transcribe`, `model` and `speech` spans are written here at the moment each finishes).

## Evidence

- **Live Transcribe streaming, 2026-11-01, us-east-1, through the v4 client:** a 5.8-second Polly clip ("Hi, my code is ACME four eight two one. Can I move my interview to Thursday at nine thirty?") fed in real time as 20 ms PCM frames; first partial at 1.31 s ("Hi"), first final at 3.78 s ("Hi, my coat is Acme 4821."), second final at 6.60 s ("Can I move my interview to Thursday at 9:30?"), stream closed at 6.61 s. The final for the last sentence arrived about 0.8 s after its audio ended. Note the mis-hearing of "code" as "coat", which the code-reading turn has to survive.
- **The transport finding, 2026-11-01:** `AsyncTranscribeStreamingConfig` cannot be constructed directly (`resolve(...)` is awaited), and with the default transport `start_stream_transcription` raises `UnsupportedTransportError` naming `AWSCRTHTTPClient`; with `transport=AWSCRTHTTPClient()` it streams. `smithy-http[awscrt]` is the dependency that brings the CRT.
- **Live Polly mu-law, 2026-11-01, through `PollySpeaker`:** "ACME candidate line, this is Gus." came back in 278 ms as 17,700 bytes of 8 kHz mu-law (2.21 s of audio); "Thursday at nine thirty. Anything else?" in 133 ms, 20,240 bytes (2.53 s). The audio is one Twilio media message per half second with no conversion.
- `uv run pytest -q`, 2026-11-01: 50 passed, among them the media tests: greeting then echo with `speaking` cleared by the last mark; a partial during speech sends one `clear` and drops the second sentence; a partial while quiet is ignored; the stream verb and its fail-closed 503 without a public host; the `/media` WebSocket end to end through the TestClient.
- **The whole local path, driven by the probe caller (DR-011), 2026-11-01:** greeting, two caller lines, two echoes, with real Transcribe and Polly on both sides and no phone in between; turn gap 775 and 767 ms with the echo brain, which is the floor the model's latency adds to (Haiku 4.5 measured about 600 ms, DR-003). The same mis-hearing as the first live clip ("coat" for "code", "4,821" for the spoken digits) appeared on both sides.
- First real call from James's phone: (filled when the Twilio number exists)

- **First real call, 2026-11-02, 15:17:52 to 15:18:21 CT (29 s by Twilio's call record).** James dialled the line's new number from his own phone. Twilio's signed `POST /voice` from one of its own addresses returned 200 (an unsigned test request two minutes earlier had returned 403, so the signature check was live for the real call); Twilio's media server opened the `/media` WebSocket; James's words: "i called and gus answered". The brain was Haiku 5.5 on the Anthropic API behind the cloudflared quick tunnel. What Gus heard and said on this call was not captured: the media session logs only exceptions and the per-turn spans are `prompts/03`'s work, so the line gained one INFO line per turn (heard, reply, brain and gap milliseconds) right after this call, and the second call carries the numbers.

- **Second real call, 2026-11-02 about 15:21 CT: Gus repeated the caller word for word, and the barge-in worked.** James's report: "gus just repeats exactly what I say each time" and "I did a barge in too at the end and it cut off and listened". The echo was not the echo brain: the media path's dependencies defaulted the system prompt to the echo line (`Deps.system = ECHO_SYSTEM`, kept from the Sunday proof that ran with no model) while the brain was Haiku 5.5, which followed the instruction it was given. Fixed by defaulting to the same prompt text mode runs (`PLACEHOLDER_SYSTEM`). The per-turn log lines added after the first call also never printed: uvicorn configures only its own loggers, so the app now installs a root handler at INFO. Found by James's ear, which is the point of a real call.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
