"""Turns what the transcriber wrote for an application code or a PIN into the four digits the records hold.

Why its own module: the transcriber hears "ACME" as "acne" or "application", writes 3233 as "3,233" or "32 33",
and drops a PIN's leading zero, so a caller who said the right thing would fail verification without one
forgiving parser that the tool and its tests share.
"""

from __future__ import annotations

import re

_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_NUMERAL = re.compile(r"[0-9]")
_WORD = re.compile(r"[a-z]+")


def _digits(text: object) -> str:
    """Numerals win. Spelled digits count only when there are no numerals at all, so a stray "oh" or "one" in
    "oh, it's one sec, 3233" never becomes an extra digit."""
    if text is None or isinstance(text, bool):
        return ""
    if isinstance(text, float) and text.is_integer():
        text = int(text)
    raw = str(text)
    numerals = "".join(_NUMERAL.findall(raw))
    if numerals:
        return numerals
    return "".join(_DIGIT_WORDS[w] for w in _WORD.findall(raw.lower()) if w in _DIGIT_WORDS)


def code_digits(text: object) -> str | None:
    """The four digits of an application code, whatever came before them ("ACME-", "acne", "application"), or
    None when the text does not hold exactly four."""
    digits = _digits(text)
    return digits if len(digits) == 4 else None


def pin_digits(text: object) -> str | None:
    """The four digits of a PIN, leading zeros kept. Three digits are read as a PIN whose leading zero the
    transcriber dropped ("963" for 0963), because a spoken "zero" or "oh" is the digit it loses most."""
    digits = _digits(text)
    if len(digits) == 4:
        return digits
    if len(digits) == 3:
        return f"0{digits}"
    return None


def code_label(digits: str) -> str:
    """The code as the records write it."""
    return f"ACME-{digits}"


def spoken_digits(digits: str) -> str:
    """Digits apart, so the voice reads "3 2 3 3" one by one and never as a number."""
    return " ".join(digits)


# The transcript normaliser LineHooks.on_turn runs, so the brain reads "ACME-3233" and "PIN 9683" where the
# transcriber wrote "acne 3,233 PI 96 83" (DR-006). Digits are joined only after a cue word, because "9 30" with no
# cue is a time; a four-digit number with a thousands comma is joined anywhere, since no caller here says money.
_DIGIT_TOKEN = r"(?:[0-9]|(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b)"
_GAP = r"[\s,.\-]{0,2}"
_ACME_WORD = r"(?:a\.?\s?c\.?\s?m\.?\s?e|acne|akme|ackme|acmi|acmy|ac\s?me|ak\s?me|act\s?me)(?:'s)?"
_CODE_WORD = r"(?:application\s+(?:code|number)|application|code|coat|coed|cold)"
_FILLER = r"(?:\s+(?:number|is|it's|its|was))*"
_MISHEARD_CODE = {"coat", "coed", "cold"}
_APPLICATION_ALONE = {"application", "application number"}
_CODE = re.compile(
    rf"(?P<lead>\b(?P<word>{_CODE_WORD})\b{_FILLER}[\s:,\-]*)?(?:(?P<acme>\b{_ACME_WORD}\b)[\s,:.\-]*)?"
    rf"(?P<digits>{_DIGIT_TOKEN}(?:{_GAP}{_DIGIT_TOKEN}){{3}})(?![0-9])",
    re.IGNORECASE,
)
# "PI" and "pen" are how the transcriber wrote PIN on the 2026-11-04 test call and the dry runs; each counts only
# with digits right after it.
_PIN_WORD = r"(?:pin|pins|pin's|pinn|pen|pi|pie|pim|ping|bin|p\.?\s?i\.?\s?n\.?)"
_PIN = re.compile(
    rf"\b{_PIN_WORD}\b(?:\s*(?:number|no\.?|code|is|it's|its|was|[:,\-]))*\s*"
    rf"(?P<digits>{_DIGIT_TOKEN}(?:{_GAP}{_DIGIT_TOKEN}){{2,3}})(?![0-9])",
    re.IGNORECASE,
)
_THOUSANDS = re.compile(r"(?<![0-9,])([0-9]),([0-9]{3})(?![0-9]|,[0-9])")
# Transcribe groups a long run of digits with thousands commas, and not always where a thousands comma goes: the
# probe's "application 3233 PI 9683" reached the deployed line on 2026-11-05 as "application 3,2339,683", the PIN's
# word lost and the two numbers run into one (the trace store's masked final, confidence 0.971; CL-021, DR-024). So
# a run with commas and no spaces is read as its digits. Eight of them with no code anywhere else are the code and
# the PIN said in one breath; four of them right after a code are its PIN.
_GROUPED = re.compile(r"(?<![\w,\-])[0-9]{1,4}(?:,[0-9]{1,4})+(?!\w|,[0-9])")
_AFTER_CODE = re.compile(r"[\s,]*(?:and\s+)?", re.IGNORECASE)


def _joined(digits: str) -> str:
    """The numerals of a run, with spelled digits turned into numerals ("oh nine 6 3" is 0963)."""
    tokens = re.findall(r"[0-9]|[a-z]+", digits.lower())
    return "".join(_DIGIT_WORDS.get(t, t) for t in tokens if t.isdigit() or t in _DIGIT_WORDS)


def _code(match: re.Match[str]) -> str:
    if not match.group("lead") and not match.group("acme"):
        return match.group(0)  # four digits with no cue may be anything; the brain reads them as said
    lead = match.group("lead") or ""
    word = match.group("word")
    if word and word.lower() in _MISHEARD_CODE:
        lead = "code" + lead[len(word) :]  # "coat 3233" was "code 3233"; the caller's other words stay
    elif word and re.sub(r"\s+", " ", word.lower()) in _APPLICATION_ALONE:
        # "application 3233" read to the model as a second number beside the code, and the 16:26 CT test call
        # was asked for the code again (the first live eval run of card 02, CL-021); the invitation calls it a code.
        lead = word[: len("application")] + " code" + lead[len(word) :]  # the caller's capital stays
    if lead:
        lead = lead.rstrip(" -") + " "
    return f"{lead}{code_label(_joined(match.group('digits')))}"


# A bare run of four digits beside a PIN is the code even with no cue word: on the operator's first call to the
# container (2026-11-04, 20:14 CT) the transcriber wrote "it's 323-3 and the PIN is 9683", the hyphen kept the
# model from reading a code, and the caller paid a turn to say it again. A time ("9:30") has a colon, which the
# gap never spans, and a year beside a PIN is not a thing a caller says.
_BARE_CODE = re.compile(
    rf"(?<![0-9A-Za-z-])(?P<digits>{_DIGIT_TOKEN}(?:{_GAP}{_DIGIT_TOKEN}){{3}})(?![0-9])", re.IGNORECASE
)


def _bare_code_beside_pin(text: str) -> str:
    if "PIN " not in text or "ACME-" in text:
        return text
    pin_at = text.index("PIN ")
    for match in _BARE_CODE.finditer(text):
        if match.start() < pin_at and len(_joined(match.group("digits"))) == 4:
            return text[: match.start()] + code_label(_joined(match.group("digits"))) + text[match.end() :]
    return text


def _cued_codes(text: str) -> list[re.Match[str]]:
    """The codes in the text that carry a cue, a code word or ACME; four digits alone may be anything."""
    return [m for m in _CODE.finditer(text) if m.group("lead") or m.group("acme")]


def _ends_with_code(text: str) -> bool:
    return any(_AFTER_CODE.fullmatch(text[m.end() :]) for m in _cued_codes(text))


def _grouped_runs(text: str) -> str:
    """Each comma-grouped run of four or more digits as its digits, split into a code and a PIN, or named as the
    PIN, by the rule above. A shorter run ("2,3") is left alone, since a thousands comma needs four digits."""
    out: list[str] = []
    last = 0
    for match in _GROUPED.finditer(text):
        digits = match.group().replace(",", "")
        if len(digits) < 4:
            continue
        before = "".join(out) + text[last : match.start()]
        if len(digits) == 8 and not _cued_codes(f"{before} {text[match.end() :]}"):
            said = f"{code_label(digits[:4])} PIN {digits[4:]}"
        elif len(digits) == 4 and _ends_with_code(before):
            said = f"PIN {digits}"
        else:
            said = digits
        out.append(text[last : match.start()] + said)
        last = match.end()
    return "".join(out) + text[last:]


def normalise_transcript(text: str) -> str:
    """The caller's words with each code written "ACME-dddd" and each PIN "PIN dddd". The PIN keeps its digits as
    heard, a dropped leading zero included, since pin_digits puts the zero back when the tool reads it."""
    text = _grouped_runs(text)
    text = _THOUSANDS.sub(r"\1\2", text)
    text = _PIN.sub(lambda m: f"PIN {_joined(m.group('digits'))}", text)
    text = _CODE.sub(_code, text)
    return _bare_code_beside_pin(text)
