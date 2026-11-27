"""Edits applied to a transcript before it is written to Markdown.

A transform is a function (transcript, options) -> transcript, registered with @transform.
Folder configs list them by name, in order:

    transforms:
      - drop_speakers_if_single
      - rename_speakers: {map: {SPEAKER_00: Alice}}

To add an edit, write a function here and register it. It must not change the input
transcript: return a new one (Transcript.with_segments).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .transcript import Segment, Transcript

TransformFn = Callable[[Transcript, dict[str, Any]], Transcript]
REGISTRY: dict[str, TransformFn] = {}
OPTION_NAMES: dict[str, set[str]] = {}

TransformSpec = tuple[str, dict[str, Any]]


def transform(name: str, options: set[str] = frozenset()):
    """Register a transform. `options` lists the keys it accepts; others are a config error."""

    def decorator(fn: TransformFn) -> TransformFn:
        REGISTRY[name] = fn
        OPTION_NAMES[name] = set(options)
        return fn

    return decorator


def parse_spec(item: Any) -> TransformSpec:
    """Accept "name" or {"name": {options}} or {"name": name, ...options}."""
    if isinstance(item, str):
        name, options = item, {}
    elif isinstance(item, dict) and len(item) == 1:
        (name, options), = item.items()
        options = options or {}
    elif isinstance(item, dict) and "name" in item:
        options = {k: v for k, v in item.items() if k != "name"}
        name = item["name"]
    else:
        raise ValueError(f"bad transform entry: {item!r}")
    if name not in REGISTRY:
        raise ValueError(f"unknown transform {name!r} (known: {', '.join(sorted(REGISTRY))})")
    if not isinstance(options, dict):
        raise ValueError(f"options of transform {name!r} must be a mapping")
    unknown = set(options) - OPTION_NAMES[name]
    if unknown:
        raise ValueError(f"transform {name!r} does not take {', '.join(sorted(unknown))}")
    return name, dict(options)


def apply(transcript: Transcript, specs: list[TransformSpec]) -> Transcript:
    for name, options in specs:
        transcript = REGISTRY[name](transcript, options)
    return transcript


@transform("drop_speakers_if_single")
def drop_speakers_if_single(t: Transcript, _: dict) -> Transcript:
    """If the recording has one speaker, remove the speaker name from every line."""
    if len(t.speakers()) > 1:
        return t
    return t.with_segments(replace(s, speaker=None) for s in t.segments)


@transform("rename_speakers", {"map"})
def rename_speakers(t: Transcript, options: dict) -> Transcript:
    """Rename speakers. Keys can be the raw label (SPEAKER_00) or the current name."""
    mapping = options.get("map") or {}
    if not isinstance(mapping, dict):
        raise ValueError("rename_speakers.map must be a mapping")

    def rename(seg: Segment) -> Segment:
        for key in (seg.speaker_label, seg.speaker):
            if key and key in mapping:
                return replace(seg, speaker=str(mapping[key]))
        return seg

    return t.with_segments(rename(s) for s in t.segments)


@transform("merge_consecutive")
def merge_consecutive(t: Transcript, _: dict) -> Transcript:
    """Join neighbouring segments that have the same speaker into one paragraph."""
    merged: list[Segment] = []
    for seg in t.segments:
        if merged and merged[-1].speaker == seg.speaker and merged[-1].speaker_label == seg.speaker_label:
            prev = merged[-1]
            merged[-1] = replace(prev, text=f"{prev.text} {seg.text}".strip(), end=seg.end)
        else:
            merged.append(seg)
    return t.with_segments(merged)


@transform("drop_empty")
def drop_empty(t: Transcript, _: dict) -> Transcript:
    return t.with_segments(s for s in t.segments if s.text.strip())


@transform("replace", {"rules"})
def replace_text(t: Transcript, options: dict) -> Transcript:
    """Find and replace in the text. rules: [{pattern, replacement, regex: false}]."""
    rules = []
    for rule in options.get("rules") or []:
        if not isinstance(rule, dict) or "pattern" not in rule:
            raise ValueError("replace rules need a 'pattern' (and 'replacement')")
        pattern = str(rule["pattern"])
        if not rule.get("regex", False):
            pattern = re.escape(pattern)
        rules.append((re.compile(pattern), str(rule.get("replacement", ""))))

    def apply_rules(seg: Segment) -> Segment:
        text = seg.text
        for regex, repl in rules:
            text = regex.sub(repl, text)
        return replace(seg, text=text)

    return t.with_segments(apply_rules(s) for s in t.segments)
