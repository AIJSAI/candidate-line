"""Gus's words: the system prompt every path speaks with, and the fixed lines the loop and the hooks say themselves.

Why the fixed lines live here and not in the prompt alone: a line the spec gives word for word (the refusal, the
guard's fallback, the stop, the kill switch, the holding lines) is said by code, never by the model, because asked
to say one the model rewords it (card 04's second dry run: five runs of seven). Why the FAQ index and not the FAQ:
answer_question hands the model the sections it names, so every process answer carries its ids (spec.md section 6).
"""

from candidate_line.tools.faq import faq_index

PLACEHOLDER_SYSTEM = (
    "You are Gus, the phone line for ACME's job candidates. Plain words, one or two short sentences. "
    "The real instructions are not written yet; if asked anything about a person, say that you do not "
    "evaluate people and offer to help with the process instead."
)

# The lines spec.md sections 6 and 7 give word for word.
REFUSAL_LINE = "That's not something I have an answer for. I can ask the coordinator to call you back."
FALLBACK_LINE = "I can't speak to that. I can help with the process, a slot, or a callback."
STOP_LINE = "Understood. Goodbye."
KILL_LINE = "The line is closing for now. Please call back later. Goodbye."
HOLDING_LINE = "Take your time. I'm still here."
HOLD_LIMIT_LINE = "I'll let you go for now. Call back any time. Goodbye."
# Said when a turn cannot finish (the model error the phone catches, or a tool loop that never settles).
RECOVERY_LINE = "Sorry, I lost that. Could you say it again?"
# Said between turns once a call passes Settings.max_call_seconds (DR-021), then the call ends.
LENGTH_LINE = "We're at the five-minute mark, so I'll let you go. Call back any time. Goodbye."

# The first sentence says the line is automated, so a caller never takes the human name that follows for a person
# (KICKOFF.md section 1; spec section 5, Never 3).
GREETING = "ACME's automated candidate line. This is Gus. How can I help?"


# The outbound call's lines, word for word as spec section 9.9 gives them (DR-025 section 13). Code says each one,
# so every applicant hears the same words after the same answer, and the model never words a reaction to an answer.
# The opening is Twilio's <Say> before the stream opens; before the PIN it names nothing from the record but the
# first name the applicant gave (spec section 5, Never 5).
OUTBOUND_OPENING = (
    "Hello, this is ACME's automated hiring line, calling for {first_name} about a job application. I'm Gus, an "
    "automated voice, and this call is transcribed so a recruiter can read your answers. No audio is kept."
)
PIN_ASK = (
    "To go on, please say the four-digit PIN you chose when you applied. Or say stop, and this line won't call "
    "you again."
)
PIN_RETRY_LINE = "That PIN didn't match. Please say the four digits once more."
PIN_SECOND_MISS_LINE = (
    "That didn't match either, so I can't go on with the questions on this call. I can ask a recruiter to call "
    "this number back. Would you like that?"
)
# The person line is the build's ruling of 5 November 2026 on card 08's open decision 8: one spoken line offers a
# person at any time, and the model routes "person" to request_callback.
PERSON_LINE = "Say person at any time and a recruiter will call you instead."
INTRO_LINE = (
    "Thank you. I have {count} questions the employer posted for the {title} role. I'll note each answer as you "
    "give it, and you can skip any. "
    + PERSON_LINE
    + " After the last one, I'll either offer interview times or "
    "tell you when a recruiter will call."
)
ACK_LINE = "Noted: {value}."
UNCLEAR_LINE = "Sorry, I didn't catch that."
MET_LINE = (
    "That's every question, thank you. A recruiter will read all your answers before the interview. The nearest "
    "open interview times are {slots}. Which suits you?"
)
NO_SLOT_LINE = (
    "That's every question, thank you. There are no open interview times right now, so a recruiter will call "
    "you within one business day to set one."
)
NOT_MET_LINE = (
    "That's every question, thank you. For this role, the posting asks for {asks}. A recruiter will read your "
    "answers and call you within one business day."
)
VOICEMAIL_LINE = (
    "This is ACME's automated hiring line with a message for {first_name} about a job application. Please call "
    "us back at {line_number}, or we'll try again later. To stop these calls, call that number and say stop."
)
OUTBOUND_STOP_LINE = "Understood. This line won't call this number again. Goodbye."
VERIFIED_APPLICANT_LINE = "Thank you, that's application {code_digits}."


def outbound_opening(first_name: str) -> str:
    return OUTBOUND_OPENING.format(first_name=first_name)


def intro_line(count: int, title: str) -> str:
    return INTRO_LINE.format(count=count, title=title)


def ack_line(spoken_value: str) -> str:
    return ACK_LINE.format(value=spoken_value)


def met_line(labels: list[str] | tuple[str, ...]) -> str:
    return MET_LINE.format(slots=_and(labels))


def not_met_line(asks: list[str] | tuple[str, ...]) -> str:
    # Joined by "and" alone, as spec 9.9 says: a posted "asks" may hold its own commas.
    return NOT_MET_LINE.format(asks=" and ".join(asks))


def verified_applicant_line(code_digits: str) -> str:
    return VERIFIED_APPLICANT_LINE.format(code_digits=code_digits)


def voicemail_line(first_name: str, line_number: str) -> str:
    """The number is the line's own, from TWILIO_LINE_NUMBER at run time, said digit by digit in its three
    groups; it is never written in a file (spec 9.9)."""
    return VOICEMAIL_LINE.format(first_name=first_name, line_number=spoken_number(line_number))


def spoken_number(e164: str) -> str:
    """A US number in E.164 form as its ten national digits in their three groups of three, three and four, each
    digit said apart, so the voice never reads a group as a number. Anything else is read digit by digit."""
    digits = "".join(ch for ch in e164 if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return " ".join(digits)
    return ", ".join(" ".join(part) for part in (digits[:3], digits[3:6], digits[6:]))


def _and(items: list[str] | tuple[str, ...]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def length_line(max_call_seconds: float) -> str:
    """The length line for this cap. Only the default is worded as five minutes; any other cap is "the time
    limit", so the line never states a length the setting does not hold."""
    if max_call_seconds == 300:
        return LENGTH_LINE
    return LENGTH_LINE.replace("the five-minute mark", "the time limit")


# The brief, under 300 words without the index (card 04). The Never list is spec.md section 5's rule sentences
# as written, without their case ids. Lines from the live eval runs of card 02 (DR-017): the application number is
# the code, because the 16:26 CT test call said "application 3233" and was asked for the code again (the example
# is no record's code, so the model cannot verify with it); no word about the PIN after a match, because the
# guard's pin-03 rule replaced "your PIN was received" and the code read back with it; a pick with no day and time
# read back before booking (spec 3.3), because "the first one" was booked at once; and a callback taken at once,
# because the model asked again for a time the caller had given. Lines from the review walk of 2026-11-04: every
# process question through the tool, pay and other candidates named, because the model refused those in its own
# words (5 of 5) and the loop then said no refusal line and wrote nothing up; a named day and time booked in the
# same turn, because it was read back in 2 of 2; a move handed off at once; no PIN digits in any form, because Gus
# said a caller's PIN back in words when asked; each section named by its own heading, because the fixed example
# was copied onto F5.1; the confirmation from the tool, which cites F3.1; a time zone passed to list_open_slots,
# because F3.4 promises the slot in it and Gus contradicted himself; and no closing offer or added fact,
# because 25 of 38 replies ended on an offer and refusals carried claims the FAQ does not make. The screening
# block is card 08's (DR-025 section 13): the model maps an answer to a posted value and nothing more, because
# the line says every question and every line after an answer by code; a question about the outcome goes to F9.
# The first Never line is the proposed Never 1 of spec section 5, put in at the merge of card 08 (2026-11-05),
# because the line now makes one check and the brief says what that check is and who decides.
BRIEF = """You are Gus, ACME's automated line for job candidates. Your words are spoken; the transcriber mishears callers.

Voice: dry, plain, at most two short sentences; no lists, markdown or emoji. End on the answer. A refusal is one sentence and adds no fact.

Never:
No score, ranking, opinion, comparison between people or predicted outcome about any person, the caller included. The line's one check is code comparing an applicant's own answer with a requirement the employer posted; it is never spoken as a judgment, and a person makes every hiring decision.
No process answer from anywhere but the FAQ sections the tool returned.
Never passes for a person: asked, Gus says it is an automated line.
Never says a PIN aloud, in a reply or a trace.
Never books, moves or reads a record for an unverified caller.
Never moves a slot itself.

Verify: get the code and PIN, then call verify_caller. "Application 4821" is the code, ACME-4821. Never ask whether the caller is the candidate. On a match, read the code back as digits; never say a PIN's digits in any form, even the caller's own. First miss: ask again. Second miss: offer a callback.

Book: offer the nearest few. For a named day and time, call list_open_slots for that day, then book_slot with its id in the same turn, no read-back. Read back any other pick; book on the yes. Then say the day, time and confirmation. Given a time zone, call list_open_slots with it and say both times.

Move: call move_slot at once; say what it returns.

Questions: every process question, pay, other candidates and dress code included, goes to answer_question with the ids whose titles fit, or an empty list; never refuse one in your own words. Answer only from what it returns, naming each section's heading and id. If their text does not answer it, call again with an empty list.

Callbacks: request_callback at once, with any time.

Screening (an applicant, once confirmed or verified): the line says each question itself. After every answer, call record_answer with the question id the last result named, a value it allows, and the applicant's words. Map only a plain answer to a value; anything else is unclear, and a skip is declined. Never comment on an answer or say whether it meets anything. A question about the answers or the outcome goes to answer_question (F9). "Person" or a recruiter asked for: request_callback at once.

On a call the line placed: ask only for the PIN, then confirm_applicant. A request not to be called again goes to stop_calls.

Goodbye or stop: one sentence, then end_call.

FAQ index:
"""

# Rendered once at import: the persona and the index are the same on every turn of every call, which is what lets
# the Anthropic brain's prompt cache hold them (DR-003).
SYSTEM_PROMPT = BRIEF + faq_index()

# The reply cap the turn loop uses. A tool call's arguments spend output tokens, so 100 cut a verify_caller call off
# before its PIN and 250 fit two whole calls (card 04's notes); the persona's words keep the spoken reply short.
REPLY_MAX_TOKENS = 250

# Arm A before Wednesday: the model repeats the caller, so the audio path is proven with nothing deciding anything.
ECHO_SYSTEM = "Repeat the caller's words back to them, exactly, and say nothing else."
