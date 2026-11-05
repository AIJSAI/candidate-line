# DR-022: The scorecard, and CI for the tests

Status: DRAFT
Built: live (built 2026-11-04 evening, after the session)
Commit: this commit

## What it is

`make scorecard` prints one page of what the line did, in the numbers a recruiting lead asks for, each with its n and its method beside it. `candidate_line/scorecard.py` holds one pure function per number over the trace store, the ledger's state file, `candidate_line/evals/rates.py`, `data/candidates.yaml` and `data/baseline_invites.csv`. In the same commit, `.github/workflows/ci.yml` runs the linters and the tests on GitHub for every push and pull request to main.

## The decision

- **The sources, read only.** The trace store is `TRACE_STORE_PATH`, or `var/traces.sqlite`. The ledger is `STATE_PATH`, or `var/state.json`, and `:memory:` means no ledger file. A store file that does not exist is read as empty and never created. The state file is read as JSON, in the shape `Ledger._write` gives it, and not through `Ledger`, because a ledger that opens an unreadable file moves it aside, and a page that only reads must never move the live line's file. An unreadable file is named on the page and nothing is computed from it. The page says "synthetic data, synthetic baseline" in its first line and names no caller: it prints no number the store masked, and no caller field at all.
- **Each number and its method.**
  - Calls taken, by channel: one row of the store's `calls` table per call, whatever its length, less the calls the daily cap closed.
  - Calls closed by the daily cap: the rows whose outcome is `CLOSED_OUTCOME` (`candidate_line/telephony/app.py`), which heard the closed line and opened no stream (DR-021). Counted apart, so a capped day never reads as more calls taken.
  - Verified callers: calls with a `verify_caller` tool span that matched. The span's line is built from named fields (`turn._one_line`), and "verified " starts it only on a match.
  - Bookings made: `book_slot` tool spans that succeeded, less the two take-backs that leave their spans in the trace: a turn the caller talked over (a `hook/superseded` span after the turn's tier span, from `media.py`) and a turn that hit the five-call cap (its last model span asked for tools that never ran, `turn._take_back`).
  - Callback and move hand-offs: tier-2 `escalation` spans by the tool that posted them. A repeat marked `duplicate` was never posted and is not counted. A superseded turn's hand-off was posted and has no undo (DR-021), so it is counted.
  - Median brain time: each model span's ms, which is one model call from request to reply on the brain's own clock, with the worst beside it, and one row per model id when the store holds more than one. A 0 ms span is left out, as the eval runner leaves it out, since the echo brain reports 0. This is per model call. The eval runner's median (DR-017) is per turn, with a turn's model calls summed, so the two numbers differ by method and are never compared as one.
  - Median turn gap, phone: the `first_audio_gap_ms` that `media.py` writes on a speech span, from the turn's first final transcript (grace included) to its first audio byte sent to Twilio, on the line's own clock. It is neither the probe's clock nor a recording, and the page says so. DR-001's budget of 2,000 ms for the median runs from the caller's last word, so this clock leaves out the transcriber's end-pointing before the final and reads low against the budget [inference].
  - Brain cost per call: the mean over calls of their model spans, priced again with `rates.cost_usd` from each span's tokens and cache counts, so the page follows the rate table and not the price a span was written with. A call with a model `rates.py` has no row for is left out and counted, never priced as free. Speech and the phone are not priced on this page.
  - Invite-to-booked hours: for every booking in the ledger file, the hours from the candidate's `invited_at` in `data/candidates.yaml` to the booking's own stamp, and their median. A booking with no candidate or no time that parses is counted as left out. Beside it, the baseline's median `hours_to_book` for phone and for email, over the invites that booked, with the never-booked count.
- **The baseline's own numbers**, from `data/baseline_invites.csv` (40 synthetic invites, June to September 2026): phone, 5 invites, all 5 booked, median 29.4 hours; email, 35 invites, 29 booked, median 27.5 hours, 6 never booked; all channels, 34 booked, median 28.45 hours. The `hours_to_book` column matches `booked_at` minus `invited_at` to 0.1 hours on all 34 booked rows.
- **Card 07's open decisions, the helper's defaults, not James's:** 1, the page leads with calls taken, in the order the work item listed the numbers; 2, the page is printed only, not served by the cockpit.
- **CI.** One job on `ubuntu-latest`, a standard GitHub-hosted runner: checkout, `astral-sh/setup-uv@v5` with Python 3.12, `uv sync --frozen`, `ruff check`, `ruff format --check`, and `pytest -q` with `STATE_PATH=:memory:`. It has no secrets and makes no model call. The evals need the providers' keys, so they stay on the Mac (`make gate`), and the workflow says so in a comment. `permissions: contents: read`, and a concurrency group per ref that cancels a superseded run.

## Cut this week, with the files each would touch

Card 07 asks for more than this page prints. Each item would touch `candidate_line/scorecard.py` and `tests/test_scorecard.py` only.

- Turns per call, calls by tier (the highest a call reached), and calls that opened with no turn.
- The day's window. The page covers the whole store and prints its first and last call; a `--day` filter is one argument.
- The cost split by speech in, speech out and the phone, by `SPEECH_RATES_USD`, and the two 50 USD spend caps quoted as quoted.
- Guard hits and overrides with trace links, and the cite-or-refuse counts over the FAQ turns.
- The same page written as `var/scorecard.md`.

## The alternative rejected, and why

- **Invite-to-booked from the `book_slot` tool spans,** as card 07 words it. A superseded or capped booking keeps its span, so the span says a booking happened that no longer stands. The ledger holds only the bookings that stand, with their stamp. The cost: text walks and eval runs on `STATE_PATH=:memory:` never reach this number, only bookings written to a ledger file do.
- **The bookings count from the ledger too.** The ledger keeps no channel and nothing of the call's other spans, and is empty for every in-memory walk. The trace count and the ledger's n sit on one page, so a gap between them is visible.
- **Summing each model span's recorded `cost_usd`.** A span written before its model had a rate carries none, and a corrected rate would never show. On the walk store below the two agree to the fifth decimal.
- **A self-hosted or a paid runner for CI.** The repository is public, and standard GitHub-hosted runners are free in public repositories (below).

## What would change the decision

James's answers to card 07's two open decisions. A store with spans and no `calls` row being one the room reads: the probe's direct path opens the media stream without `/voice`, so its calls have no row and stay off the page, as they stay off the cockpit's list. A gap between "bookings made" and the ledger's n on a phone day, which would mean a take-back the spans do not mark. A second machine, when the store becomes a table (DR-012) and the page stays. For CI: a test that needs a secret or the network, or the repository going private, when the minutes are billed.

## Evidence

- `uv run pytest -q tests/test_scorecard.py`, 2026-11-04: 9 passed. Three synthetic calls: a phone call that books on its third turn after a superseded booking, a text call with a missed verification and a callback posted twice, a text call whose booking the five-call cap took back. Also an unpriced model, a 0 ms span, a booking with no candidate, the baseline's counts, an empty store (no file created), an unreadable ledger (not moved), a masked caller (not printed), and `main` reading both paths from the environment.
- The CI steps, run on this Mac on a fresh clone of HEAD with only this item's files added, 2026-11-04: `uv sync --frozen`, `ruff check .` "All checks passed!", `ruff format --check .` "112 files already formatted", `pytest -q` "412 passed". Not yet run on GitHub.
- `make scorecard` on an empty scratch store and a missing scratch ledger: every count 0, every median "none", the baseline rows filled, no file created; 0.07 s wall (`/usr/bin/time -p`).
- `make scorecard` on a copy of the 2026-11-04 walk store (36 text calls, 23:17 to 00:40 UTC) and a copy of a scratch ledger file with one booking, 0.07 s wall. Each value matched a read-only SQL query on the same copy: 0 voice and 36 text calls; 32 verified; 6 bookings (6 successful `book_slot` spans, no superseded span); 4 callback and 3 move hand-offs; 232 model spans, all Haiku 5.5, median 785.5 ms (printed 786 ms), worst 1,240 ms; 0.00075 USD a call over 36 priced calls, 0.02710 USD in all, which is also the sum of the spans' recorded `cost_usd`; invite-to-booked 157.7 hours, n = 1 (invited 2026-10-29 10:10 UTC, booked 2026-11-04 23:54:39 UTC).
- The turn gap is not yet read from a real call: no scratch store had a phone call with a `calls` row. The probe store's 12 speech spans with a gap have none (above).
- `astral-sh/setup-uv` at tag v5 takes a `python-version` input that sets `UV_PYTHON`, read from its `action.yml` on 2026-11-04. The repository is public (`gh api repos/AIJSAI/candidate-line`, 2026-11-04). GitHub's Actions billing page says the use of standard GitHub-hosted runners is free in public repositories (`github/docs`, `content/billing/concepts/product-billing/github-actions.md`, read 2026-11-04).

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
