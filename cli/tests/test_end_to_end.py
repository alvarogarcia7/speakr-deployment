from pathlib import Path

from conftest import PASSWORD, TOKEN, FakeServer
from speakr_sync.cli import main
from speakr_sync.state import State


def make_setup(tmp_path, url, transforms="  - drop_speakers_if_single\n"):
    folder = tmp_path / "Meetings"
    folder.mkdir()
    (folder / ".speakr-sync.yaml").write_text(
        "language: en\nattributes:\n  participants: Alice\n"
        "transforms:\n" + transforms, encoding="utf-8")
    (folder / "meeting one.mp3").write_bytes(b"ID3 fake audio " * 100)
    config = tmp_path / "config.yaml"
    config.write_text(
        f"server:\n  url: {url}\n  username: admin\n"
        f"state_file: {tmp_path / 'state.sqlite3'}\nsettle_seconds: 0\nwait_minutes: 1\n"
        f"refresh_seconds: 1\nfolders:\n  - {folder}\n", encoding="utf-8")
    return folder, config


def test_run_uploads_once_and_writes_markdown(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)

    assert main(["--config", str(config), "run"]) == 0
    assert FakeServer.uploads == [("meeting one.mp3", FakeServer.uploads[0][1])]
    assert len(FakeServer.uploads[0][1]) == 64  # idempotency key = SHA-256 of the file

    job = (folder / "transcripts" / "meeting one.job.md").read_text(encoding="utf-8")
    assert f"[Recording 7]({fake_server}/recordings/7)" in job
    assert "[meeting one.mp3](file://" in job and "meeting%20one.mp3)" in job
    assert "[meeting one.transcript.md](./meeting%20one.transcript.md)" in job
    assert "**Speakers detected:** 1" in job

    text = (folder / "transcripts" / "meeting one.transcript.md").read_text(encoding="utf-8")
    assert "# Team sync" in text
    assert "[00:00:00] Hello team" in text          # single speaker: name removed by the transform
    assert "Alice" not in text
    assert (folder / "transcripts" / "raw" / "meeting one.json").is_file()

    # second run: nothing new is sent
    assert main(["--config", str(config), "run"]) == 0
    assert len(FakeServer.uploads) == 1


def test_renamed_copy_is_not_sent_again(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "run"]) == 0
    (folder / "copy of meeting.mp3").write_bytes((folder / "meeting one.mp3").read_bytes())
    assert main(["--config", str(config), "run"]) == 0
    assert len(FakeServer.uploads) == 1


def test_wrong_password_fails_cleanly(tmp_path, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("SPEAKR_PASSWORD", "wrong")
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    _, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "check"]) == 1
    err = capsys.readouterr().err
    assert "Authelia login for user 'admin'" in err
    assert "password from the SPEAKR_PASSWORD environment variable" in err


def test_wrong_api_token_is_reported_as_token_problem(tmp_path, fake_server, monkeypatch, capsys):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", "not-the-token")
    _, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "check"]) == 1
    err = capsys.readouterr().err
    assert "Authelia login worked" in err and "API token from SPEAKR_API_TOKEN was rejected" in err


def test_session_expiry_triggers_relogin(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)
    FakeServer.api_expired = True  # first API call gets 401; the client logs in again and retries
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    assert len(FakeServer.uploads) == 1


def test_failed_job_is_recorded_and_not_resent(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    FakeServer.job_status = "FAILED"
    folder, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "run"]) == 0
    state = State(tmp_path / "state.sqlite3")
    rows = state.all()
    state.close()
    assert [r["status"] for r in rows] == ["failed"]
    assert main(["--config", str(config), "run"]) == 0
    assert len(FakeServer.uploads) == 1


def test_rerender_applies_new_transforms_offline(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server, transforms="  - merge_consecutive\n")
    assert main(["--config", str(config), "run"]) == 0
    text = (folder / "transcripts" / "meeting one.transcript.md").read_text(encoding="utf-8")
    assert "Alice:** Hello team Let us start" in text

    # change the folder config to drop the speaker, then rerender with no server call
    (folder / ".speakr-sync.yaml").write_text(
        "transforms:\n  - merge_consecutive\n  - drop_speakers_if_single\n", encoding="utf-8")
    FakeServer.job_status = "FAILED"  # proves rerender does not need the server
    assert main(["--config", str(config), "rerender"]) == 0
    text = (folder / "transcripts" / "meeting one.transcript.md").read_text(encoding="utf-8")
    assert "Hello team Let us start" in text and "Alice" not in text


def test_edit_on_server_updates_the_transcript(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    md = folder / "transcripts" / "meeting one.transcript.md"
    assert "Hello team" in md.read_text(encoding="utf-8")

    # the user edits the transcript in Speakr; the next watcher pass sees it in the change feed
    FakeServer.transcript_text = ["Hello team, edited"]
    FakeServer.version += 1
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    text = md.read_text(encoding="utf-8")
    assert "Hello team, edited" in text and "Let us start" not in text
    assert len(FakeServer.uploads) == 1  # an edit never causes a new upload

    # a pass with no further edits rewrites nothing
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    state = State(tmp_path / "state.sqlite3")
    rec = state.all()[0]
    state.close()
    assert rec["status"] == "done" and rec["remote_updated_at"].endswith("2.000000Z")


def test_deletion_on_server_is_recorded_and_file_not_resent(tmp_path, fake_server, monkeypatch):
    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    FakeServer.removed = True
    assert main(["--config", str(config), "run", "--no-wait"]) == 0
    state = State(tmp_path / "state.sqlite3")
    rec = state.all()[0]
    state.close()
    assert rec["status"] == "removed"
    assert (folder / "meeting one.mp3").is_file()  # the local file is kept
    assert len(FakeServer.uploads) == 1           # and not sent again


def test_apple_transcript_goes_into_the_transcript_file(tmp_path, fake_server, monkeypatch):
    import json as _json

    monkeypatch.setenv("SPEAKR_PASSWORD", PASSWORD)
    monkeypatch.setenv("SPEAKR_API_TOKEN", TOKEN)
    folder, config = make_setup(tmp_path, fake_server)
    (folder / ".speakr-sync.yaml").write_text("apple_transcript: true\n", encoding="utf-8")
    apple = {"attributedString": {"runs": [" Apple", 0, " words.", 1],
                                  "attributeTable": [{"timeRange": [0, 0.5]}, {"timeRange": [0.5, 1.0]}]}}
    (folder / "meeting one.mp3").write_bytes(b"\x00" * 50 + b"tsrp" + _json.dumps(apple).encode())
    assert main(["--config", str(config), "run"]) == 0
    out = folder / "transcripts"
    transcript = (out / "meeting one.transcript.md").read_text(encoding="utf-8")
    assert transcript.index("## Speakr transcript") < transcript.index("## Apple Voice Memos transcript")
    assert "Hello team" in transcript and "Apple words." in transcript
    job = (out / "meeting one.job.md").read_text(encoding="utf-8")
    assert "Apple Voice Memos" not in job
