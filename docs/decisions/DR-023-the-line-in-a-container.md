# DR-023: The line in a container on AWS

Status: DECIDED 2026-11-04
Built: live (deployed 2026-11-04 evening, after the session)
Commit: this commit

## What it is

The same FastAPI app the Mac ran, as one Fargate task on Graviton behind an Application Load Balancer and a CloudFront distribution with WAF, with the trace store and the ledger on EFS, the secrets in Secrets Manager, the hand-offs on an SNS topic that emails the operator, and a budget action that fails the line closed past a spend threshold. One CloudFormation template (`infra/aws/candidate-line-stack.yaml`) creates all of it; `scripts/deploy.sh` runs the steps in order. The plan it follows is `docs/deploy/PLAN.md`.

## The decision

- **Fargate, not App Runner, not Lambda.** The media stream is one long WebSocket per call with audio every 20 ms. App Runner carries no WebSocket support that could be confirmed (searched 2026-11-04); Lambda and API Gateway's WebSocket API do not fit a bidirectional audio stream.
- **CloudFront in front of the load balancer, no custom domain.** Twilio's media stream needs `wss://`; CloudFront gives a stable HTTPS and WSS address with a default certificate and forwards the WebSocket upgrade headers (its WebSocket page, read 2026-11-04). The load balancer accepts port 80 from CloudFront's managed prefix list only, so the origin cannot be reached around the distribution.
- **A public subnet with a public IP, no NAT.** The task reaches ECR, Transcribe, Polly, the Anthropic API and Twilio directly; a NAT gateway would add about 32 USD a month for nothing.
- **Graviton.** About 20 percent cheaper per hour; the lockfile carries the arm64 wheels, and the image built and imported on 2026-11-04 at 19:37 CT on the Mac.
- **One identity per job.** The execution role pulls the image, writes logs and reads the four secrets; the task role may start a Transcribe stream, synthesize with Polly, invoke the two Haiku profiles, publish to the one topic, mount the one access point, and open an SSM channel. Nothing else, and no key anywhere.
- **The store outlives the task.** EFS, encrypted, one access point owned by the container's user, mounted at `var/`; the file system and the secrets are retained if the stack is deleted.
- **The cockpit stays private.** It is reachable only through an SSM port-forward into the task (`aws ecs execute-command`), tied to the operator's own sign-in.
- **Money as a control.** The existing 50 USD budget alarm stays; a second budget at 45 USD of actual monthly spend attaches a deny policy to the task role, so the line fails closed to Twilio's closed-line message. The per-call and daily caps (DR-021) sit in the code.
- **WAF now.** A rate rule (300 requests in five minutes per address) and the AWS common rule set, about 6 USD a month plus 0.60 per million requests (pricing page read 2026-11-04). Twilio's signature check already refuses any POST that is not Twilio's; WAF protects the public address from a flood.

## The alternative rejected, and why

- **Terraform.** One stack in one account with nothing to share; CloudFormation is native, keeps no state file, needs no new tool, and reads as infrastructure as code. A translation is two hours if a role names Terraform.
- **A custom domain with an ACM certificate.** Needs a DNS change in a zone the line does not own; the CloudFront address serves the same purpose.
- **The store in RDS or DynamoDB.** DR-012's trigger (a second machine) has not fired; EFS keeps the one SQLite file and the ledger with no code change.

## What would change the decision

A second task (SQLite on EFS is a single-writer design: then RDS); a custom domain the operator owns (then ACM on CloudFront and a named origin); a Bedrock quota opening (then `BrainProvider=bedrock` on the stack and the Anthropic secret retired); a cost reading over the plan's estimate after the first full month.

## Evidence

(filled at the end of the deployment: the stack's creation time, the CloudFront address's shape, the probe call's transcript and turn gap, the time the number was re-pointed, the operator's call, the time the Mac line came down, the first cost reading.)

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)

## Evidence, as it happened (2026-11-04, Central time)

- 19:37: the image built for linux/arm64 on the Mac (730 MB) and imported the app, awscrt, anthropic and boto3.
- 19:40: the four secrets created in Secrets Manager from the keychain, nothing printed.
- 19:42: the image pushed to the registry under the commit's short sha (173 MB compressed).
- 19:43: the first stack creation rolled back inside a minute: the CloudFront prefix-list id was empty because the builder profile cannot list managed prefix lists and the lookup returned nothing; the stack was deleted at 19:45 with nothing else created. The lesson is in the deploy script: the lookup runs under the admin profile and the id is checked before the deploy.
- 19:45:35 to 19:51:45: the stack created (CREATE_COMPLETE), six minutes, CloudFront the longest.
- 19:52:13: the service running 1 of 1, the target healthy, `/health` 200 through the distribution on the first try.
- 19:52 to 19:53: a probe call through `wss://<distribution>/media` passed: verified Hannah by code and PIN, answered from F2.1 and F2.3 naming the sections, refused "do you think I am a strong candidate", said goodbye; turn gap median 3,050 ms and worst 3,319 ms over four replies, against 2,263 ms median on the Mac line an hour earlier (the edge and the load balancer add about 700 ms a turn).
- 19:53 to 19:59:03: the stack updated with its own public address as `PUBLIC_BASE_URL` (the Twilio signature check and the stream's `wss://` URL need it); the new task healthy at 19:59:04.
- 19:59:33: the Twilio number re-pointed at the distribution (`make webhook URL=https://<distribution>`); the closed-line fallback stayed on the number; the Mac line stayed up as the safety net until the operator's call passed.
- About 20:00: the hand-off email subscription confirmed by the operator (the first confirmation link belonged to the rolled-back stack's topic and failed; the second stack's email worked).
- 20:13:57 to 20:15:21: the operator's call to the container (masked ***-***-0657). The webhook and the stream opened at 20:13:57.8, and nothing played for about twenty seconds: the first final transcript ("Hello.") came at 20:14:17.5, so the greeting waited on the speech clients' first connections in a task replaced fourteen minutes earlier (a cold start the Mac never showed, its clients staying warm between calls). From there the turns ran normally: 2.1, 1.5, 1.8, 3.0 (a tool turn), 2.5 (a tool turn) and 1.9 s from the caller's last word to the first audio. "it's 323-3 and the PIN is 9683" was not read as a code (the hyphenated spelling was outside the normaliser) and cost one turn; "Acme 3233" verified at 20:14:59; a callback request posted a tier-2 hand-off at 20:15:11 to the log poster, because the running image predates the SNS poster; goodbye at 20:15:21. Two fixes follow in the next image: a warm-up of the speech clients at startup before the task reports healthy, and the hyphenated digit spelling in the normaliser.
- 20:32 to 20:38:33: the final image (the committed head with the caps, the hand-off channel, the stream token, the warm-up and the cockpit beside the line on the container's loopback) built, pushed and rolled out; the new task's log reads "warm-up: polly 77 ms, transcribe 1820 ms" before it reported healthy.
- 20:38 to 20:40: two probe calls through the distribution passed. The first on the fresh task heard the greeting at 8.4 s from connection (11.2 s before the warm-up), the second at 2.4 s; turn gaps 2.6 to 3.6 s. The second asked for a callback as Mei Petrov and the hand-off went out through the SNS topic to the operator's address.
- 20:42: the scorecard run inside the container against its own store (`aws ecs execute-command`, the private path the cockpit also uses): 1 voice call taken, 1 verified caller, 1 callback hand-off, median brain time 850 ms over 10 model spans, median phone turn gap 2,020 ms over 6 turns on the line's own clock (worst 3,024 ms), brain cost 0.00100 USD for that call. The probe calls open the stream directly and leave no call row, so they are not in those counts.
- 20:43:44: the Mac line stopped (the tunnel kept for one more test). 20:43:46 to 20:44:44: a real call placed by the probe's own Twilio number to the line's number, the probe answering as the caller on the Mac's tunnel: the container's webhook minted the stream token, Twilio carried it in the stream's start message, the stream opened, and the call passed (verified Hannah, F2.1 and F2.3 named, the judgment refused, goodbye). The greeting played 3.7 s after the probe connected; the turn gaps by the probe's clock were 3,162 ms median and 3,821 ms worst over four replies, and by the dual-channel recording 3,210 ms median and 3,840 ms worst over four turns (DR-001's method of record). The recording was deleted from Twilio after the measurement, as the probe always does.
- 20:40 to 20:50: the first hand-off email read by the operator ("very messy"): the Slack and log template pushed through SNS as bare lines. The SNS poster now sends a subject that says what happened ("Candidate Line: callback request from ACME-3233 (Hannah Haddad)") and a body that reads as a note, with the masked caller, the next step, the time in Central and the call id; the Slack and log forms stay as they were.
- 20:46:18: the Mac's tunnel down (`make down`); nothing of the line runs on the Mac from then on, and the closed-line fallback on the number is the only net.
- 20:47 to 20:52: the last image of the evening (the email change) rolled out; a probe call asked for a callback as Mei Petrov through the distribution and the hand-off reached the operator's inbox at 20:52 in the new form, the third row in the container's escalations table, posted with no error.
- 21:01 to 21:06:57: the hand-off note moved to SES. The operator read the SNS email and called it improper for a firm's coordinator (it came from no-reply at sns.amazonaws.com, carried AWS's unsubscribe block with the topic's ARN and the recipient's address, and ended on an internal sentence). The stack gained the operator's address as an SES identity (verified by one click) and the task role `ses:SendEmail` on it; the note now arrives from "ACME Candidate Line" as plain sentences (who asked for what, from which masked number and when, what to do, the call record's id), with the SNS topic as the fallback when a send fails.
- 21:07 to 21:08: a callback probe through the distribution produced the fourth hand-off row, channel `ses`, posted with no error, and the note reached the operator's inbox.
- Still open (read 2026-11-05 08:58 CT): the ledger's daily count for 4 November reads 1 where the store holds two voice calls through `/voice` that evening (the operator's at 20:13:57 and the dialled probe at 20:43:46, both with a `POST /voice` line in the container's log). The same code counts 1, 2, 3 across three processes on one file on the Mac, and inside the container the counter's ledger is file-backed at the volume's `state.json`, so the lost count has no explanation yet. The cap still bounds the bill; it may run one call long. The next step is a second counted call on the container with the file read before and after.
- Still open: the first call on a fresh task waits 8 to 13 s for the greeting (three probes after deployments: 11.2 s before the warm-up, 8.4 s and 13.7 s after it; a dialled call to a task already warm by a probe: 3.7 s), so the warm-up removes part of the cold start and not all of it. The next step is to find the remaining wait in the first stream's own log lines before changing anything.
- 21:07 to 21:15: the SES note was delivered but landed in the operator's spam folder, shown as from "me": the sender is the operator's own Gmail address, which gmail.com does not authorize Amazon's servers to send for, so Gmail's checks fail on it. SES accepted and delivered (two attempts, no bounce, no reject). The right sender is an address on a domain the operator owns, verified in SES with its DKIM records in that domain's DNS, so a firm's coordinator receives the note in the inbox with no "via" warning; until that domain is set up, the note reaches the operator only after Gmail is told the sender is not spam. The sender address and the recipients are settings, so the change is the DNS records and two stack parameters, no code.
- 21:25 to 21:30: the operator's controls proven. The cockpit inside the container answered through the SSM port-forward (`make cockpit-forward`, http://127.0.0.1:8011/) with both real calls listed, their steps, model time, tier and hand-offs; the kill switch flipped from the Mac with `make line-off` (the file appeared on the task's volume) and `make line-on` (it was gone), nobody calling in between. Not built: the redesigned recruiting-lead screen (a design page, `docs/showcase/cockpit-design.html`), the recruiter's reply spoken on the next turn, and the summary job; DR-021 lists their files.
