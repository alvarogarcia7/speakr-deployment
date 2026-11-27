import pytest

from speakr_sync.transcript import Segment, Transcript, render_markdown
from speakr_sync.transforms import apply, parse_spec


def seg(text, speaker=None, label=None, start=0.0, end=1.0):
    return Segment(text=text, start=start, end=end, speaker=speaker, speaker_label=label)


def test_single_speaker_loses_names():
    t = Transcript((seg("hi", "Alice", "SPEAKER_00"), seg("there", "Alice", "SPEAKER_00")))
    out = apply(t, [parse_spec("drop_speakers_if_single")])
    assert all(s.speaker is None for s in out.segments)
    assert [s.text for s in out.segments] == ["hi", "there"]


def test_two_speakers_keep_names():
    t = Transcript((seg("hi", "Alice", "SPEAKER_00"), seg("yo", "Bob", "SPEAKER_01")))
    out = apply(t, [parse_spec("drop_speakers_if_single")])
    assert [s.speaker for s in out.segments] == ["Alice", "Bob"]


def test_rename_by_label_and_merge():
    t = Transcript((seg("a", "SPEAKER_00", "SPEAKER_00", 0, 1), seg("b", "SPEAKER_00", "SPEAKER_00", 1, 2),
                    seg("c", "SPEAKER_01", "SPEAKER_01", 2, 3)))
    spec = parse_spec({"rename_speakers": {"map": {"SPEAKER_00": "Alice"}}})
    out = apply(t, [spec, parse_spec("merge_consecutive")])
    assert [(s.speaker, s.text, s.start, s.end) for s in out.segments] == [
        ("Alice", "a b", 0, 2), ("SPEAKER_01", "c", 2, 3)]


def test_replace_literal_and_regex():
    t = Transcript((seg("colour and colours"),))
    spec = parse_spec({"replace": {"rules": [
        {"pattern": "colour", "replacement": "color", "regex": True},
        {"pattern": "a.d", "replacement": "X"},  # literal, not regex
    ]}})
    assert apply(t, [spec]).segments[0].text == "color and colors"


def test_unknown_transform_and_option_are_errors():
    with pytest.raises(ValueError, match="unknown transform"):
        parse_spec("nope")
    with pytest.raises(ValueError, match="does not take"):
        parse_spec({"drop_empty": {"bogus": 1}})


def test_input_is_not_mutated():
    t = Transcript((seg("x", "Alice"),))
    apply(t, [parse_spec("drop_speakers_if_single")])
    assert t.segments[0].speaker == "Alice"


def test_render_markdown_with_and_without_timestamps():
    t = Transcript((seg("hello", "Alice", start=3725.0),))
    assert "[01:02:05] **Alice:** hello" in render_markdown(t, "T", True)
    assert "**Alice:** hello" in render_markdown(t, "T", False)
    assert "[01:02:05]" not in render_markdown(t, "T", False)
