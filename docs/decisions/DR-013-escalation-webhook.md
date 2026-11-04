# DR-013: The escalation webhook

Status: DRAFT
Built: pre-built (PREBUILT.md row 12)
Commit: 93ad659

## What it is

One line to a channel the recruiter already uses, with the trace link and a suggested next action, posted from a queue so a slow channel never slows a turn; and the way the recruiter's reply is logged back against the call. The rule for which tier crossing posts is written live, with the tiers.

## The decision

- **The channel is a Slack incoming webhook by default, and it is James's pick** (`SlackWebhookPoster`; the second option in the plan, a text to the coordinator through the line's own number, is the same `Poster` interface with Twilio's REST call behind it and costs a message each). The webhook URL is a secret: it lives in 1Password and the login keychain as `SLACK_WEBHOOK_URL`, reaches the process through `scripts/env.sh`, and the poster refuses to be built without it.
- **The message is a fixed template** (`candidate_line/escalation.py`): the tier, the call id, why, the suggested next action, the trace link, and one sentence that says where to log the reply. No transcript in the message; the transcript is one click away on the cockpit, on the loopback.
- **A bounded queue and one worker thread.** `submit` returns in microseconds; the worker writes the escalation row to the trace store, posts, and records the result (`posted_at`, or `post_error` with the exception's name). A failed post is recorded against the call and never raised into a turn. A full queue drops and counts rather than blocks; the count is a span's worth of evidence for the retro, not an outage for the caller.
- **The loop closes on the cockpit.** An incoming webhook is one-way, so the recruiter's reply is the form on the call's page (DR-012): what they did and who they are, stamped, against the same escalation row. `make trace last` prints it with the call.

## The alternative rejected, and why

- **A Slack app with interactive buttons.** Two-way, and the right end state for a real team; it needs an app, OAuth scopes and a public callback URL, which is a week of its own. The reply box costs nothing and is on the page the recruiter already opens.
- **Posting from the turn, synchronously.** A 3-second Slack hiccup becomes a 3-second silence on the phone.
- **Email.** Nobody in a recruiting team is watching an inbox during a call.
- **An unbounded queue.** A dead webhook then grows memory for the length of the day; a bounded one drops the hundredth message and says so.

## What would change the decision

The tiers landing live (then the rule names which crossing calls `submit`, and the message's tier field means something); James choosing the text channel (then `TwilioSmsPoster` behind the same interface, with its per-message cost in the cost line); a team that needs two-way Slack (then the app, and the reply box stays as the record).

## Evidence

- `uv run pytest -q tests/test_escalation.py`, 2026-11-01: the message carries tier, reason, action and trace link; `submit` returns in under 50 ms and the worker posts and marks the row; a failing poster's error is recorded and not raised; a queue of one drops under four quick submits and counts; a missing `SLACK_WEBHOOK_URL` is refused at construction.
- No live post yet: the webhook URL is James's to mint in his Slack workspace and store with `make secret NAME=SLACK_WEBHOOK_URL`; the first real post is pasted here with the channel name.

- **The channel stayed open on 2026-11-02 (about 14:50 CT).** The session tried to stand up the Slack webhook under James's go-ahead: his Google sign-in to Slack with the work account lands only in another workspace, which is not a place for this line's hand-offs, and the one Slack login in his 1Password has no workspace URL and is due a review. No app and no webhook were created. The log poster carries the Tuesday drill; `prompts/06` asks James for the channel (Slack in a workspace he names, or a text through the line's own number once Twilio is live) before the tier code is written.

- **Amended 2026-11-02 evening, after the timed dry run of card 06.** Nothing at runtime built an `EscalationQueue`, so the card's "submit call site" had nowhere to live and a post made from text mode died with the process. Now `default_queue(store, webhook_url)` builds one per path beside the store (`SlackWebhookPoster` when `SLACK_WEBHOOK_URL` is set, the log poster otherwise; the eval runner always the log poster), the turn context carries it (`TurnContext.escalations`), and `drain()` lets text mode and the runner wait for the last post before they exit. The rule for which tier submits stays card 06's.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
