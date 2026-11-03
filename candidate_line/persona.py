"""Gus's words. The persona is a Wednesday work item (PREBUILT.md); this is the placeholder text mode runs on
until then, so nothing here decides anything about a caller."""

PLACEHOLDER_SYSTEM = (
    "You are Gus, the phone line for ACME's job candidates. Plain words, one or two short sentences. "
    "The real instructions are not written yet; if asked anything about a person, say that you do not "
    "evaluate people and offer to help with the process instead."
)

# Card 04 writes the persona here, in this name; every path (the phone, text mode, the eval runner) reads it
# through Settings.system_prompt(), which prefers SYSTEM_PROMPT_FILE when that is set (the bake-off, DR-001).
SYSTEM_PROMPT = PLACEHOLDER_SYSTEM

# The reply cap the turn loop uses. Output tokens set the turn's latency (DR-003: 901 ms median at 60 tokens, over
# a second at 120); card 04 lowers this beside the persona it writes, and the eval run's latency line shows it.
REPLY_MAX_TOKENS = 200

GREETING = "ACME candidate line, this is Gus."

# Arm A before Wednesday: the model repeats the caller, so the audio path is proven with nothing deciding anything.
ECHO_SYSTEM = "Repeat the caller's words back to them, exactly, and say nothing else."
