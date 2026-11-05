# docs/refs: pages read, with their read dates

Every fact a decision record relies on comes from a page saved here, text only, with the read date (Central time, the build calendar's clock; the exact UTC instant is the second line of each file) in the file name. No rate, quota or model fact is said from memory (DR-000). Re-read a page before saying its fact aloud if the date is older than the day you say it.

The files whose Source line is on docs.aws.amazon.com are copies of AWS documentation, copyright Amazon Web Services, Inc. or its affiliates, licensed under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/), converted to plain text on the date in each file's Read line and otherwise unchanged. The Illinois statute texts are public law; the FCC ruling, the eCFR text, and the New York City and California pages are public government documents, each reduced to the passages its record cites and saying so in its first lines. The repository's own code, data and prose are under the MIT license in LICENSE; this folder is the exception. The price-list JSON is the filtered output of `aws pricing get-products`. The other files in this folder are stubs: the vendor's own copyright does not allow the page to be copied here, so each keeps its source line and the few facts the records cite. The three Twilio pages of 2026-11-05 are the same kind: each quotes, word for word, only the passages DR-025 cites.

| Read | File | Page | Used by |
| - | - | - | - |
| 2026-11-01 | `2026-11-01-aws-identity-center-instances.txt` | IAM Identity Center: organization and account instances | DR-002 |
| 2026-11-01 | `2026-11-01-aws-cli-configure-sso.txt` | AWS CLI: configure with IAM Identity Center | DR-002 |
| 2026-11-01 | `2026-11-01-aws-bedrock-model-access.txt` | Amazon Bedrock: request access to models | DR-002, DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-api-invoke-model-with-bidirectional-stream.txt` | Bedrock API reference: InvokeModelWithBidirectionalStream (the permission it needs) | DR-002, DR-007 |
| 2026-11-01 | `2026-11-01-aws-bedrock-model-card-claude-haiku-5-5.txt` | Bedrock model card: Claude Haiku 5.5 | DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-model-card-claude-sonnet-5-5.txt` | Bedrock model card: Claude Sonnet 5.5 | DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-model-card-nova-2-5-sonic.txt` | Bedrock model card: Amazon Nova 2.5 Sonic | DR-001, DR-003, DR-007 |
| 2026-11-01 | `2026-11-01-aws-polly-api-synthesize-speech.txt` | Polly API: SynthesizeSpeech (output formats and sample rates) | DR-003, DR-006 |
| 2026-11-01 | `2026-11-01-claude-platform-pricing-docs.txt` | Claude Platform docs: pricing. Stub: quotes the first-party rate rows for Haiku 5.5, Sonnet 5.5 and Haiku 4.5 and the prompt-caching multipliers | DR-003 |
| 2026-11-01 | `2026-11-01-anthropic-pricing.txt` | anthropic.com/pricing (plans). Stub: quotes nothing, because the page holds no API rate; the rates are on the docs page above | DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-pricing.txt` | Bedrock pricing page. Stub: quotes nothing, because its rate tables render only in a browser; the Nova 2.5 Sonic rates are in the price-list file below | DR-003 |
| 2026-11-01 | `2026-11-01-aws-price-list-api-us-east-1.json` | AWS Price List API (`aws pricing get-products`), us-east-1: Nova 2.5 Sonic, Transcribe, Polly | DR-003, DR-006, DR-007 |
| 2026-11-01 | `2026-11-01-aws-transcribe-pricing.txt` | Transcribe pricing page. Stub: quotes streaming at 0.01 USD a minute in US East (N. Virginia), billed by the second | DR-006 |
| 2026-11-01 | `2026-11-01-aws-polly-pricing.txt` | Polly pricing page. Stub: quotes neural voices at 16.00 USD per million characters | DR-006 |
| 2026-11-01 | `2026-11-01-aws-bedrock-quotas.md` | Bedrock user guide: quotas (overview; the reduced-quota sentence) | DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-quotas-runtime.md` | Bedrock user guide: quotas for the bedrock-runtime endpoint | DR-003 |
| 2026-11-01 | `2026-11-01-aws-bedrock-quota-increase.md` | Bedrock user guide: request a quota increase | DR-003 |
| 2026-11-01 | `2026-11-01-aws-general-reference-transcribe-quotas.md` | AWS General Reference: Transcribe endpoints and quotas (concurrent streams) | DR-006 |
| 2026-11-01 | `2026-11-01-aws-general-reference-polly-quotas.md` | AWS General Reference: Polly endpoints and quotas (requests per second) | DR-006 |
| 2026-11-01 | `2026-11-01-aws-polly-quotas.txt` | Polly developer guide: quotas | DR-006 |
| 2026-11-01 | `2026-11-01-twilio-twiml-stream.txt` | Twilio TwiML: `<Stream>`. Stub: quotes bidirectional with `<Connect>`, ends only with the call, `wss` only | DR-005 |
| 2026-11-01 | `2026-11-01-twilio-media-streams-websocket-messages.txt` | Twilio Media Streams: WebSocket messages. Stub: quotes the fields the line uses in `connected`, `start`, `media`, `stop`, `mark` and `clear` (`audio/x-mulaw` 8000 base64) | DR-005, DR-006 |
| 2026-11-01 | `2026-11-01-twilio-free-trial.txt` | Twilio docs: how the free trial works. Stub: quotes verified recipients only (up to five), 30 days, the same credentials after the upgrade | DR-005 |
| 2026-11-01 | `2026-11-01-twilio-voice-pricing-us.txt` | Twilio voice pricing, US. Stub: quotes local inbound at 0.0085 USD a minute, a local number at 1.15 USD a month, recording at 0.0025 USD a minute | DR-005 |
| 2026-11-01 | `2026-11-01-twilio-security-request-validation.txt` | Twilio docs: security, request validation. Stub: quotes the six signature steps and the worked example | DR-005 |
| 2026-11-01 | `2026-11-01-nyc-dcwp-automated-employment-decision-tools.txt` | NYC DCWP: Automated Employment Decision Tools, Local Law 144 of 2021. Stub: quotes the bias-audit sentence and links the law text | the spec's Never list |
| 2026-11-01 | `2026-11-01-illinois-820-ilcs-42-ai-video-interview-act.txt` | 820 ILCS 42, Artificial Intelligence Video Interview Act (ilga.gov) | the spec's Never list |
| 2026-11-01 | `2026-11-01-illinois-public-act-103-0804.txt` | Illinois Public Act 103-0804 (775 ILCS 5/2-102(L), AI in employment, effective 2026-01-01) | the spec's Never list |
| 2026-11-05 | `2026-11-05-twilio-calls-resource.txt` | Twilio Voice API: the Call resource. Reduced: Direction and AnsweredBy, the create parameters (Url, From, MachineDetection, AsyncAmd, AsyncAmdStatusCallback, StatusCallback, StatusCallbackEvent, Timeout, TimeLimit), Update a Call | DR-025 |
| 2026-11-05 | `2026-11-05-twilio-answering-machine-detection.txt` | Twilio: answering machine detection. Reduced: Enable and DetectMessageEnd, AsyncAmd, the callback's AnsweredBy values, the forked-stream limit | DR-025 |
| 2026-11-05 | `2026-11-05-twilio-voice-pricing-us.txt` | Twilio voice pricing, US. Reduced: local calls at 0.0140 USD a minute out and 0.0085 in, detection at 0.0075 a call, premium text-to-speech per 100 characters | DR-025 |
| 2026-11-05 | `2026-11-05-fcc-24-17-ai-voices-declaratory-ruling.txt` | FCC 24-17, Declaratory Ruling of 8 February 2024: AI-generated voices are artificial voices under the TCPA. Reduced: paragraphs 1 to 9 and the ordering clause | DR-025 |
| 2026-11-05 | `2026-11-05-ecfr-47-cfr-64-1200.txt` | 47 CFR 64.1200 (eCFR, current). Reduced: (a)(1), (a)(10) and (a)(11) on revocation, (b) on artificial-voice messages, (c)(1) on calling hours | DR-025 |
| 2026-11-05 | `2026-11-05-nyc-dcwp-aedt-faq.txt` | NYC DCWP: Automated Employment Decision Tools, the page and its FAQ of 2023-06-29. Reduced: what an AEDT is, screening as an employment decision, the notice rules | DR-025 |
| 2026-11-05 | `2026-11-05-illinois-public-act-103-0804.txt` | Illinois Public Act 103-0804 (775 ILCS 5/2-102(L)), re-read. Reduced: the definition of artificial intelligence, subdivision (L), the effective date | DR-025 |
| 2026-11-05 | `2026-11-05-california-crc-ads-regulations.txt` | California Civil Rights Council: the automated-decision system regulations, the summary page of 30 June 2025 (in effect 1 October 2025). Reduced: what the regulations do | DR-025 |
