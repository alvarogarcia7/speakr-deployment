"""Local record of every file sent to Speakr, keyed by the SHA-256 of its content.

Keying by content (not by path or name) means a renamed or copied file is not sent again.
Statuses:
  pending  uploaded, transcription queued or running on the server
  done     transcript downloaded and written
  error    upload or job failed; the upload is retried on the next run (same idempotency key)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    sha256        TEXT PRIMARY KEY,
    local_path    TEXT NOT NULL,
    folder        TEXT NOT NULL,
    status        TEXT NOT NULL,
    recording_id  INTEGER,
    error         TEXT,
    uploaded_at   TEXT,
    completed_at  TEXT,
    raw_json      TEXT,
    job_md        TEXT,
    transcript_md TEXT,
    info_json     TEXT,
    remote_updated_at TEXT
)
"""
META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
COLUMNS = (
    "local_path", "folder", "status", "recording_id", "error",
    "uploaded_at", "completed_at", "raw_json", "job_md", "transcript_md", "info_json",
    "remote_updated_at",
)


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.execute(META_SCHEMA)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(files)")}
        if "remote_updated_at" not in columns:  # state files created before the change feed existed
            self.db.execute("ALTER TABLE files ADD COLUMN remote_updated_at TEXT")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def get(self, sha256: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM files WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None

    def save(self, sha256: str, **fields: Any) -> None:
        unknown = set(fields) - set(COLUMNS)
        if unknown:
            raise ValueError(f"unknown state field(s): {', '.join(sorted(unknown))}")
        if self.get(sha256) is None:
            cols = ["sha256", *fields]
            marks = ", ".join("?" for _ in cols)
            self.db.execute(
                f"INSERT INTO files ({', '.join(cols)}) VALUES ({marks})",
                (sha256, *fields.values()),
            )
        elif fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(f"UPDATE files SET {assignments} WHERE sha256 = ?", (*fields.values(), sha256))
        self.db.commit()

    def by_recording(self, recording_id: int) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM files WHERE recording_id = ?", (recording_id,)).fetchone()
        return dict(row) if row else None

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def by_status(self, *statuses: str) -> list[dict[str, Any]]:
        marks = ", ".join("?" for _ in statuses)
        rows = self.db.execute(
            f"SELECT * FROM files WHERE status IN ({marks}) ORDER BY local_path", statuses
        ).fetchall()
        return [dict(r) for r in rows]

    def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM files ORDER BY local_path").fetchall()]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
