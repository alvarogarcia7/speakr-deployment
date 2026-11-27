"""Reads the transcript that Apple Voice Memos stores inside each .m4a file.

Voice Memos writes a 'tsrp' atom into the recording: JSON with the attributed string of the
transcript. In it, `runs` is a flat list of alternating [text, attribute index, text, index, ...]
(one entry per word), and `attributeTable[index].timeRange` is [start, end] in seconds.
The format is undocumented: it was read from sample files, not from Apple's documentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .transcript import fmt_time

PAUSE_SECONDS = 1.5  # a pause this long starts a new paragraph
MARKER = b"tsrp{"


@dataclass(frozen=True)
class Paragraph:
    start: float | None
    text: str


def _parse_json(data: bytes) -> dict | None:
    idx = data.find(MARKER)
    if idx < 0:
        return None
    text = data[idx + 4:].decode("utf-8", errors="replace")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)  # the JSON is followed by other atom data
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _words(attributed: dict) -> list[tuple[str, float | None, float | None]]:
    """(text, start, end) per run. Runs without a time range have None times."""
    runs = attributed.get("runs") or []
    table = attributed.get("attributeTable") or []
    words = []
    for pos in range(0, len(runs) - 1, 2):
        text, index = runs[pos], runs[pos + 1]
        if not isinstance(text, str) or not isinstance(index, int):
            continue
        start = end = None
        if 0 <= index < len(table) and isinstance(table[index], dict):
            time_range = table[index].get("timeRange")
            if isinstance(time_range, list) and len(time_range) == 2:
                start, end = float(time_range[0]), float(time_range[1])
        words.append((text, start, end))
    return words


def read_transcript(path: Path) -> list[Paragraph] | None:
    """Paragraphs of the Voice Memos transcript, or None if the file has none."""
    obj = _parse_json(path.read_bytes())
    if not obj or not isinstance(obj.get("attributedString"), dict):
        return None
    words = _words(obj["attributedString"])
    if not words:
        return None

    paragraphs: list[Paragraph] = []
    current: list[str] = []
    current_start: float | None = None
    last_end: float | None = None
    last_text = ""
    for text, start, end in words:
        gap = (start - last_end) if (start is not None and last_end is not None) else None
        new_paragraph = bool(current) and (
            (gap is not None and gap > PAUSE_SECONDS)
            or (gap is None and last_text.rstrip().endswith((".", "?", "!")))
        )
        if new_paragraph:
            paragraphs.append(Paragraph(current_start, "".join(current).strip()))
            current, current_start = [], None
        if not current:
            current_start = start
        current.append(text)
        last_text = text
        if end is not None:
            last_end = end
    if current:
        paragraphs.append(Paragraph(current_start, "".join(current).strip()))
    return [p for p in paragraphs if p.text]


def render_section(paragraphs: list[Paragraph] | None) -> str:
    """Markdown section for the job report."""
    lines = ["", "## Apple Voice Memos transcript", ""]
    if paragraphs is None:
        lines.append("_No Voice Memos transcript in this file._")
        return "\n".join(lines) + "\n"
    for p in paragraphs:
        prefix = f"**[{fmt_time(p.start)}]** " if p.start is not None else ""
        lines += [f"{prefix}{p.text}", ""]
    return "\n".join(lines).rstrip() + "\n"
