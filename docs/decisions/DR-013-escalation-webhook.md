# DR-013: The escalation webhook

Status: DRAFT
Built: pre-built (PREBUILT.md row 12)
Commit: 5e0ed27

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

- **The channel stayed open on 2026-11-02 (about 14:50 CT).** No Slack workspace suited to this line's hand-offs was available on 2026-11-02, so no app and no webhook were created; the on-screen log poster carries the hand-off. It carried the Tuesday drill; `prompts/06` asks James for the channel (Slack in a workspace he names, or a text through the line's own number once Twilio is live) before the tier code is written.

- **Amended 2026-11-02 evening, after the timed dry run of card 06.** Nothing at runtime built an `EscalationQueue`, so the card's "submit call site" had nowhere to live and a post made from text mode died with the process. Now `default_queue(store, webhook_url)` builds one per path beside the store (`SlackWebhookPoster` when `SLACK_WEBHOOK_URL` is set, the log poster otherwise; the eval runner always the log poster), the turn context carries it (`TurnContext.escalations`), and `drain()` lets text mode and the runner wait for the last post before they exit. The rule for which tier submits stays card 06's.
- **The notes read in the operator's inbox, 2026-11-05, 19:00 to 19:10 CT:** 35 hand-off emails from the day were listed in Gmail (the probe's screening hand-off, and the callback, move and write-up notes the two voice regressions raised) and four were opened. The callback, move and screening notes read as a recruiter needs them: who, what was asked, when, what to do, the record link. The write-ups did not: "The ACME candidate line raised a tier 3 hand-off: the guard replaced a sentence (p08)" and "What to do: read the trace", with no link, and the screening note's record link named the dev cockpit's port (8001) rather than the port-forward's (8011, DR-023). Fixed the same evening: each write-up part has recruiter words and a to-do (`_WRITE_UPS` in `escalation.py`; a part the table does not name is kept in the line's words), the subject reads "A call to look at: unanswered question", every note ends with the call's cockpit link, and the stack sets `COCKPIT_BASE_URL` to the port-forward's address. Also seen: the notes arrive from the operator's own address ("via amazonses.com", "me" in the inbox list) because SES is in its sandbox with that one verified identity; a line of ACME's own would send from a verified domain. And the probe's calls raise real notes: every regression run mails the operator a dozen hand-offs, which a `probe-` call id could route to the store alone once the regression scores them from the store rather than the inbox (DR-024).
- **Read again after the fix, 2026-11-05, 19:41 to 19:45 CT (image f12c533 on the container, stack updated 19:39 CT):** two probe calls by voice through `make voice-regression`, CL-033 (a callback) and CL-032 (a question the FAQ does not answer), raised hand-offs 36 and 37, both posted by SES with no error, and both notes were opened in the operator's inbox. The write-up's subject is "A call to look at: unanswered question" and its body reads "The ACME candidate line flagged a call for a person to look at: a caller asked something the FAQ does not answer, so the line said it could not help with that. ... What to do: listen to the question on the call page; if it deserves an answer, add it to the FAQ or call the caller back. Call record probe-CL-032: http://127.0.0.1:8011/calls/probe-CL-032 (the line's cockpit)." The callback note names Mei Petrov (ACME-1022), the best time, F8.2's one business day and the same kind of link. Nothing internal is left in either.


## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
