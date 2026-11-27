"""Configuration: the global config file and one config file per watched folder."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .transforms import TransformSpec, parse_spec

FOLDER_CONFIG_NAME = ".speakr-sync.yaml"
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("SPEAKR_SYNC_CONFIG", "~/.config/speakr-sync/config.yaml")
).expanduser()
DEFAULT_STATE_FILE = "~/.local/state/speakr-sync/state.sqlite3"
DEFAULT_EXTENSIONS = (
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac",
    ".webm", ".mp4", ".mov", ".mkv",
)

GLOBAL_KEYS = {"server", "state_file", "refresh_seconds", "settle_seconds", "wait_minutes", "folders"}
SERVER_KEYS = {"url", "username", "ca_bundle", "verify_tls", "api_token_env"}
FOLDER_KEYS = {
    "language", "transcription_model", "hotwords", "initial_prompt", "min_speakers",
    "max_speakers", "attributes", "extensions", "output_dir", "transforms", "show_timestamps",
    "apple_transcript",
}
# Fields of the Speakr upload form that the folder config may set (see POST /api/v1/recordings/upload)
ATTRIBUTE_KEYS = {"title", "participants", "notes", "folder_id", "tag_ids", "meeting_date"}


class ConfigError(Exception):
    """A config file is missing, malformed or refers to something that does not exist."""


@dataclass
class ServerConfig:
    url: str
    username: str = "admin"
    ca_bundle: str | None = None
    verify_tls: bool = True
    api_token_env: str = "SPEAKR_API_TOKEN"


@dataclass
class FolderConfig:
    path: Path
    language: str = ""  # ISO 639-1; empty = let Speakr detect it
    transcription_model: str | None = None
    hotwords: str = ""
    initial_prompt: str = ""
    min_speakers: int | None = None
    max_speakers: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    output_dir: Path = Path("transcripts")
    transforms: list[TransformSpec] = field(default_factory=list)
    show_timestamps: bool = True
    apple_transcript: bool = False  # add the Apple Voice Memos transcript to the job report
    config_file: Path | None = None

    @property
    def output_path(self) -> Path:
        return self.path / self.output_dir


@dataclass
class AppConfig:
    path: Path
    server: ServerConfig
    state_file: Path
    refresh_seconds: int
    settle_seconds: int
    wait_minutes: int
    folder_paths: list[Path]


def _check_keys(data: Any, allowed: set[str], where: str) -> dict:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must be a mapping")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})")
    return data


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a mapping at the top level")
    return data


def _positive_int(value: Any, where: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where} must be a whole number >= 0")
    return value


def load_app_config(path: Path) -> AppConfig:
    path = Path(path).expanduser()
    raw = _read_yaml(path)
    _check_keys(raw, GLOBAL_KEYS, str(path))

    server_raw = _check_keys(raw.get("server"), SERVER_KEYS, "server")
    url = str(server_raw.get("url") or "").rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ConfigError("server.url must start with https:// (for example https://speakr.example.lan:8446)")
    ca_bundle = server_raw.get("ca_bundle")
    if ca_bundle:
        ca_bundle = str((path.parent / Path(ca_bundle).expanduser()).resolve())
        if not Path(ca_bundle).is_file():
            raise ConfigError(f"server.ca_bundle not found: {ca_bundle}")
    server = ServerConfig(
        url=url,
        username=str(server_raw.get("username") or "admin"),
        ca_bundle=ca_bundle,
        verify_tls=bool(server_raw.get("verify_tls", True)),
        api_token_env=str(server_raw.get("api_token_env") or "SPEAKR_API_TOKEN"),
    )

    state_file = Path(str(raw.get("state_file") or DEFAULT_STATE_FILE)).expanduser()
    if not state_file.is_absolute():
        state_file = (path.parent / state_file).resolve()

    folders = raw.get("folders") or []
    if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
        raise ConfigError("folders must be a list of folder paths")
    folder_paths = [(path.parent / Path(f).expanduser()).resolve() for f in folders]

    return AppConfig(
        path=path,
        server=server,
        state_file=state_file,
        refresh_seconds=_positive_int(raw.get("refresh_seconds"), "refresh_seconds", 60),
        settle_seconds=_positive_int(raw.get("settle_seconds"), "settle_seconds", 30),
        wait_minutes=_positive_int(raw.get("wait_minutes"), "wait_minutes", 240),
        folder_paths=folder_paths,
    )


def load_folder_config(folder: Path) -> FolderConfig:
    """Read <folder>/.speakr-sync.yaml. A folder without one is an error: its settings must be explicit."""
    cfg_path = folder / FOLDER_CONFIG_NAME
    if not folder.is_dir():
        raise ConfigError(f"watched folder does not exist: {folder}")
    if not cfg_path.is_file():
        raise ConfigError(f"{folder} has no {FOLDER_CONFIG_NAME} (create one with: speakr-sync init-folder {folder})")
    raw = _read_yaml(cfg_path)
    _check_keys(raw, FOLDER_KEYS, str(cfg_path))

    attributes = _check_keys(raw.get("attributes"), ATTRIBUTE_KEYS, f"{cfg_path}: attributes")
    if "tag_ids" in attributes and not isinstance(attributes["tag_ids"], list):
        raise ConfigError(f"{cfg_path}: attributes.tag_ids must be a list")

    extensions = raw.get("extensions")
    if extensions is None:
        exts = DEFAULT_EXTENSIONS
    else:
        if not isinstance(extensions, list) or not extensions:
            raise ConfigError(f"{cfg_path}: extensions must be a non-empty list")
        exts = tuple(str(e).lower() if str(e).startswith(".") else "." + str(e).lower() for e in extensions)

    transforms_raw = raw.get("transforms") or []
    if not isinstance(transforms_raw, list):
        raise ConfigError(f"{cfg_path}: transforms must be a list")
    try:
        transforms = [parse_spec(item) for item in transforms_raw]
    except ValueError as exc:
        raise ConfigError(f"{cfg_path}: {exc}") from exc

    min_s = raw.get("min_speakers")
    max_s = raw.get("max_speakers")
    for key, value in (("min_speakers", min_s), ("max_speakers", max_s)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ConfigError(f"{cfg_path}: {key} must be a whole number >= 1")

    return FolderConfig(
        path=folder,
        language=str(raw.get("language") or "").strip(),
        transcription_model=raw.get("transcription_model") or None,
        hotwords=str(raw.get("hotwords") or ""),
        initial_prompt=str(raw.get("initial_prompt") or ""),
        min_speakers=min_s,
        max_speakers=max_s,
        attributes=dict(attributes),
        extensions=exts,
        output_dir=Path(os.path.expanduser(str(raw.get("output_dir") or "transcripts"))),  # ~ and absolute paths allowed
        transforms=transforms,
        show_timestamps=bool(raw.get("show_timestamps", True)),
        apple_transcript=bool(raw.get("apple_transcript", False)),
        config_file=cfg_path,
    )


EXAMPLE_APP_CONFIG = """\
# speakr-sync: global settings. Relative paths are relative to this file.
server:
  url: https://speakr.example.lan:8446   # PUBLIC_URL from the Speakr .env
  username: admin                        # Authelia login (make password on the server)
  # The password is never stored here: set SPEAKR_PASSWORD, or it is asked for.
  api_token_env: SPEAKR_API_TOKEN        # name of the env var holding the Speakr API token
  # ca_bundle: ./ca.crt                  # caddy/certs/ca.crt copied from the server (local CA), if it is not trusted
  verify_tls: true

state_file: ~/.local/state/speakr-sync/state.sqlite3   # which files were already sent
refresh_seconds: 60     # `watch`: how often to look for new files and check running jobs
settle_seconds: 30      # skip files modified in the last N seconds (still being copied)
wait_minutes: 240       # `run`: how long to wait for jobs before exiting

# Each folder needs a .speakr-sync.yaml inside it (speakr-sync init-folder <folder>)
folders:
  - ~/Recordings/Meetings
  - ~/Recordings/Interviews
"""

EXAMPLE_FOLDER_CONFIG = """\
# speakr-sync: settings for this folder. Every audio/video file here is uploaded once.
language: en              # ISO 639-1; empty = auto-detect
transcription_model:      # empty = the server default; must be allowed by the server
hotwords: ""              # names or terms the transcriber should expect
initial_prompt: ""        # free text hint about the content
min_speakers:             # diarization limits (the server needs speaker detection enabled)
max_speakers:

# Sent as the upload form fields (Speakr API: POST /api/v1/recordings/upload)
attributes:
  participants: ""        # "Alice, Bob"
  notes: ""
  # title: ""             # without it Speakr titles the recording itself
  # folder_id: 3          # a Speakr folder id
  # tag_ids: [1, 2]
  # meeting_date: "2026-11-27T10:00:00"

extensions:               # which files to pick up (default: common audio and video)
  - .mp3
  - .m4a
  - .wav

output_dir: transcripts   # relative to this folder; holds the .job.md, .transcript.md and raw/ files
show_timestamps: true

# Changes made to the transcript before it is written (the raw JSON is kept, so
# `speakr-sync rerender` can apply new rules later). Applied in order.
transforms:
  - drop_speakers_if_single   # one speaker in the recording: no speaker names in the transcript
  # - merge_consecutive       # join consecutive segments of the same speaker
  # - rename_speakers: {map: {SPEAKER_00: Alice, SPEAKER_01: Bob}}
  # - replace: {rules: [{pattern: "\\\\bcolour\\\\b", replacement: color, regex: true}]}
  # - drop_empty              # remove segments with no text
"""
