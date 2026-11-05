# DR-025: The outbound screening call, with the gate in code

Status: DRAFT
Built: live (the contract written 2026-11-05 by lane 0 of the outbound build; lanes A, B and C build to it, `prompts/08-outbound-screening.md`)
Commit: this commit

## What it is

The line calls an applicant back within minutes of a signed application with consent, inside a calling window. It says first that it is automated and transcribed, confirms the applicant by the PIN they chose at intake, asks the role's posted questions word for word, and records each answer with one fixed line after it. When every posted requirement is met it offers the recruiter's open slots and books one; when one is not met it says in fixed words what the posting asks for and when a recruiter will call, and hands the application to that recruiter. A person makes every hiring decision. It runs on the same `/voice`, media stream, turn loop, guard, tiers, ledger, trace store and escalation queue as the inbound line (spec section 9).

## The decision

James ruled the shape on 5 November 2026, over the design notes' default (the no-gate shape, below). The gate is code: one pure function compares an applicant's own answers with the requirements the employer posted for the role, and `book_slot` and `list_open_slots` refuse in code while a posted question is unasked or a posted requirement is unmet. The model never decides the gate and never words a reaction to an answer: every line after an answer is fixed and said by code, the same for every applicant. Nothing is spoken as a judgment, nothing closes an application, and Gus never scores, ranks, compares or opines. Spending and security are requirements of the design, not afterthoughts: caps bound the bill with nobody calling, and the raw phone number lives in one store, read by one component.

Section 5 of the spec keeps every line; the rewording of Never 1, a new Never 7, and the outbound lines under Never 3 and Never 5 are written beside them as proposed to James on 2026-11-05, pending his words.

## Contracts

The three builder lanes build to these names, signatures and shapes. A lane that needs one changed stops and asks (AGENTS.md rule 3); the record changes first.

### 1. The tools (`candidate_line/tools/screening.py`, lane A)

Each is a `ToolFn` in the `actions.py` pattern: wrapped by `_tool`, returns a `ToolOutcome`, never raises. All three read the applicant from the call's scratch: `ctx.data["outbound"]` on an outbound call (seeded from the dial record, section 12), or `ctx.data["candidate"]` once `verify_caller` matched an applicant on an inbound call.

- **`confirm_applicant(pin: str)`**. Outbound calls only; in `OUTBOUND_TOOL_SPECS`, not in `TOOL_SPECS`.
  - No dialled applicant on the call: error "There is no application on this call to confirm."
  - Two misses already: error "Two misses already on this call. " + `OFFER_CALLBACK`, nothing checked; an insisted PIN still goes to `ctx.data["pins_heard"]`.
  - Not four digits: error "The PIN was not four digits. Ask the applicant to say it again, digit by digit."
  - Match (`Ledger.match_applicant_pin`): sets `ctx.data["candidate"] = code`; content `{"confirmed": true, "first_name", "role": <title>, "questions": <n>, "next_question_id": <id or null>}`; `say` = the intro line and the first unrecorded question; `ctx.data["asked"] = <that question id>`. When the screen is already complete, `say` is None and the content carries `"next_step"` (below).
  - Miss: content `{"confirmed": false, "failures": n, "tries_left": m}` and, on the second, `"next": OFFER_CALLBACK`; `is_error` false, as `verify_caller`'s miss; `say` = `PIN_RETRY_LINE` on the first miss, `PIN_SECOND_MISS_LINE` on the second. The miss counts in `ctx.data["verify_failures"]` with `MAX_VERIFY_ATTEMPTS`, so the tier rule's second-miss write-up holds unchanged.
- **`record_answer(question_id: str, value: str, heard: str)`**.
  - Not confirmed or verified as an applicant: error "The applicant is not confirmed yet. Ask for the PIN first."
  - Unknown id, or an id the line has not yet said: error naming the question to record ("Record the answer to q3.").
  - The screen already complete: error "Every question is answered; the answers are fixed for this call."
  - A value outside the question's kind: error naming the allowed values ("For this question the value is yes, no, declined or unclear.").
  - `unclear` the first time on a question: nothing written; content `{"recorded": false, "question_id", "asked_again": true}`; `say` = `UNCLEAR_LINE` + " " + the same question.
  - Recorded, more to come: written through `Ledger.record_answer` with an undo that restores the previous record; content `{"recorded": true, "question_id", "value", "next_question_id", "questions_left"}`; `say` = `ack_line(value)` + " " + the next question; `ctx.data["asked"]` moves on.
  - Recorded, the last: `rules.check(role, answers)` decides. Met with open slots: `Ledger.set_screen(code, "met", ...)`; content adds `"complete": true, "next_step": "offer_slots", "slots": [{"id", "label", "local"?}]` (at most three, the role's recruiter's, nearest first, in Central with the applicant's zone beside it when it differs); `say` = `ack_line(value)` + " " + `met_line(slots)`. Met with no open slot, or not met: `Ledger.set_screen(code, "met" | "not_met", call_id, promised_by)`; content adds `"complete": true, "next_step": "recruiter_call"`; `say` = `ack_line(value)` + " " + `NO_SLOT_LINE` or `not_met_line(asks)`; `escalate` = the screening hand-off (section 11). The undo clears the screen and the answer. The content never holds the words met, unmet, qualify or eligible, so the model reads no verdict it could repeat.
  - The `heard` words are scrubbed with `_scrub` (PIN and phone masked) before they are written or traced, and capped at `MAX_TEXT`.
- **`stop_calls()`**. In `TOOL_SPECS` and `OUTBOUND_TOOL_SPECS`.
  - An applicant on the call: `Ledger.opt_out(code, how="said on the call", call_id, number_hmac)` cancels every due dial; content `{"stopped": true, "dials_cancelled": n}`; `say` = `OUTBOUND_STOP_LINE`; `hang_up` true.
  - No applicant: error "This line calls only people who applied and agreed to it; nobody on this call is on its list."
  - The hooks' phrase rule (section 14) reaches the same `screening.record_opt_out(ctx, how)` with no model call.
- **The existing tools for an applicant** (lane A, `actions.py`): `verify_caller` matches an applicant's code and PIN through `Ledger.match` and, when questions remain, returns `say` = `verified_applicant_line(code_digits)` + the intro + the first unrecorded question. `list_open_slots` and `book_slot` call `rules.check` for an applicant and refuse unless it is complete and met: error "The screening questions come first; a booking is offered after the last one." when one is unasked, and "A recruiter calls this applicant within one business day; the line books nothing on this call." when one is unmet. `book_slot` books only a slot of the role's recruiter; `Ledger.book` refuses an applicant whose screen is not `met` as a second lock.
- **The specs.** `TOOL_SPECS` gains `record_answer` and `stop_calls`. `OUTBOUND_TOOL_SPECS` is `confirm_applicant`, `record_answer`, `stop_calls`, `list_open_slots`, `book_slot`, `answer_question`, `request_callback` and `end_call`. `_TOOLS` names all of them. The descriptions carry no record's real id or slot.

### 2. `ToolOutcome` gains `say` (lane A, `actions.py`)

`say: str | None = None`: words the loop speaks by code in place of a further model call; never a PIN. The other fields are unchanged.

### 3. The loop's say branch (lane A, `turn.py`)

When a tool outcome of a model call carries `say`, `_tool_loop` returns that text (the last such outcome's, when there are several) with no further model call, and marks the loop `said_by_code`. `run_turn` then skips the own-refusal check, `_spoken_cap` and `_name_sections` for that text; the guard (`before_speak`) still reads it. The history alternates as on the refusal path: the assistant tool-use message, the tool results, then the spoken text. `_one_line` gains the three tools ("confirmed the applicant", "recorded q2: yes", "stopped every further call"). `_ID_ARGS` gains `question_id` and `value`: a value is a posted id or a number of three digits at most, never a PIN, so the span keeps it; `heard` is free text and masked. `TurnResult` gains `hand_offs: tuple[Escalation, ...] = ()`, the hand-offs posted on the turn, for the eval's hand-off checks (section 18).

### 4. `data/roles.yaml` and its loader (`candidate_line/tools/roles.py`, lane A)

```yaml
# SYNTHETIC. Generated by scripts/make_synthetic_data.py (seed 20261105) on 2026-11-05. No real person or record.
synthetic: true
firm: ACME
roles:
- id: care-aide                 # a slug, unique
  title: Home Care Aide         # said after the PIN, never before
  site: Riverside branch
  recruiter: Recruiter A        # a label; the interview slots below name it
  questions:                    # asked in this order, word for word
  - id: q1                      # unique within the role
    say: The posting asks for a valid driver's licence, because aides drive between clients' homes. Do you hold a valid driver's licence?
    kind: yes_no                # yes_no | choice | range
    asks: a valid driver's licence   # the posted requirement in words, for the not-met line and the cockpit
    rule: {equals: 'yes'}       # the posted requirement in a closed form
    reason: Aides drive between clients' homes on every shift.   # the posted reason it is job-related
  - id: q2
    say: ...
    kind: choice
    options:                    # choice only
    - {id: weekdays, say: weekdays only}
    - {id: weekends, say: weekends only}
    - {id: both, say: both}
    asks: availability on weekends
    rule: {one_of: [weekends, both]}
    reason: ...
  - id: q3
    say: ...
    kind: range
    range: {min: 0, max: 60, unit: hours a week}   # range only; the scale and the unit the line says
    asks: at least 20 hours a week
    rule: {at_least: 20}
    reason: ...
interview_slots:                # the recruiters' slots, beside data/slots.yaml's first-round slots
- id: S1105-0900                # the S<mmdd>-<hhmm> form; 09:00, 11:00, 13:00 and 16:30 never clash with slots.yaml
  start: '2026-11-05T09:00:00-06:00'
  duration_min: 20
  recruiter: Recruiter A
  status: open
  held_by: null
```

- The rule forms, and no others: yes_no takes `equals: 'yes' | 'no'`; choice takes `one_of: [option ids]`; range takes `at_least: n`, `at_most: n` or `between: [low, high]`, each inside the range. Every question has a rule, an `asks` and a `reason`.
- The loader refuses, at load and so at start: an unknown key anywhere (score, weight, rank, knockout, required, expression and any other); a rule form that does not fit the kind; a duplicate id; an option or range on the wrong kind; and any question whose `say` names a topic the line never asks about: age or birth date, citizenship or nationality, salary history or current pay, zip code or neighbourhood, health or disability (the accommodation clause excepted), arrests or convictions, pregnancy, marital or family status, religion, race or ethnicity.
- `Question(id, say, kind, options, range, asks, rule, reason)`, `Option(id, say)`, `Range(min, max, unit)`, `Rule(form, value)` and `Role(id, title, site, recruiter, questions)` are frozen dataclasses. `load_roles(path: Path = ROLES_PATH) -> dict[str, Role]`, `role(role_id: str) -> Role | None` and `spoken_value(question: Question, value: str) -> str` ("yes", "no", "skipped", "not clear", the option's words, or the number and the unit).

### 5. The gate (`candidate_line/tools/rules.py`, lane A)

```python
@dataclass(frozen=True)
class GateResult:
    complete: bool  # every posted question has a recorded answer
    met: bool  # complete, and every recorded value meets its question's rule
    unasked: tuple[str, ...]  # question ids with no recorded answer, in posted order
    unmet: tuple[str, ...]  # question ids whose answer meets no rule (declined and unclear included)


def meets(question: Question, value: str) -> bool: ...
def check(role: Role, answers: Mapping[str, str]) -> GateResult: ...  # answers: question id to value
```

Pure: no file, clock, network, model or randomness; the same inputs always give the same result. `declined` and `unclear` meet no rule. Nothing in it weighs, sums or compares answers across questions or across applicants. Tested on every rule form, both sides of each bound, and every role in `data/roles.yaml` with an all-met and an each-one-unmet answer set.

### 6. `data/applications.yaml` (lane 0; read by the ledger, lane C)

```yaml
# SYNTHETIC. Generated by scripts/make_synthetic_data.py (seed 20261105) on 2026-11-05. No real person or record.
synthetic: true
firm: ACME
consent_texts:                  # each version the careers form has shown, word for word
  consent-2026-11-05: By ticking this box, I agree that ACME's automated hiring line may call ...
applications:
- code: ACME-3108               # ACME- and four digits, never a code in data/candidates.yaml
  first_name: Lerato
  role: care-aide               # a role id in data/roles.yaml
  zone: America/Chicago         # an IANA zone in the US
  pin: '4398'                   # the fixture's PIN as a string; an intake application keeps only its HMAC
  applied_at: '2026-11-04T09:35:00-06:00'
  consent: {version: consent-2026-11-05, accepted: true, at: '2026-11-04T09:33:36-06:00', source: careers-form}
```

No phone number and no email address: the fixtures hold none, and a test that needs a number injects a fictional 555-01xx one at run time.

### 7. The ledger overlay (`candidate_line/tools/ledger.py`, lane C)

`var/state.json` keeps its four keys and gains four. `_read_overlay` keeps every top-level key it does not know, unchanged, and `_write` writes them back, so an older or newer image never erases another's records.

- `applications`: `{code: {"code", "first_name", "role", "zone", "pin_hmac", "number_hmac", "consent": {"version", "text_sha256", "accepted", "at", "source"}, "received_at"}}`, for applications that arrived through intake. The fixtures stay in `data/applications.yaml` and are never copied here.
- `answers`: `{code: {"by_question": {question_id: {"value", "heard", "at", "call_id"}}, "screen": null | {"result": "met" | "not_met", "at", "call_id", "promised_by": ISO | null}}}`. `heard` is already scrubbed.
- `dials`: a list of dial records (section 8).
- `opt_outs`: a list of `{"code", "number_hmac", "at", "call_id", "how"}`; `how` is "said on the call", "said stop", "wrong person", "operator" or "deletion".

No raw number and no PIN digit is ever written to the overlay. The ledger's new surface (keyword arguments as named; every change written through under `_exclusive`):

```python
def derive_key(root: str, purpose: str) -> bytes                  # HMAC-SHA256(root, "candidate-line " + purpose)
def pin_hmac(key: bytes, code: str, pin: str) -> str              # hex HMAC-SHA256 over f"{code}:{pin}"
def number_hmac(key: bytes, e164: str) -> str                     # hex HMAC-SHA256 over the E.164 number

@dataclass(frozen=True)
class Applicant:
    code: str; first_name: str; role: str; zone: str; received_at: str
    consent: Mapping[str, Any]; number_hmac: str | None           # None for the fixtures
    @property
    def consented(self) -> bool: ...

class Ledger:
    def __init__(self, ..., applications_path=APPLICATIONS_PATH, roles_path=ROLES_PATH, pin_key: bytes | None = None): ...
    def applicant(self, code: object) -> Applicant | None
    def match(self, code: str, pin: str) -> Candidate | Applicant | None        # existing, now applicants too
    def match_applicant_pin(self, code: str, pin: str) -> Applicant | None      # the outbound confirmation
    def add_application(self, *, first_name, role, zone, pin, consent, number_hmac, received_at=None) -> Applicant
    def answers(self, code: str) -> dict[str, dict[str, Any]]
    def record_answer(self, code, question_id, value, heard, call_id) -> dict[str, Any] | None   # the previous record
    def restore_answer(self, code, question_id, previous: dict[str, Any] | None) -> None          # the undo
    def screen(self, code: str) -> dict[str, Any] | None
    def set_screen(self, code, result, call_id, promised_by) -> None
    def clear_screen(self, code: str) -> None
    def opt_out(self, code, how, call_id=None, number_hmac=None) -> int        # dials cancelled
    def opted_out(self, code: str | None = None, number_hmac: str | None = None) -> bool
    def schedule_dial(self, code: str, attempt: int, due_at: datetime) -> dict[str, Any]
    def claim_due_dial(self, now: datetime, max_per_day: int, ready: Callable[[dict[str, Any], Applicant], bool]) -> dict[str, Any] | None
    def bind_call(self, dial_id: str, call_sid: str) -> dict[str, Any] | None
    def update_dial(self, key: str, **fields: Any) -> dict[str, Any] | None   # key: a dial id or a CallSid
    def dial(self, key: str) -> dict[str, Any] | None
    def dials(self, code: str | None = None) -> list[dict[str, Any]]
    def dials_placed_today(self) -> int                                      # Central-time day, as calls_today
    def open_slots(self, day=None, limit=MAX_LISTED, recruiter: str | None = None) -> list[Slot]   # recruiter: that recruiter's interview slots only
    def forget(self, code: str) -> None                                      # a deletion request (spec 9.13)
```

`claim_due_dial` returns None while any dial is `claimed`, `placed` or `in-progress` (one at a time), when `dials_placed_today()` has reached `max_per_day`, or when no `due` dial is due by `now` whose applicant has consented, has not opted out and passes `ready` (the dialler's window check). The claim sets `status: claimed` under the file lock, so it is placed once. `state(code)` for an applicant returns `{"booked_slot", "answers_recorded", "questions_left", "screen", "opted_out", "dials_due", "callback_requested"}`; a candidate's state is unchanged. `book()` and `state()` read applicants beside `data/candidates.yaml`, and `book()` refuses an applicant whose screen is not `met` (kind `screen_not_met`).

### 8. The dial record

```json
{"dial_id": "D-3f9a1c2b7e4d", "code": "ACME-3108", "attempt": 1,
 "due_at": "2026-11-05T16:02:00+00:00", "status": "due",
 "claimed_at": null, "placed_at": null, "call_sid": null,
 "twilio_status": null, "answered_at": null, "answered_by": null,
 "voicemail_left": false, "ended_at": null, "outcome": null}
```

`status`: `due`, `claimed`, `placed`, `in-progress`, `done`, `cancelled` or `failed` (the REST call failed). `outcome`: `screened`, `screen_unfinished`, `voicemail`, `machine`, `no_answer`, `busy`, `failed`, `opted_out`, `wrong_person`, `pin_missed`, `hung_up_before_pin` or `kill`. Times are ISO UTC to the second, as the ledger stamps them. The dial id is 12 random hex characters after `D-`. A dial record never holds the number.

### 9. The contacts store (`candidate_line/outbound/contacts.py`, lane B)

The one store of raw numbers: `CONTACTS_PATH` (default `var/contacts.json`, on the encrypted volume), mode 600, written through atomically under its own lock, read only by the dialler. `{"version": 1, "contacts": {code: {"number": "+1...", "added_at", "delete_after"}}}`. `Contacts(path)`, `put(code, e164, now)`, `number(code) -> str | None`, `delete(code) -> bool`, `purge(now) -> int` (run by the dialler once an hour). Every other path gets `mask_number`.

### 10. Intake (`candidate_line/outbound/intake.py`, lane B)

`POST /applications`, mounted by `create_app`. Headers `X-Intake-Timestamp` (Unix seconds) and `X-Intake-Signature` (hex HMAC-SHA256 under INTAKE_SIGNING_KEY over `f"{timestamp}.{raw body}"`). 503 when the key is unset; 401 on a bad or missing signature, a timestamp more than 300 s off, or a signature already seen inside that window; 413 over 4 KB; 422 on the schema. The pydantic model forbids extra keys: `first_name` (1 to 40 letters, spaces, hyphens, apostrophes), `role` (a role id), `phone` (`^\+1[2-9]\d{2}[2-9]\d{6}$`), `zone` (an IANA zone under `America/` or `Pacific/Honolulu`), `pin` (four digits), `consent` (`version` in `consent_texts`, `accepted` bool, `at` ISO, `source` one of `careers-form`, `ats`, `operator`). It writes the application (`add_application`, the PIN hashed there), the number (`Contacts.put`) and, with consent and no opt-out on the number's HMAC, the first dial (`schedule_dial(code, 1, window.next_in_window(received + 120 s, ...))`). It answers 202 `{"code": "ACME-dddd", "status": "scheduled" | "no_consent" | "opted_out"}`, never the number or the PIN, and logs the masked number only.

### 11. Settings (`candidate_line/settings.py`, lane B)

| Setting | Default | Rule at start |
| - | - | - |
| `OUTBOUND_ENABLED` | off (`0`) | `1` turns the dialler on; it then needs the four below or the process stops |
| `MAX_OUTBOUND_PER_DAY` | 20 | a whole number of at least 1; dials placed per Central-time day |
| `MAX_CONCURRENT_OUTBOUND` | 1 | must be 1 this week (one 0.25 vCPU task); any other value stops the process |
| `CALL_WINDOW` | `09:00-20:00 Mon-Sat` | `HH:MM-HH:MM` and a day range, in the applicant's zone; an empty or reversed window stops the process |
| `MAX_DIAL_ATTEMPTS` | 3 | a whole number from 1 to 3 |
| `INTAKE_SIGNING_KEY` | none (a secret) | required with outbound on; the PIN and number HMAC keys derive from it |
| `CONTACTS_PATH` | `var/contacts.json` | an empty value reads as unset |
| `CONTACTS_RETENTION_DAYS` | 30 | a whole number of at least 1 |
| `TWILIO_LINE_NUMBER` | none (a secret, already typed) | required with outbound on: the From of every dial and the number the voicemail says |
| `TWILIO_ACCOUNT_SID` | none (a secret, already typed) | required with outbound on |
| `MAX_OUTBOUND_CALL_SECONDS` | 480 | a whole number of at least 1; inbound keeps `MAX_CALL_SECONDS` 300 |

`CallWindow(start: time, end: time, days: frozenset[int])` is parsed in `settings.py`. No number, key or account id has a default in the file.

### 12. The outbound `/voice`, `/media` and the callbacks (`candidate_line/telephony/app.py`, lane B)

- **The dial.** The dialler places `Calls.json` with `To` (from the contacts store), `From` (TWILIO_LINE_NUMBER), `Url` = `{PUBLIC_BASE_URL}/voice?dial={dial_id}`, `StatusCallback` = `{PUBLIC_BASE_URL}/voice/status` with `StatusCallbackEvent` `answered` and `completed`, `MachineDetection=DetectMessageEnd`, `AsyncAmd=true`, `AsyncAmdStatusCallback` = `{PUBLIC_BASE_URL}/voice/amd`, `Timeout` 30 and `TimeLimit` = MAX_OUTBOUND_CALL_SECONDS + 60 (the Calls resource page, read 2026-11-05). The dial id rides in the query, which Twilio's signature covers (`public_url` keeps the query), because Twilio may fetch the Url before the dialler has written the CallSid from the REST reply.
- **`/voice` on an outbound call.** The same signature check. `Direction` is `outbound-api` for a call placed through the REST API. The dial record is found by CallSid, or by the `dial` query value with no CallSid yet bound, which `bind_call` then binds; no record answers `<Response><Hangup/></Response>` and logs it. The inbound daily count is skipped. `start_call(call_sid, "outbound", caller=form["To"], ...)`, so the store masks the applicant's number and never names the line's own. The kill switch, a lost consent or an opt-out since the claim answers `<Hangup/>`. Otherwise the stream token is minted as now and the answer is `<Response><Say voice="Polly.Matthew-Neural">{opening}</Say><Connect><Stream url="wss://.../media"><Parameter name="token" value="..."/></Stream></Connect></Response>`: the opening plays at once and uncut, over the seconds the stream takes to start.
- **`/media` on an outbound call.** The dial record is read by the stream's CallSid, after the token check; `ctx.data["outbound"] = {"code", "first_name", "dial_id", "attempt"}` comes from it and never from anything the client sent. The session's greeting is the PIN ask, its tools `OUTBOUND_TOOL_SPECS`, its length cap MAX_OUTBOUND_CALL_SECONDS. At its end the dial's outcome is written in a worker thread.
- **`POST /voice/status`**, signature-checked: `CallSid`, `CallStatus` (`queued`, `initiated`, `ringing`, `in-progress`, `completed`, `busy`, `failed`, `no-answer`, `canceled`). It writes `twilio_status`; on `in-progress`, `answered_at`; on an end state, `ended_at`, and when no person was reached (no answer, busy, failed, or a machine) and attempts remain with no opt-out, it schedules the next attempt with `window.next_attempt`. It answers 204.
- **`POST /voice/amd`**, signature-checked: `CallSid`, `AnsweredBy` (with DetectMessageEnd: `machine_end_beep`, `machine_end_silence`, `machine_end_other`, `human`, `fax`, `unknown`), `MachineDetectionDuration`. `human` and `unknown` are written and the call goes on. A machine on the first attempt with no voicemail left: the live call is updated to `<Say>{voicemail line}</Say><Hangup/>`, `voicemail_left` true, outcome `voicemail`. A machine on a later attempt, or a fax: updated to `<Hangup/>`, outcome `machine` or `failed`. It answers 204.
- **One machine-detection mode.** Asynchronous detection that waits for the end of the greeting, and no synchronous path: the opening plays while detection listens, and a voicemail is left after the beep. Asynchronous detection takes one of the call's four forked audio streams while it listens, and Media Streams share that limit (the detection page, read 2026-11-05); one detection and one stream are two of four.

### 13. The fixed lines (`candidate_line/persona.py`, lane A)

Word for word as spec section 9.9 gives them, by these names: `OUTBOUND_OPENING` (with `{first_name}`), `PIN_ASK`, `PIN_RETRY_LINE`, `PIN_SECOND_MISS_LINE`, `INTRO_LINE` (with `{count}` and `{title}`), `ACK_LINE` = "Noted: {value}.", `UNCLEAR_LINE`, `MET_LINE` (with `{slots}`), `NO_SLOT_LINE`, `NOT_MET_LINE` (with `{asks}`), `VOICEMAIL_LINE` (with `{first_name}` and `{line_number}`, the number spoken digit by digit from settings at run time), `OUTBOUND_STOP_LINE`, and `VERIFIED_APPLICANT_LINE` = "Thank you, that's application {code_digits}." Helpers `outbound_opening(first_name)`, `intro_line(count, title)`, `ack_line(spoken_value)`, `met_line(labels)`, `not_met_line(asks)` and `voicemail_line(first_name, line_number)` return them filled. The brief gains a short screening block: call `record_answer` after every answer with the applicant's words; map only a plain answer to a posted value, anything else is unclear; never comment on an answer or say whether it meets anything; send any question about the answers or the outcome to `answer_question` (F9); a skip is declined. The brief's Never list follows section 5 once James words it.

### 14. The hooks (`candidate_line/hooks.py`, lane A)

- `_is_stop` stays as it is. A new phrase rule, `_is_opt_out(text)`, matches "don't call me", "do not call me", "stop calling", "take me off", "wrong number", "not me" and "you have the wrong person" as whole phrases, so "don't stop" is never one. On an outbound call, or for a verified applicant, either rule records the opt-out through `screening.record_opt_out(ctx, how)`, sets `ctx.data["say"] = OUTBOUND_STOP_LINE` and `hang_up`, with no model call. On an inbound call from anyone else, `_is_stop` keeps today's stop line and `_is_opt_out` goes to the model.
- On an outbound call before the PIN matches, a transcript made only of hello words ("hello", "hi", "hey", "yes", "yeah", "speaking", "this is she", "this is he", the first name) is answered by code with the PIN ask, at most twice a call, and no model call; a third goes to the model.
- `on_call_end` stays an observer for the tier-3 write-up. The dial's outcome is written by the media session and the status callback (section 12), in a worker thread.
- The kill switch closes an outbound call with `KILL_LINE`, as an inbound one; the dialler reads the same file.

### 15. The tiers and the escalation kind (lane A, `tiers.py` and `escalation.py`)

- `assign(tools_called, guard_hits=(), refused=False, verify_failures=0, spoken="", hand_offs=())`: tier 2 when the turn posted any hand-off (`hand_offs`, the `HandOff`s the turn's outcomes carried), whatever the tool; the existing tool-name rule stays for callers that pass none. `_DONE_ALONE` gains `confirm_applicant` ("confirmed the applicant by PIN"), `record_answer` ("recorded an answer") and `stop_calls` ("stopped every further call"). Tier 3 for a second PIN miss (the shared `verify_failures`) and for a call the length cap ended with questions left.
- The screening hand-off: `HandOff(reason=f"screening hand-off from {code} ({first_name}): {role title}; recruiter call promised by {when}", suggested_action="read the answers on the applicant's record and call them by the promised time; a person decides the application")`. `{when}` is the promised time in Central ("4:05 PM Central on Friday 6 November 2026"), one business day after the screen.
- `Escalation` gains `record_url: str | None = None` = `{COCKPIT_BASE_URL}/applicants/{code}`. `format_subject` gives "Screening hand-off: Lerato (ACME-3108)". `format_email` for this kind: "{first name} ({code}) answered the screening questions for the {role} role on the ACME line, and the line promised that a recruiter will call by {when}.", a blank line, "Read the answers on the applicant's record: {record_url}", "What to do: read the answers on the record and call the applicant by the promised time; a person decides every application.", and the call record line. It never carries an answer, the applicant's words, which requirement was not met, or the number, and a test holds it to that with every answer of the fixtures.

### 16. The cockpit's `/applicants` (lane C, `traces/cockpit.py`)

- `GET /applicants`: one row per application in arrival order (received time, oldest first), with no sort, no filter, no colour and no count by answer, and no column that holds an answer. Columns: code, first name, role, received (Central), consent (version, accepted or not), the line's status in words (waiting for the window, dialling, reached, booked with the slot, recruiter call promised by the time, opted out, no consent), attempts.
- `GET /applicants/{code}`: the applicant (first name, code, role, site, recruiter, received, the consent record, the masked number); then one row per posted question in posted order: the question as said, what the posting asks for, the posted reason, the recorded answer in spoken words, the applicant's own words (masked), when; then the line's outcome in plain words (never passed, failed, qualified or rejected); then the dials with their outcomes and links to the call traces.
- `POST /applicants/{code}/read` (`by`): logs the read as a `hook` span named `read` on the screening call, with `by`, `opened_at` and `read_seconds`, for the minutes-saved row.
- It reads the state file as `scorecard.ledger_bookings` does, never through `Ledger`, which sets a broken file aside.

### 17. The scorecard's rows (lane C, `scorecard.py`)

| Row | Method | n |
| - | - | - |
| Minutes from application to first contact | `received_at` to the `answered_at` of the first dial a person answered (detection `human` or `unknown`, and the stream started), from the ledger's dials; median and worst; arrivals inside the window apart from those that waited for it; never reached counted beside | applications reached |
| Answers captured per applicant | recorded answers other than `unclear` over the role's question count, per finished screen; median; `declined` counted beside | finished screens |
| Recruiter minutes saved (estimate) | met screens times the median minutes of `data/baseline_screens.csv`, less the reading minutes the cockpit logged; a not-met hand-off saves nothing, because a recruiter calls it back; labelled an estimate on a synthetic baseline | finished screens |
| The promise, a check row | met screens offered slots, n of n; not-met hand-offs replied to in the cockpit before their promised time, n of n; short of n is a defect | finished screens, hand-offs |

`calls_by_channel` counts `voice` and `outbound` apart; `hand_offs` counts the screening kind beside `request_callback` and `move_slot`.

### 18. The eval support (lane C, `evals/schema.py`, `evals/checks.py`, `evals/runner.py`)

- `CASE_KEYS` gains `outbound`: an application code from `data/applications.yaml`. The runner seeds `ctx.data["outbound"]` from it as the phone would, passes `OUTBOUND_TOOL_SPECS` to `run_turn` (it passes no tools today), keeps `EVAL_CLOCK`, and keeps the opening and the PIN ask out of the history, as the phone keeps its greeting out (Bedrock's Converse API wants a user message first).
- `TURN_KEYS` gains `fixed`: `opening` or `voicemail`; such a turn runs no model, and its spoken text is that fixed line for the case's applicant, so a check can read it.
- `CHECKS` gains `hand_off_matches` and `hand_off_not_matches`: a regular expression over the subject and the email body (`format_subject`, `format_email`) of every hand-off posted on the turn (`TurnResult.hand_offs`). `hand_off_matches` fails when no hand-off was posted.
- The `state` check reads the applicant's state keys (section 7).

### 19. The stack, the deploy and the Makefile (lane C)

The task definition gains secret references for `INTAKE_SIGNING_KEY` and `TWILIO_LINE_NUMBER` (the execution role already reads every `candidate-line/*` secret) and parameters for `OutboundEnabled` (default `0`), `MaxOutboundPerDay`, `CallWindow` and `MaxOutboundCallSeconds`. `DesiredCount: 1` and `MaximumPercent: 100` stay, since two tasks would be two diallers. No new AWS resource and no new permission. `scripts/deploy.sh` stores `INTAKE_SIGNING_KEY` from the keychain as the other secrets. The Makefile gains `dial-off` and `dial-on` (touch or remove `var/no-dial` on the task, as `line-off` does), `apply` (posts a signed synthetic application for a walk, with a 555-01xx number by default) and `forget CODE=` (the deletion request).

## Spend

Rates, each from a page saved in `docs/refs/`: Twilio outbound local 0.0140 USD a minute, answering machine detection 0.0075 USD a call, and text-to-speech premium neural 0.0032 USD per 100 characters (`2026-11-05-twilio-voice-pricing-us.txt`); Transcribe streaming 0.01 USD a minute and Polly neural 16.00 USD per million characters (2026-11-01 pages, DR-006); Haiku 5.5 at 0.10 and 0.50 USD per million tokens (`rates.py`). The opening's `<Say>` is taken as premium neural because it names a Polly neural voice [inference]. Per-minute rounding and whether an unanswered dial is billed are not on the saved page [inference: billed by the started minute, unanswered free].

- **A four-minute screen, about 0.14 USD** [inference; the four minutes are a hypothesis to measure on the dialled probe: opening 12 s, PIN 15 s, intro 12 s, five questions at 20 s, the offer and booking 60 s]: Twilio 0.056 (4 minutes), detection 0.0075, the opening's `<Say>` 0.0074 (230 characters), Transcribe 0.040, Polly 0.024 (about 1,500 characters of fixed lines and replies), Haiku about 0.002 (DR-019 measured 0.00024 USD a call over 36 cases; a screen has about eight model calls).
- **A call at the 480 s cap, about 0.26 USD:** Twilio 0.112, detection 0.0075, `<Say>` 0.0074, Transcribe 0.080, Polly about 0.048, Haiku about 0.004.
- **A voicemail attempt, about 0.04 USD:** one billed minute 0.014, detection 0.0075, the opening and the voicemail by `<Say>` about 0.016 (490 characters), Transcribe about 0.005.
- **The caps bound the bill with nobody calling.** At the defaults, 20 dials a day at the 480 s cap cost at most about 5.90 USD a day (20 times 0.295, a minute of Twilio, Transcribe and Polly at the most a call speaks), of which Twilio is about 2.50 USD (20 times 8 minutes at 0.014, plus detection and the opening). Twilio's TimeLimit ends a call 60 s after the line's own cap if the line has failed.
- **The monthly number at 10 screens a day** [inference], on 26 calling days (Monday to Saturday): 260 screens times 0.14 is 36.40 USD; with one voicemail for every two screens [hypothesis], 130 times 0.04 is 5.20 USD; about 42 USD a month on top of the fixed AWS cost of 35 to 37 USD with WAF (`docs/deploy/PLAN.md`). Split by who bills it: AWS about 17 USD (Transcribe and Polly, 0.064 a screen and 0.005 a voicemail), Twilio about 24 USD, Anthropic about 0.50 USD.
- **The budget stop and what it does not stop.** The 45 USD AWS budget action (DR-023) denies the task role's speech and model services when the month's actual AWS spend reaches it. At 10 screens a day the month-to-date AWS spend grows about 1.78 USD a day (1.20 fixed and 0.58 for the screens), so it reaches 45 USD on about day 25, and from then the line, inbound and outbound, fails closed for the rest of the month. Raising the stop is James's money decision (open decision 3 of card 08). The stop never reaches Twilio (minutes, detection, `<Say>`) or the Anthropic API (its own 50 USD workspace cap, DR-003), so the dialler carries those itself: it stops on its own caps, and before each dial it synthesises one short word with Polly and sets `var/no-dial` on AccessDenied, so it never dials into a line that cannot speak.

## Security

- **Signed intake.** HMAC-SHA256 over the timestamp and the body, 300 s of skew, a replay set over that window, a closed schema with extra keys refused, 4 KB at most. The WAF's rate rule and common rule set cover `/applications` (DR-023).
- **Raw numbers in one store.** The contacts store on the encrypted EFS volume, mode 600, read only by the dialler; masked in every trace, log, post, email and cockpit page (`mask_number`). Anyone with `execute-command` on the task can read the file, so the operator's own sign-in is that boundary.
- **The PIN as an HMAC.** A four-digit PIN has 10,000 values, so an unkeyed hash would be no protection; the PIN key derives from INTAKE_SIGNING_KEY, which lives only in Secrets Manager and the task's environment. Compared in constant time; never in a span, a log or a post. Rotating the key orphans the stored PINs, so a rotation re-keys or re-asks (open decision 6 of card 08).
- **Consent records, versioned.** The version, a SHA-256 of the text shown, accepted or not, the time and the source, per application; the text of each version in `data/applications.yaml`'s `consent_texts`. A deletion keeps the version, the time and the number's HMAC as the evidence of consent and of the opt-out.
- **Retention and deletion.** Contacts deleted after CONTACTS_RETENTION_DAYS, at once on an opt-out, and on a deletion request (`make forget CODE=`), which removes the application, its answers, its dials and its contact.
- **No answer in any email.** The screening hand-off names the applicant, the role, the promised time and the record link; a test holds every fixture answer and heard word out of the subject and the body.
- **Least privilege.** No new AWS resource or permission. Two new secrets in Secrets Manager. The Twilio client uses the account SID and auth token the task already holds. The dialler can dial only a number in the contacts store whose application consented and has not opted out.
- **Bound to the dial.** `/voice/status` and `/voice/amd` check Twilio's signature as `/voice` does; an outbound `/voice` needs a dial record, found by the CallSid or the signed dial id; `/media` seeds the call from the dial record, never from the client's parameters; the stream token stays.
- **The two stops.** The kill switch (`var/kill`) closes every call and stops the dialler; the opt-out stops every dial to that number, at once. `var/no-dial` stops the dialler alone.
- **One dialler.** One task (`DesiredCount: 1`, `MaximumPercent: 100`) and the claim under the ledger's file lock, so a dial is placed once.
- **The model decides no gate.** The roles loader refuses any form but the closed rules and any question on a topic the line never asks about; the gate is a pure function; the not-met line and the hand-off carry fixed words.

## The code fixes each lane must close

From the review of the design (2026-11-05), each with its lane:

1. **The 300 s cap.** An outbound call uses MAX_OUTBOUND_CALL_SECONDS (480), so five questions and a booking fit; inbound keeps 300 (lane B: `settings.py`, `telephony/app.py`, `telephony/media.py`).
2. **The hello and barge-in on the disclosure.** The opening is Twilio's `<Say>` before `<Connect><Stream>`, so nothing can barge in on it; the stream's first line is the PIN ask, said at once; before the PIN matches, hello words never barge in and never reach the model (lane B: `telephony/app.py`, `telephony/media.py`; lane A: the hello rule in `hooks.py`).
3. **`_spoken_cap` on the completion line.** The say branch skips `_spoken_cap`, `_name_sections` and the own-refusal check, so the met line reaches its slots and its question (lane A: `turn.py`).
4. **The stop phrases.** "Don't call me", "stop calling", "take me off", "wrong number" and "not me" get their own phrase rule; `_STOP_WORDS` is not widened (lane A: `hooks.py`).
5. **`on_call_end` off the event loop.** The media session runs `on_call_end` and the dial's outcome write with `asyncio.to_thread` (lane B: `telephony/media.py`).
6. **`_read_overlay` keeps unknown keys**, and `_write` writes them back (lane C: `tools/ledger.py`). The image running today drops them, so this lands, and is deployed, before any outbound record exists; a rollback past it would erase applications, dials and opt-outs.
7. **`start_call`'s From on an outbound call.** An outbound call records `To` as the caller and `outbound` as the channel, so no hand-off or cockpit page names the line's own number (lane B: `telephony/app.py`).
8. **One machine-detection mode.** `DetectMessageEnd` with `AsyncAmd=true` and the detection callback; no synchronous detection and no voicemail from `/voice` (lane B: `telephony/twilio_rest.py`, `outbound/dialler.py`, `telephony/app.py`).
9. **The escalation kind.** "screening hand-off" in `format_subject` and `format_email`, with the record link and no answers (lane A: `escalation.py`).
10. **Tiers by outcome.** `assign` reads the hand-offs the turn posted, not only tool names; the scorecard's hand-off count follows (lane A: `tiers.py`; lane C: `scorecard.py`).
11. **Applicants in `book()` and `state()`**, and the ledger refusing a booking for a screen not met (lane C: `tools/ledger.py`).
12. **The runner passes the tools** to `run_turn`, and the cockpit reads the state file without `Ledger` (lane C: `evals/runner.py`, `traces/cockpit.py`).

## The alternative rejected, and why

- **No gate: every applicant who reaches the last question is offered slots** (the design notes' default, 2026-11-05). Kept as the fallback: the same code with the not-met branch replaced by the met branch in `screening.py` and the not-met line unused, and the recruiter applies the posted requirements after reading. Its cost: a recruiter interviews every applicant the posting excludes, at about the baseline's median screen minutes each (`data/baseline_screens.csv`, synthetic), and the line promises a time to people the employer will not hire. It is the fallback if counsel reads the gate as a tool that needs a bias audit before use in New York City (Local Law 144) or another rule the gate cannot meet in time. The review put the fallback at about 15.5 agent-hours against 17.5 for the gate.
- **Scoring:** a number, a rank or a weighted sum over the answers. It breaks Never 1 in any wording, it is the plain case of an automated employment decision tool, and it would compare applicants with each other, which the gate never does.
- **Text first:** screening by SMS. US application-to-person texting needs carrier registration before the first message, every message is read later rather than answered now, and the line's tested path is voice; the speed the ruling asks for (within minutes) is a call.
- **First-name confirmation without a PIN:** quicker, and the usual pattern, but it reads the record to whoever answers the phone, which Never 5 forbids.
- **The voicemail from `/voice` on a synchronous machine answer:** a person who picks up waits in silence while detection decides; asynchronous detection lets the opening play at once.

## What would change the decision

Counsel's read of the consent text, the hour rules, the Illinois notice and whether the gate's yes or no counts as simplified output under New York City's rules (then the fallback, or a bias audit first); James's words on Never 1 and Never 7; a measured voicemail misfire rate on the dialled probes; a second task (then the claim moves to a store two tasks share); a cost reading over the Spend estimate after the first full week.

## Evidence

- Twilio's Calls resource page, read 2026-11-05 (`docs/refs/2026-11-05-twilio-calls-resource.txt`): the create parameters `Url`, `From`, `MachineDetection` (`Enable` or `DetectMessageEnd`), `AsyncAmd`, `AsyncAmdStatusCallback`, `StatusCallback`, `StatusCallbackEvent` (`initiated`, `ringing`, `answered`, `completed`), `Timeout` (default 60 s) and `TimeLimit`; `Direction` is `outbound-api` for a call placed through the REST API; `AnsweredBy` is set when detection ran.
- The same page's Update a Call: a POST to the call's own resource with `Twiml` (or `Url`, or `Status=completed`) changes a call in progress, which is how a machine's verdict turns the live call into the voicemail or a hang-up.
- Twilio's answering machine detection page, read 2026-11-05 (`docs/refs/2026-11-05-twilio-answering-machine-detection.txt`): with `DetectMessageEnd` a person is reported at once and a machine only at the end of its greeting; the `AnsweredBy` values; asynchronous detection lets the call go on and takes one of four forked audio streams while it listens.
- Twilio's US voice pricing page, read 2026-11-05 (`docs/refs/2026-11-05-twilio-voice-pricing-us.txt`): the rates in Spend, "current as of August 2026".
- 47 CFR 64.1200, read 2026-11-05 from the eCFR (`docs/refs/2026-11-05-ecfr-47-cfr-64-1200.txt`): (a)(1) prior express consent for an artificial-voice call to a mobile number; (a)(10) revocation by any reasonable means, honoured within ten business days; (b)(1) the business's identity at the beginning of the message and (b)(2) a telephone number during or after it; (c)(1) the 08:00 to 21:00 limit for a telephone solicitation.
- The FCC's Declaratory Ruling of 8 February 2024, FCC 24-17, read 2026-11-05 (`docs/refs/2026-11-05-fcc-24-17-ai-voices-declaratory-ruling.txt`): the TCPA's "artificial or prerecorded voice" covers AI technologies that generate human voices, so a call that uses one needs the called party's prior express consent (paragraphs 2, 5 and 9), there is no carve-out for a technology that stands in for a live agent (paragraph 6), and 64.1200(b)'s identification and disclosure rules apply (paragraph 9). This is why consent is taken at intake and versioned, and why the opening names ACME first.
- New York City's DCWP page and its AEDT FAQ of 2023-06-29, read 2026-11-05 (`docs/refs/2026-11-05-nyc-dcwp-aedt-faq.txt`): an AEDT uses machine learning, statistical modeling, data analytics or AI, helps make employment decisions, and substantially assists or replaces discretionary decision-making; screening counts as an employment decision; the law needs a bias audit within a year before use and a notice to New York City candidates 10 business days before use, with the job qualifications the tool assesses and how to ask for an accommodation. Whether a fixed comparison of an applicant's own answer with a posted requirement is such a tool is counsel's question (card 08, open decision 2) [inference: the gate uses no model and no statistics, but a model maps the words to the value it compares].
- Illinois Public Act 103-0804, re-read 2026-11-05 (`docs/refs/2026-11-05-illinois-public-act-103-0804.txt`), in effect since 1 January 2026: an employer may not use AI with the effect of discrimination on a protected class, or zip codes as a proxy for one, in recruitment and hiring, and must give notice that it uses AI; the Department's rules set the notice. The roles loader refuses a zip-code question for this reason.
- The California Civil Rights Council's automated-decision system regulations, summary page of 30 June 2025, read 2026-11-05 (`docs/refs/2026-11-05-california-crc-ads-regulations.txt`), in effect since 1 October 2025: an automated-decision system may violate California law if it harms applicants on a protected characteristic; employment records, including automated-decision data, are kept at least four years; and an assessment's questions that elicit information about a disability may be an unlawful medical inquiry. So the retention decision (card 08, open decision 4) reads four years for any applicant in California, and the lifting questions carry the accommodation clause and go to counsel with the rest.
- The cost figures in Spend are arithmetic on those rates, labelled [inference] or [hypothesis]; nothing is measured yet. The dialled probes (met and not met) and James's own call measure the screen's minutes, its characters and the first contact time.

## Say it like this

> (written after the teach-back)

## Teach-back

(not yet)
