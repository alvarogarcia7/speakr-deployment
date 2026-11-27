"""Transcript model, conversion from Speakr's JSON, and Markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Segment:
    text: str
    start: float | None = None
    end: float | None = None
    speaker: str | None = None        # display name (or SPEAKER_00 when not named)
    speaker_label: str | None = None  # raw diarization label, kept for renaming


@dataclass(frozen=True)
class Transcript:
    segments: tuple[Segment, ...] = field(default_factory=tuple)

    def speakers(self) -> set[str]:
        return {s.speaker for s in self.segments if s.speaker}

    def with_segments(self, segments) -> "Transcript":
        return Transcript(tuple(segments))


def from_speakr_json(data: dict[str, Any]) -> Transcript:
    """Build a Transcript from GET /api/v1/recordings/{id}/transcript?format=json."""
    segments = []
    for item in data.get("segments") or []:
        label = item.get("speaker_label")
        name = item.get("speaker") or label
        segments.append(
            Segment(
                text=(item.get("text") or "").strip(),
                start=_float_or_none(item.get("start_time")),
                end=_float_or_none(item.get("end_time")),
                speaker=name or None,
                speaker_label=label or None,
            )
        )
    return Transcript(tuple(segments))


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--:--"
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def render_markdown(transcript: Transcript, title: str, show_timestamps: bool = True) -> str:
    lines = [f"# {title}", ""]
    for seg in transcript.segments:
        prefix = f"[{fmt_time(seg.start)}] " if show_timestamps else ""
        speaker = f"**{seg.speaker}:** " if seg.speaker else ""
        lines.append(f"{prefix}{speaker}{seg.text}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
