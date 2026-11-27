"""A fake Authelia + Speakr server on 127.0.0.1, enough for an end-to-end run."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

COOKIE = "speakr_authelia_session=ok"
TOKEN = "test-token"
PASSWORD = "pw"


class FakeServer(BaseHTTPRequestHandler):
    uploads: list = []          # (filename, idempotency_key)
    job_status = "COMPLETED"
    api_expired = False         # when True, the first API call answers 401 to force a re-login
    version = 1                 # bumped on every edit; the change feed reports changes after a cursor
    transcript_text = ["Hello team", "Let us start"]
    removed = False             # when True, recording 7 shows up as deleted in the change feed

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, code, body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self):
        return COOKIE in (self.headers.get("Cookie") or "") and \
            self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path == "/authelia/api/firstfactor":
            data = json.loads(body)
            if data.get("password") != PASSWORD:
                return self._send(401, {"status": "KO"})
            return self._send(200, {"status": "OK"}, {"Set-Cookie": "speakr_authelia_session=ok; Path=/"})
        if self.path == "/api/v1/recordings/upload":
            if not self._authed():
                return self._send(401, {"status": "KO"})
            key = body.decode("latin-1").split('name="idempotency_key"')[1].split("\r\n\r\n")[1].split("\r\n")[0]
            name = body.decode("latin-1").split('filename="')[1].split('"')[0]
            FakeServer.uploads.append((name, key))
            return self._send(200, {"id": 7 + len(FakeServer.uploads) - 1, "status": "PENDING"})
        self._send(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/authelia/api/state":
            if COOKIE in (self.headers.get("Cookie") or ""):
                return self._send(200, {"status": "OK", "data": {"username": "admin"}})
            return self._send(401, {"status": "KO"})
        if not self._authed():
            return self._send(401, {"status": "KO"})
        if FakeServer.api_expired:
            FakeServer.api_expired = False
            return self._send(401, {"status": "KO"})
        if self.path == "/api/v1/tokens/current":
            return self._send(200, {"scopes": ["upload", "read"]})
        url = urlparse(self.path)
        if url.path == "/api/v1/recordings/changes":
            cursor = parse_qs(url.query).get("cursor", [None])[0]
            since = int(cursor) if cursor else 0
            changes = []
            if FakeServer.removed:
                changes.append({"type": "delete", "id": 7, "deleted_at": "x", "reason": "deleted"})
            elif FakeServer.version > since:
                changes.append({"type": "upsert", "recording": {
                    "id": 7, "title": "Team sync", "updated_at": f"2026-11-27T10:00:0{FakeServer.version}.000000Z"}})
            return self._send(200, {"changes": changes, "next_cursor": str(FakeServer.version), "has_more": False})
        if self.path.endswith("/status"):
            return self._send(200, {"status": FakeServer.job_status, "stage": "transcription"})
        if self.path.startswith("/api/v1/recordings/7/transcript"):
            return self._send(200, {"format": "json", "kind": "segments", "duration": 62.0, "segments": [
                {"index": i, "speaker": "Alice", "speaker_label": "SPEAKER_00", "text": text,
                 "start_time": 2.0 * i, "end_time": 2.0 * i + 2.0}
                for i, text in enumerate(FakeServer.transcript_text)]})
        if self.path.startswith("/api/v1/recordings/7"):
            return self._send(200, {"id": 7, "title": "Team sync", "status": "COMPLETED",
                                    "audio_duration": 62.0, "participants": "Alice",
                                    "updated_at": f"2026-11-27T10:00:0{FakeServer.version}.000000Z"})
        self._send(404, {"error": "not found"})


@pytest.fixture
def fake_server():
    FakeServer.uploads = []
    FakeServer.job_status = "COMPLETED"
    FakeServer.api_expired = False
    FakeServer.version = 1
    FakeServer.transcript_text = ["Hello team", "Let us start"]
    FakeServer.removed = False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
