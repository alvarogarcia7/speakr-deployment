"""Per-file log: <name>.log.md in the output folder, one line for each step that happened to the file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def new_log_path(output_dir: Path, stem: str, sha256: str) -> Path:
    path = output_dir / f"{stem}.log.md"
    if path.exists():  # another file with the same name: keep both logs
        path = output_dir / f"{stem}-{sha256[:8]}.log.md"
    return path


def append(path: Path, rec: dict[str, Any], message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    local = Path(rec["local_path"])
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as fh:
        if new_file:
            fh.write(
                f"# Log: {local.name}\n\n"
                f"- **Local file:** [{local.name}]({local.as_uri()})\n"
                f"- **SHA-256:** `{rec['sha256']}`\n\n"
                "## Events\n\n"
            )
        fh.write(f"- {stamp} {message}\n")
