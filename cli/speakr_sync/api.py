"""Client for the Speakr API v1 (see the API reference in the Speakr docs)."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from .config import ATTRIBUTE_KEYS, FolderConfig


class SpeakrError(Exception):
    pass


class SpeakrClient:
    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        token: str,
        relogin: Callable[[], None] | None = None,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.relogin = relogin  # called once when the Authelia session has expired

    def _request(self, method: str, path: str, build: Callable[[], dict] | None = None) -> requests.Response:
        """build() returns the extra kwargs for requests; it is called again after a re-login."""
        for attempt in (1, 2):
            kwargs = build() if build else {}
            try:
                resp = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=kwargs.pop("timeout", 120),
                    allow_redirects=False,
                    **kwargs,
                )
            except requests.RequestException as exc:
                raise SpeakrError(f"{method} {path}: {exc}") from exc
            session_expired = resp.status_code == 401 or (
                resp.status_code in (301, 302, 303, 307) and "/authelia" in resp.headers.get("Location", "")
            )
            if session_expired and attempt == 1 and self.relogin:
                self.relogin()
                continue
            return resp
        return resp  # pragma: no cover - loop always returns

    def _json(self, resp: requests.Response, what: str) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise SpeakrError(f"{what}: HTTP {resp.status_code} {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise SpeakrError(f"{what}: response is not JSON (is the Authelia login still valid?)") from exc

    def token_info(self) -> dict[str, Any]:
        return self._json(self._request("GET", "/api/v1/tokens/current"), "check token")

    def upload(self, path: Path, fields: dict[str, str], idempotency_key: str) -> int:
        """fields: form values from upload_fields(folder)."""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        handles = []

        def build() -> dict:
            handle = path.open("rb")  # reopened on each attempt, so a retry sends the whole file
            handles.append(handle)
            return {
                "files": {"file": (path.name, handle, mime)},
                "data": {**fields, "idempotency_key": idempotency_key},
                "timeout": 3600,
            }

        try:
            resp = self._request("POST", "/api/v1/recordings/upload", build)
        finally:
            for handle in handles:
                handle.close()
        body = self._json(resp, f"upload {path.name}")
        if "id" not in body:
            raise SpeakrError(f"upload {path.name}: no recording id in the response: {body}")
        return int(body["id"])

    def transcribe(self, recording_id: int, body: dict[str, Any]) -> None:
        """POST /api/v1/recordings/{id}/transcribe (scope "process"): transcribe again."""
        resp = self._request("POST", f"/api/v1/recordings/{recording_id}/transcribe", lambda: {"json": body})
        if resp.status_code >= 400:
            raise SpeakrError(f"transcribe: HTTP {resp.status_code} {resp.text[:300]}")

    def status(self, recording_id: int) -> dict[str, Any]:
        return self._json(self._request("GET", f"/api/v1/recordings/{recording_id}/status"), "status")

    def recording(self, recording_id: int) -> dict[str, Any]:
        return self._json(
            self._request("GET", f"/api/v1/recordings/{recording_id}", lambda: {"params": {"format": "minimal"}}),
            "recording details",
        )

    def changes(self, cursor: str | None, limit: int = 500) -> tuple[int, dict[str, Any]]:
        """GET /api/v1/recordings/changes. Returns (HTTP status, body); 410 means the cursor expired."""
        params = {"limit": limit, **({"cursor": cursor} if cursor else {})}
        resp = self._request("GET", "/api/v1/recordings/changes", lambda: {"params": params})
        if resp.status_code == 410:
            return 410, {}
        return resp.status_code, self._json(resp, "changes")

    def transcript(self, recording_id: int) -> dict[str, Any]:
        return self._json(
            self._request("GET", f"/api/v1/recordings/{recording_id}/transcript", lambda: {"params": {"format": "json"}}),
            "transcript",
        )


def upload_fields(folder: FolderConfig | dict[str, Any]) -> dict[str, str]:
    """Form fields for the upload, from the folder config (attributes plus transcription options)."""
    if isinstance(folder, FolderConfig):
        attrs = folder.attributes
        extra = {
            "language": folder.language,
            "transcription_model": folder.transcription_model,
            "hotwords": folder.hotwords,
            "initial_prompt": folder.initial_prompt,
            "min_speakers": folder.min_speakers,
            "max_speakers": folder.max_speakers,
        }
    else:
        attrs, extra = folder, {}
    unknown = set(attrs) - ATTRIBUTE_KEYS
    if unknown:
        raise SpeakrError(f"unknown attribute(s): {', '.join(sorted(unknown))}")

    fields: dict[str, str] = {}
    for key, value in {**extra, **attrs}.items():
        if value is None or value == "" or value == []:
            continue
        if key == "tag_ids":
            for i, tag in enumerate(value):
                fields[f"tag_ids[{i}]"] = str(tag)
        elif key == "participants" and isinstance(value, list):
            fields[key] = ", ".join(str(v) for v in value)
        else:
            fields[key] = str(value)
    return fields
