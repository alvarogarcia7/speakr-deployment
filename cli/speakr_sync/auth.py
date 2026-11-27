"""Login to the server.

Two layers, both needed:
1. Authelia (the login in front of Speakr, see authelia/ in the repo): username and password,
   answered with a session cookie. Caddy checks this cookie on every request.
2. Speakr API token (Settings > API tokens in Speakr), sent as "Authorization: Bearer".

The password is read from SPEAKR_PASSWORD or asked for. Neither is stored on disk.
"""

from __future__ import annotations

import getpass
import os
import sys

import requests

from .config import ServerConfig


class AuthError(Exception):
    pass


def configure_tls(session: requests.Session, server: ServerConfig) -> None:
    if server.ca_bundle:
        session.verify = server.ca_bundle
    elif not server.verify_tls:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session.verify = False


def api_token(server: ServerConfig) -> str:
    token = os.environ.get(server.api_token_env, "").strip()
    if not token:
        raise AuthError(f"no Speakr API token: set {server.api_token_env} (create one in Speakr under API tokens)")
    return token


def read_password(server: ServerConfig) -> tuple[str, str]:
    """Returns (password, where it came from), so a failed login can say which source was used."""
    password = os.environ.get("SPEAKR_PASSWORD")
    if password:
        return password, "the SPEAKR_PASSWORD environment variable"
    if not sys.stdin.isatty():
        raise AuthError("no password: set SPEAKR_PASSWORD (nothing to ask on a terminal-less run)")
    return getpass.getpass(f"Password for {server.username} at {server.url}: "), "the prompt"


def login_authelia(session: requests.Session, server: ServerConfig, password: str, source: str = "") -> None:
    """POST /authelia/api/firstfactor stores the session cookie in `session`.
    `source` says where the password came from; it is shown in error messages."""
    url = f"{server.url}/authelia/api/firstfactor"
    who = f"Authelia login for user '{server.username}' at {server.url}"
    used = f" (password from {source})" if source else ""
    try:
        resp = session.post(
            url,
            json={"username": server.username, "password": password, "keepMeLoggedIn": False},
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise AuthError(f"cannot reach {server.url}: {exc}") from exc
    if resp.status_code == 401:
        raise AuthError(
            f"{who} refused: wrong username or password{used}. This is the Authelia password "
            "(make password on the server), not the Speakr admin password."
        )
    if resp.status_code == 429:
        raise AuthError(f"{who} refused: too many attempts, wait a few minutes")
    if resp.status_code != 200:
        raise AuthError(f"{who} failed with HTTP {resp.status_code} at {url}")

    state = session.get(f"{server.url}/authelia/api/state", timeout=30, allow_redirects=False)
    try:
        ok = state.status_code == 200 and state.json().get("status") == "OK"
    except ValueError:
        ok = False
    if not ok:
        raise AuthError(f"{who}: the server accepted the login but no session cookie came back "
                        "(is the server behind Authelia, and is the URL HTTPS?)")
