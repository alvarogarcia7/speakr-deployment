import pytest

from speakr_sync.api import upload_fields
from speakr_sync.config import (
    EXAMPLE_FOLDER_CONFIG,
    ConfigError,
    load_app_config,
    load_folder_config,
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_app_config_defaults_and_relative_paths(tmp_path):
    cfg = write(tmp_path / "config.yaml", "server:\n  url: https://speakr.example.lan:8446\nfolders:\n  - ./rec\n")
    app = load_app_config(cfg)
    assert app.server.url == "https://speakr.example.lan:8446"
    assert app.refresh_seconds == 60
    assert app.folder_paths == [(tmp_path / "rec").resolve()]
    assert app.state_file.name == "state.sqlite3"


def test_app_config_rejects_unknown_keys_and_bad_url(tmp_path):
    with pytest.raises(ConfigError, match="unknown key"):
        load_app_config(write(tmp_path / "a.yaml", "server:\n  url: https://x.y\nrefresh: 5\n"))
    with pytest.raises(ConfigError, match="must start with"):
        load_app_config(write(tmp_path / "b.yaml", "server:\n  url: speakr.example.lan\n"))


def test_folder_config_is_required(tmp_path):
    with pytest.raises(ConfigError, match="init-folder"):
        load_folder_config(tmp_path)


def test_example_folder_config_loads(tmp_path):
    write(tmp_path / ".speakr-sync.yaml", EXAMPLE_FOLDER_CONFIG)
    folder = load_folder_config(tmp_path)
    assert folder.language == "en"
    assert [n for n, _ in folder.transforms] == ["drop_speakers_if_single"]
    assert folder.output_path == tmp_path / "transcripts"


def test_folder_config_validation(tmp_path):
    write(tmp_path / ".speakr-sync.yaml", "langage: en\n")
    with pytest.raises(ConfigError, match="unknown key"):
        load_folder_config(tmp_path)
    write(tmp_path / ".speakr-sync.yaml", "transforms: [not_a_transform]\n")
    with pytest.raises(ConfigError, match="unknown transform"):
        load_folder_config(tmp_path)
    write(tmp_path / ".speakr-sync.yaml", "extensions: [mp3, WAV]\nattributes:\n  title: x\n")
    folder = load_folder_config(tmp_path)
    assert folder.extensions == (".mp3", ".wav")


def test_upload_fields_from_folder(tmp_path):
    write(tmp_path / ".speakr-sync.yaml",
          "language: fr\nattributes:\n  participants: [Alice, Bob]\n  tag_ids: [4, 5]\n  folder_id: 3\n")
    fields = upload_fields(load_folder_config(tmp_path))
    assert fields == {"language": "fr", "participants": "Alice, Bob",
                      "tag_ids[0]": "4", "tag_ids[1]": "5", "folder_id": "3"}


def test_upload_fields_reject_unknown_attribute(tmp_path):
    from speakr_sync.api import SpeakrError

    with pytest.raises(SpeakrError):
        upload_fields({"nonsense": 1})


def test_output_dir_accepts_home_and_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    write(tmp_path / "rec" / ".speakr-sync.yaml", "output_dir: ~/Documents/out\n")
    assert load_folder_config(tmp_path / "rec").output_path == tmp_path / "home" / "Documents" / "out"
    write(tmp_path / "rec" / ".speakr-sync.yaml", f"output_dir: {tmp_path / 'abs'}\n")
    assert load_folder_config(tmp_path / "rec").output_path == tmp_path / "abs"
