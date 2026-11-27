import json

from speakr_sync.voice_memos import read_transcript, render_section


def make_m4a(tmp_path, attributed, name="memo.m4a"):
    """Bytes shaped like a Voice Memos file: audio-looking junk, then the tsrp atom."""
    payload = json.dumps({"locale": {"current": 1, "identifier": "en_AE"},
                          "attributedString": attributed}).encode()
    path = tmp_path / name
    path.write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"\x11" * 64 + b"Core Media Audio\ntsrp" + payload + b"\x00\xff")
    return path


def test_words_are_grouped_into_paragraphs_by_pause(tmp_path):
    attributed = {
        "runs": [",", 0, " how", 1, " that", 2, " impacts", 3, " is", 4, " sounds.", 5, " So", 6, " then", 7],
        "attributeTable": [
            {"timeRange": [0, 0.2]}, {"timeRange": [0.2, 0.5]}, {"timeRange": [0.5, 0.9]},
            {"timeRange": [0.9, 1.4]}, {"timeRange": [1.4, 1.6]}, {"timeRange": [1.6, 2.0]},
            {"timeRange": [5.0, 5.2]}, {"timeRange": [5.2, 5.6]},  # 3 s pause before "So"
        ],
    }
    paragraphs = read_transcript(make_m4a(tmp_path, attributed))
    assert [(round(p.start, 1), p.text) for p in paragraphs] == [
        (0.0, ", how that impacts is sounds."),
        (5.0, "So then"),
    ]


def test_no_timing_breaks_on_sentence_end(tmp_path):
    attributed = {"runs": [" Hello", 0, ".", 1, " Yes", 2, " ok", 3], "attributeTable": []}
    paragraphs = read_transcript(make_m4a(tmp_path, attributed))
    assert [p.text for p in paragraphs] == ["Hello.", "Yes ok"]
    assert all(p.start is None for p in paragraphs)


def test_file_without_transcript_gives_none(tmp_path):
    path = tmp_path / "plain.m4a"
    path.write_bytes(b"\x00" * 100)
    assert read_transcript(path) is None
    assert "_No Voice Memos transcript" in render_section(None)


def test_render_section_formats_timestamps(tmp_path):
    attributed = {"runs": [" Hi", 0], "attributeTable": [{"timeRange": [3725.0, 3726.0]}]}
    text = render_section(read_transcript(make_m4a(tmp_path, attributed)))
    assert text.startswith("\n## Apple Voice Memos transcript")
    assert "**[01:02:05]** Hi" in text
