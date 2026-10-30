"""Forward ASR requests to WhisperX and turn spoken punctuation into symbols.

Speakr posts audio to ASR_BASE_URL/asr. This proxy passes every request to
UPSTREAM unchanged. For JSON responses it runs the "text" fields (top level
and per segment) through spoken_punctuation.convert, so the transcript Speakr
stores already has the symbols. Anything that is not JSON is passed through.
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from spoken_punctuation import convert

UPSTREAM = os.environ.get("UPSTREAM", "http://whisperx-asr:9000").rstrip("/")
PORT = int(os.environ.get("PORT", "9000"))
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "3600"))
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer",
              "upgrade", "proxy-authorization", "proxy-authenticate", "host",
              "content-length", "accept-encoding"}


def punctuate(data):
    if isinstance(data, dict):
        if isinstance(data.get("text"), str):
            data["text"] = convert(data["text"])
        for seg in data.get("segments") or []:
            if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                seg["text"] = convert(seg["text"])
    return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        req = urllib.request.Request(UPSTREAM + self.path, data=body, headers=headers,
                                     method=self.command)
        try:
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
            status, resp_headers, payload = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, resp_headers, payload = e.code, e.headers, e.read()

        ctype = resp_headers.get("Content-Type", "")
        if "json" in ctype and self.command == "POST":
            try:
                payload = json.dumps(punctuate(json.loads(payload))).encode("utf-8")
            except ValueError:
                pass

        self.send_response(status)
        for k, v in resp_headers.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = _forward

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"asr-punctuate on :{PORT} -> {UPSTREAM}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
