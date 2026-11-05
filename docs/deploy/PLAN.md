# The line in a container on AWS: the plan, for James's read

Written 2026-11-04 evening, proposed and not yet carried out. Nothing in the account is created until James has read this and said go. Every price carries the page it came from and the date it was read; every security line says what it protects against. The order is the one ruled by the search session: the rebuilt line is live on the Mac (done, 17:50 CT), then this plan, then the container, then a probe call against the container's address, then the number is re-pointed, and the Mac line comes down only after that.

## 1. The shape

One container runs what the Mac runs today: the FastAPI app with the Twilio webhook, the media-stream WebSocket, the turn loop, the tools, the guard and the trace store. It runs as one ECS Fargate task (0.25 vCPU, 0.5 GB) in a public subnet with a public IP, so it reaches ECR, Transcribe, Polly, the Anthropic API and Twilio with no NAT gateway (a NAT would add about 32 USD a month for nothing). In front of it: an Application Load Balancer on port 80 that accepts traffic only from CloudFront, and a CloudFront distribution that gives the line a stable HTTPS and WSS address (`<id>.cloudfront.net`, a default certificate, WebSockets supported on any distribution when the `Sec-WebSocket-*` headers are forwarded; CloudFront speaks WebSocket over HTTP/1.1 only). No custom domain is needed for Twilio's `wss://` requirement, so no DNS change anywhere. Twilio's voice URL becomes `https://<id>.cloudfront.net/voice`, the same value goes into `PUBLIC_BASE_URL` for the signature check, and the closed-line fallback TwiML stays on the number.

Why not App Runner: no official WebSocket support found (searched 2026-11-04; community answers say no), and the media stream is a WebSocket. Why not Lambda or API Gateway's WebSocket API: the media session is one long bidirectional connection per call with audio frames every 20 ms, which neither fits.

## 2. Security, line by line

- **Identity.** No IAM user and no key in the image or a file. A task execution role (pull from ECR, write logs, read the named secrets) and a task role scoped to `transcribe:StartStreamTranscription`, `polly:SynthesizeSpeech` and `bedrock:InvokeModel` on the two model profiles the line names, and nothing else. The stack is created with the break-glass admin profile (DR-002: the builder permission set cannot write IAM by design), in one `cloudformation deploy`, and the admin session is never used for anything else.
- **Secrets.** The Anthropic key, the Twilio auth token, the account and number ids, and the Slack webhook if one exists, go into Secrets Manager from the Mac's login keychain in one command that prints nothing, and reach the task as environment variables at start. Rotation is a new secret version and a redeploy. The Anthropic key stays the one inside the workspace with the 50 USD monthly cap (DR-003).
- **Network.** The load balancer's security group allows port 80 only from CloudFront's managed prefix list; the task's security group allows port 8000 only from the load balancer's group. No SSH, no other listener. The cockpit on port 8001 is never exposed: James reads it through an SSM port-forward into the task (ECS Exec), the same way an operator would in a client's account.
- **The webhook.** Twilio's signature check stays on (`app.py`), so a POST that did not come from Twilio is refused with 403 before anything runs. Optional: AWS WAF on the distribution with one rate-based rule (about 100 requests per five minutes per address); it costs 6 USD a month (5.00 a web ACL and 1.00 a rule, plus 0.60 per million requests; pricing page read 2026-11-04) and protects the public address from a flood, which the signature check does not.
- **Data.** The trace store and the ledger live on one EFS file system (encrypted at rest with the AWS owned key, one access point mounted at the app's `var/`), so a redeploy or a task restart keeps every call and booking. No audio is ever stored (DR-012); numbers and PINs are masked before they are written. Logs go to CloudWatch with 30-day retention; CloudTrail is already on (DR-002).
- **Money as a control.** The existing 50 USD AWS budget alarm stays, and a second budget gets a budget action: at 45 USD of actual monthly spend it attaches a deny policy to the task role, so the line fails closed to Twilio's closed-line message instead of spending on. The limits the search session set as a precondition for a public number are code, in the same change: a per-call length cap (Gus closes politely at five minutes) and a daily call cap (the line answers with the closed-line TwiML past it). Both are settings with defaults, both are tested, and both show in the records.
- **The image.** `python:3.12-slim`, `uv sync --frozen`, a non-root user, a `HEALTHCHECK` on `/health`, no secrets baked in, ECR scan-on-push on. Built for `linux/arm64` (Graviton is about 20 percent cheaper per hour; the lockfile already carries aarch64 Linux wheels for the native packages, and Docker 29 with buildx is on the Mac) with x86 as the fallback if the build or a wheel fails.

## 3. Cost, monthly, before per-call charges

| Item | Estimate | Source, read 2026-11-04 |
| - | - | - |
| Fargate task, 0.25 vCPU and 0.5 GB, all month | about 9.0 USD on x86 (0.000011244 USD per vCPU-second and 0.000001235 per GB-second from the page's own example; hourly figures are my arithmetic); about 7.2 on Graviton | aws.amazon.com/fargate/pricing |
| Application Load Balancer | 16.4 USD (0.0225 an hour) plus LCU-hours at 0.008; a phone line at a few calls a day stays far under one LCU, so under 1 USD | aws.amazon.com/elasticloadbalancing/pricing |
| CloudFront | 0 USD: the Free plan carries 1 million requests and 100 GB a month with no overage charges, far above a phone line's traffic | aws.amazon.com/cloudfront/pricing |
| Secrets Manager, four or five secrets | 1.60 to 2.00 USD (0.40 a secret a month, 0.05 per 10,000 calls) | aws.amazon.com/secrets-manager/pricing |
| EFS, under 1 GB | under 1 USD; the page's table did not render, re-read before the go | aws.amazon.com/efs/pricing |
| CloudWatch logs, ECR storage | about 1 USD | not re-read; small |
| Optional WAF with one rule | 6 USD plus 0.60 per million requests (5.00 a web ACL, 1.00 a rule, prorated hourly) | aws.amazon.com/waf/pricing |
| **Total** | **about 29 to 31 USD without WAF, 35 to 37 with it** | |

Per call on top: about 0.18 USD for a five-minute call (DR-001: Transcribe, Polly, Haiku 5.5, Twilio, each at its rate read 2026-11-01). The ruling's ceiling is about 40 USD a month; the estimate is under it either way, and the Mac tunnel's 0 USD goes away with the Mac dependency.

## 4. The steps, in order

1. A `Dockerfile` and a `make image` that builds and runs the container on the Mac against the same secrets, proven by a text-mode turn and a local probe call. No account change.
2. One CloudFormation template under `infra/aws/` (a VPC with two public subnets, the two security groups, the load balancer and target group with the `/health` check, the ECS cluster, task definition and service, the EFS file system and access point, the two roles, the secret references, the CloudFront distribution with the WebSocket origin request policy, the log group, the budget action). James reads the template; the stack is created with the admin profile.
3. The secrets uploaded from the keychain, nothing printed.
4. The image pushed to ECR; the service started; `/health` green through the CloudFront address.
5. A probe call against the container (`make probe URL=wss://<id>.cloudfront.net/media`) with Hannah's code; the trace read from the store through the port-forward.
6. `make webhook URL=https://<id>.cloudfront.net` points the number at the container, time noted; one real call by James; the Mac line stays up until that call passes.
7. `make down` on the Mac; the keep-alive lines are moot from then on. The fallback TwiML stays on the number.
8. The record (DR-023, deployment) with the addresses' shapes, the flip times, the probe result, the measured cost after the first full day, and the rollback: `make webhook URL=<tunnel>` puts the number back on the Mac inside a minute; `cloudformation delete-stack` removes everything except the secrets and the file system, which are set to retain.

Time: about half a day for steps 1 to 5, an hour for 6 to 8.

## 5. What James decides before the go

1. Go or not.
2. Graviton (cheaper) or x86 (no build risk).
3. WAF now (about 6 USD a month) or later.
4. The budget action threshold (45 USD proposed) and the daily call cap (30 proposed) and per-call length cap (5 minutes proposed).
5. Whether the cockpit stays private behind the port-forward (proposed) or gets a login later.

## 6. What this does not change

The code the line runs, the evals, the guard, the records, the Twilio number and its fallback, the Anthropic workspace cap, and the brain (Haiku 5.5 on the Anthropic API, Bedrock one setting away, DR-003).
