"""The FAQ the line answers from, parsed into sections by id.

Why parsed and not pasted whole into the prompt: answer_question hands the model only the sections it named, so
every process answer carries the ids it came from (cite or refuse, spec.md section 6), and the persona carries
only the index of ids and titles.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq.md"

_HEADING = re.compile(r"^##\s+(F\d+)\.?\s+(.+?)\s*$")
_SECTION = re.compile(r"^###\s+(F\d+\.\d+)\.?\s+(.+?)\s*$")
_ID = re.compile(r"F?(\d+)(?:[.\-_](\d+))?")
# A model may cite one whole heading, which is up to five sections; more than this in one call is a model asking
# for the whole FAQ, which the index exists to avoid.
MAX_SECTIONS = 8


@dataclass(frozen=True)
class FaqSection:
    id: str
    title: str
    text: str
    heading_id: str
    heading: str


@dataclass(frozen=True)
class FaqHeading:
    id: str
    title: str
    sections: tuple[FaqSection, ...]


def parse_faq(markdown: str) -> tuple[FaqHeading, ...]:
    """Headings "## F1. Title" hold sections "### F1.1 Title"; a section's text runs to the next heading. The
    lines before the first heading are the file's own preface, not an answer."""
    headings: list[tuple[str, str, list[FaqSection]]] = []
    current: tuple[str, str, list[str]] | None = None

    def close() -> None:
        if current is not None and headings:
            sid, title, lines = current
            hid, htitle, sections = headings[-1]
            sections.append(FaqSection(sid, title, " ".join(lines), hid, htitle))

    for raw in markdown.splitlines():
        line = raw.strip()
        if m := _HEADING.match(line):
            close()
            current = None
            headings.append((m.group(1), m.group(2), []))
        elif m := _SECTION.match(line):
            close()
            current = (m.group(1), m.group(2), [])
        elif current is not None and line and not line.startswith("<!--"):
            current[2].append(line)
    close()
    return tuple(FaqHeading(hid, title, tuple(sections)) for hid, title, sections in headings)


@lru_cache(maxsize=4)
def load_faq(path: str | None = None) -> tuple[FaqHeading, ...]:
    return parse_faq(Path(path or FAQ_PATH).read_text(encoding="utf-8"))


def sections(path: str | None = None) -> dict[str, FaqSection]:
    return {s.id: s for h in load_faq(path) for s in h.sections}


def normalise_id(raw: object) -> str | None:
    """Reads "f2.1", "F 2.1", "2.1" and "F2-1" as F2.1, and "F3" or "F3." as the heading F3."""
    text = re.sub(r"\s+", "", str(raw)).upper().rstrip(".")
    m = _ID.fullmatch(text)
    if m is None:
        return None
    return f"F{int(m.group(1))}" + (f".{int(m.group(2))}" if m.group(2) else "")


def lookup(ids: Iterable[object], path: str | None = None) -> tuple[FaqSection, ...]:
    """The sections named, in the order asked: an exact id gives its section, a heading id gives every section
    under it. Unknown ids are skipped, so an empty result means the FAQ does not cover the question."""
    by_id = sections(path)
    by_heading = {h.id: h.sections for h in load_faq(path)}
    found: dict[str, FaqSection] = {}
    for raw in ids:
        sid = normalise_id(raw)
        if sid is None:
            continue
        for section in by_heading.get(sid, ()) or ((by_id[sid],) if sid in by_id else ()):
            found.setdefault(section.id, section)
    return tuple(found.values())[:MAX_SECTIONS]


def faq_index(path: str | None = None) -> str:
    """One line per heading, its sections' ids and titles after it, for the persona to carry instead of the
    FAQ's text: "F2 The first-round interview: F2.1 How long is it, and in what format?; F2.2 ..."."""
    return "\n".join(
        f"{h.id} {h.title}: " + "; ".join(f"{s.id} {s.title}" for s in h.sections) for h in load_faq(path)
    )
