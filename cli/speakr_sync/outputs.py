"""Writes the per-file outputs: the job report (.job.md), the transcript (.transcript.md), raw JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import transforms
from .config import FolderConfig
from . import voice_memos
from .transcript import fmt_time, from_speakr_json, render_markdown


def _escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _relative_link(name: str) -> str:
    return "./" + quote(name)


def plan_paths(folder: FolderConfig, rec: dict[str, Any]) -> dict[str, Path]:
    """Output paths for a file. Reuses the paths of an earlier run (rerender), else picks new names."""
    if rec.get("job_md") and rec.get("transcript_md") and rec.get("raw_json"):
        return {"job_md": Path(rec["job_md"]), "transcript_md": Path(rec["transcript_md"]), "raw_json": Path(rec["raw_json"])}
    out = folder.output_path
    stem = Path(rec["local_path"]).stem
    candidates = [out / f"{stem}.job.md", out / f"{stem}.transcript.md", out / "raw" / f"{stem}.json"]
    if any(p.exists() for p in candidates):
        stem = f"{stem}-{rec['sha256'][:8]}"
    return {
        "job_md": out / f"{stem}.job.md",
        "transcript_md": out / f"{stem}.transcript.md",
        "raw_json": out / "raw" / f"{stem}.json",
    }


def write_outputs(
    folder: FolderConfig,
    rec: dict[str, Any],
    info: dict[str, Any],
    raw: dict[str, Any],
    server_url: str,
) -> dict[str, str]:
    paths = plan_paths(folder, rec)
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)

    paths["raw_json"].write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    original = from_speakr_json(raw)
    edited = transforms.apply(original, folder.transforms)
    title = info.get("title") or Path(rec["local_path"]).stem
    paths["transcript_md"].write_text(
        render_markdown(edited, title, folder.show_timestamps), encoding="utf-8"
    )

    job_text = render_job(
        title=title,
        rec=rec,
        info=info,
        job_url=f"{server_url}/recordings/{rec['recording_id']}",
        transcript_name=paths["transcript_md"].name,
        raw_name=paths["raw_json"].relative_to(folder.output_path).as_posix(),
        speakers=len(original.speakers()),
        folder=folder,
    )
    if folder.apple_transcript:
        job_text += voice_memos.render_section(voice_memos.read_transcript(Path(rec["local_path"])))
    paths["job_md"].write_text(job_text, encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


def render_job(
    *,
    title: str,
    rec: dict[str, Any],
    info: dict[str, Any],
    job_url: str,
    transcript_name: str,
    raw_name: str,
    speakers: int,
    folder: FolderConfig,
) -> str:
    local = Path(rec["local_path"])
    duration = info.get("audio_duration")
    rows = [
        ("Job", f"[Recording {rec['recording_id']}]({job_url})"),
        ("Local file", f"[{_escape_link_text(local.name)}]({local.as_uri()})"),
        ("Processed", rec.get("completed_at") or "-"),
        ("Uploaded", rec.get("uploaded_at") or "-"),
        ("Status", info.get("status") or "COMPLETED"),
        ("Recording date", info.get("meeting_date") or info.get("created_at") or "-"),
        ("Audio duration", fmt_time(float(duration)) if duration else "-"),
        ("Language requested", folder.language or "auto"),
        ("Speakers detected", str(speakers)),
        ("Participants", info.get("participants") or folder.attributes.get("participants") or "-"),
        ("Transcript", f"[{_escape_link_text(transcript_name)}]({_relative_link(transcript_name)})"),
        ("Raw JSON", f"[{_escape_link_text(raw_name)}]({_relative_link(raw_name)})"),
        ("Folder config", f"[{FOLDER_CONFIG_LABEL}]({(folder.config_file or folder.path).as_uri()})"),
        ("Transforms", ", ".join(name for name, _ in folder.transforms) or "none"),
        ("SHA-256", f"`{rec['sha256']}`"),
    ]
    lines = [f"# {title}", ""]
    lines += [f"- **{k}:** {v}" for k, v in rows]
    return "\n".join(lines) + "\n"


FOLDER_CONFIG_LABEL = ".speakr-sync.yaml"
