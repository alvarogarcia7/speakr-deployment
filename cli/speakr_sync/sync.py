"""One sync pass: send new files, then fetch the transcripts of finished jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from .api import SpeakrClient, SpeakrError, upload_fields
from .config import AppConfig, FolderConfig, load_folder_config
from .outputs import write_outputs
from .state import State, now_iso

log = logging.getLogger("speakr_sync")
FAILED_STATES = {"FAILED", "ERROR"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover(folder: FolderConfig, settle_seconds: int) -> list[Path]:
    """Audio/video files directly in the folder (not recursive, so output folders are never scanned)."""
    found = []
    for path in sorted(folder.path.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in folder.extensions:
            continue
        if time.time() - path.stat().st_mtime < settle_seconds:
            log.info("%s was modified just now, waiting for it to settle", path.name)
            continue
        found.append(path)
    return found


class Syncer:
    """Record statuses: pending (queued on the server), done, error (upload failed, retried on the
    next pass with the same idempotency key), failed (the server's job failed; not retried),
    removed (deleted on the server; the local file is kept and never sent again)."""

    def __init__(self, app: AppConfig, client: SpeakrClient, state: State, folders: list[FolderConfig]):
        self.app = app
        self.client = client
        self.state = state
        self.folders = {f.path: f for f in folders}

    def _folder_for(self, path: str) -> FolderConfig:
        key = Path(path)
        if key not in self.folders:
            self.folders[key] = load_folder_config(key)
        return self.folders[key]

    def submit(self) -> int:
        """Upload files not seen before. Returns how many uploads were made."""
        uploaded = 0
        for folder in self.folders.values():
            for path in discover(folder, self.app.settle_seconds):
                sha = sha256_file(path)
                rec = self.state.get(sha)
                if rec and rec["status"] in ("pending", "done", "failed", "removed"):
                    if rec["status"] == "failed":
                        log.warning("skip %s: the server failed it before (%s); see `speakr-sync status`",
                                    path.name, rec.get("error"))
                    elif rec["status"] == "removed":
                        log.debug("skip %s: deleted on the server earlier", path.name)
                    else:
                        log.debug("skip %s: already sent (%s)", path.name, rec["status"])
                    continue
                where = dict(local_path=str(path), folder=str(folder.path))
                try:
                    recording_id = self.client.upload(path, upload_fields(folder), idempotency_key=sha)
                except SpeakrError as exc:
                    log.error("upload failed for %s: %s", path.name, exc)
                    self.state.save(sha, **where, status="error", error=str(exc))
                    continue
                log.info("uploaded %s as recording %d", path.name, recording_id)
                self.state.save(
                    sha, **where, status="pending", recording_id=recording_id,
                    error=None, uploaded_at=now_iso(),
                )
                uploaded += 1
        return uploaded

    def poll(self) -> int:
        """Check queued jobs. Returns how many transcripts were written in this pass."""
        finished = 0
        for rec in self.state.by_status("pending"):
            name = Path(rec["local_path"]).name
            try:
                status = self.client.status(rec["recording_id"])
            except SpeakrError as exc:
                log.warning("cannot read status of %s: %s", name, exc)
                continue
            state = str(status.get("status") or "").upper()
            if state in FAILED_STATES:
                message = status.get("error") or status.get("stage_detail") or state
                log.error("server failed to process %s: %s", name, message)
                self.state.save(rec["sha256"], status="failed", error=str(message))
                continue
            if state != "COMPLETED":
                log.info("%s: %s (%s)", name, state or "unknown", status.get("stage") or "waiting")
                continue
            try:
                self._finish(rec)
            except SpeakrError as exc:
                log.warning("could not download the result of %s yet: %s", name, exc)
                continue
            finished += 1
        return finished

    def _finish(self, rec: dict, updated_at: str | None = None) -> None:
        """Download the transcript and write the outputs. Used for a new result and for a recording
        edited on the server (then `updated_at` is the value from the change feed)."""
        folder = self._folder_for(rec["folder"])
        info = self.client.recording(rec["recording_id"])
        raw = self.client.transcript(rec["recording_id"])
        paths = write_outputs(folder, rec, info, raw, self.app.server.url)
        first_time = rec["status"] != "done"
        self.state.save(
            rec["sha256"], status="done", error=None,
            completed_at=now_iso() if first_time else rec.get("completed_at"),
            raw_json=paths["raw_json"], job_md=paths["job_md"], transcript_md=paths["transcript_md"],
            info_json=json.dumps(info, ensure_ascii=False),
            remote_updated_at=updated_at or info.get("updated_at"),
        )
        verb = "done" if first_time else "updated"
        log.info("%s: %s -> %s", verb, Path(rec["local_path"]).name, paths["job_md"])

    def refresh(self) -> int:
        """Re-fetch finished recordings that were edited on the server, using Speakr's change feed.
        Returns how many transcripts were rewritten."""
        rewritten = 0
        cursor = self.state.get_meta("changes_cursor") or None
        while True:
            status, body = self.client.changes(cursor)
            if status == 410:
                log.warning("change feed cursor expired; reading the change feed from the start")
                cursor = None
                continue
            for change in body.get("changes") or []:
                if change.get("type") == "upsert":
                    info = change.get("recording") or {}
                    rec = self.state.by_recording(info.get("id"))
                    if rec and rec["status"] == "done" and info.get("updated_at") != rec["remote_updated_at"]:
                        try:
                            self._finish(rec, updated_at=info.get("updated_at"))
                            rewritten += 1
                        except SpeakrError as exc:
                            log.warning("could not refresh %s yet: %s", Path(rec["local_path"]).name, exc)
                elif change.get("type") == "delete":
                    rec = self.state.by_recording(change.get("id"))
                    if rec and rec["status"] == "done":
                        reason = change.get("reason") or "deleted"
                        log.info("%s was removed on the server (%s); the local file is kept",
                                 Path(rec["local_path"]).name, reason)
                        self.state.save(rec["sha256"], status="removed", error=f"removed on the server ({reason})")
            cursor = body.get("next_cursor") or cursor
            self.state.set_meta("changes_cursor", cursor)
            if not body.get("has_more"):
                return rewritten

    def cycle(self) -> tuple[int, int, int]:
        """One pass: send new files, collect finished jobs, pick up edits. Returns (sent, finished, edited)."""
        sent = self.submit()
        finished = self.poll()
        edited = self.refresh()
        return sent, finished, edited

    def rerender(self) -> int:
        """Apply the current folder transforms to the stored raw JSON of finished files (no server needed)."""
        count = 0
        for rec in self.state.by_status("done"):
            folder = self._folder_for(rec["folder"])
            raw = json.loads(Path(rec["raw_json"]).read_text(encoding="utf-8"))
            info = json.loads(rec.get("info_json") or "{}")
            write_outputs(folder, rec, info, raw, self.app.server.url)
            count += 1
        return count
