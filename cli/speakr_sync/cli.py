"""Command line: speakr-sync <command> [--config FILE]."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

from . import auth
from .api import SpeakrClient, SpeakrError
from .config import (
    DEFAULT_CONFIG_PATH,
    EXAMPLE_APP_CONFIG,
    EXAMPLE_FOLDER_CONFIG,
    FOLDER_CONFIG_NAME,
    AppConfig,
    ConfigError,
    FolderConfig,
    load_app_config,
    load_folder_config,
)
from .state import State
from .sync import Syncer

log = logging.getLogger("speakr_sync")


def _login(app: AppConfig) -> SpeakrClient:
    session = requests.Session()
    auth.configure_tls(session, app.server)
    token = auth.api_token(app.server)
    password, source = auth.read_password(app.server)

    def relogin() -> None:
        log.info("session expired, logging in again")
        auth.login_authelia(session, app.server, password, source)

    # Step 1: Authelia login (username and password). Its errors name the account and password source.
    auth.login_authelia(session, app.server, password, source)
    client = SpeakrClient(session, app.server.url, token, relogin=relogin)
    # Step 2: Speakr API token. Checked now, so a bad token is reported as such, not as a login failure.
    try:
        client.token_info()
    except SpeakrError as exc:
        raise auth.AuthError(
            f"Authelia login worked, but the Speakr API token from {app.server.api_token_env} was rejected "
            f"({exc}). Create a token in Speakr (API tokens) and export it as {app.server.api_token_env}."
        ) from exc
    return client


def _load_folders(app: AppConfig) -> list[FolderConfig]:
    return [load_folder_config(p) for p in app.folder_paths]


def _syncer(app: AppConfig, client: SpeakrClient, state: State) -> Syncer:
    return Syncer(app, client, state, _load_folders(app))


def cmd_check(app: AppConfig, client: SpeakrClient, state: State) -> int:
    info = client.token_info()
    print(f"logged in to {app.server.url}; API token: {info}")
    for folder in _load_folders(app):
        print(f"folder ok: {folder.path} (config {folder.config_file}, output {folder.output_path})")
    print(f"state file: {state.path}")
    return 0


def cmd_run(app: AppConfig, client: SpeakrClient, state: State, wait: bool) -> int:
    syncer = _syncer(app, client, state)
    sent, finished, edited = syncer.cycle()
    print(f"uploaded {sent} file(s), wrote {finished} transcript(s), updated {edited} edited recording(s)")
    if not wait:
        return 0
    deadline = time.monotonic() + app.wait_minutes * 60
    while state.by_status("pending"):
        if time.monotonic() > deadline:
            print("stopped waiting: some jobs are still running; run again later or use watch")
            return 0
        time.sleep(app.refresh_seconds)
        syncer.cycle()
    return 0


def cmd_watch(app: AppConfig, client: SpeakrClient, state: State) -> int:
    print(f"watching {len(app.folder_paths)} folder(s) every {app.refresh_seconds}s; Ctrl+C to stop")
    while True:
        try:
            # reloaded each pass: folder config edits apply without a restart
            _syncer(app, client, state).cycle()
        except (ConfigError, SpeakrError, auth.AuthError) as exc:
            log.error("%s (retrying in %ss)", exc, app.refresh_seconds)  # a bad pass must not stop the watcher
        time.sleep(app.refresh_seconds)


def cmd_status(app: AppConfig, state: State) -> int:
    rows = state.all()
    if not rows:
        print("no files processed yet")
        return 0
    for rec in rows:
        name = Path(rec["local_path"]).name
        extra = ""
        if rec.get("job_md"):
            extra = f"  report: {rec['job_md']}"
        if rec.get("error"):
            extra += f"  error: {rec['error']}"
        rid = rec.get("recording_id") or "-"
        print(f"{rec['status']:<8} {name}  recording {rid}  sent {rec.get('uploaded_at') or '-'}{extra}")
    return 0


def cmd_rerender(app: AppConfig, state: State) -> int:
    count = Syncer(app, None, state, _load_folders(app)).rerender()  # type: ignore[arg-type]  # no server needed
    print(f"rewrote {count} transcript(s)")
    return 0


def cmd_retranscribe(app: AppConfig, client: SpeakrClient, state: State, files: list[str], everything: bool) -> int:
    rows = state.by_status("done")
    if everything:
        targets = rows
    else:
        if not files:
            print("name the files to transcribe again (or use --all)", file=sys.stderr)
            return 2
        wanted = set(files)
        targets = [r for r in rows if Path(r["local_path"]).name in wanted or r["local_path"] in wanted]
        missing = wanted - {Path(r["local_path"]).name for r in targets} - {r["local_path"] for r in targets}
        if missing:
            print(f"not a finished recording in the state file: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    if not targets:
        print("nothing to transcribe again")
        return 0
    syncer = _syncer(app, client, state)
    ok = True
    for rec in targets:
        print(f"transcribing again: {Path(rec['local_path']).name}")
        ok &= syncer.retranscribe(rec, timeout_seconds=app.wait_minutes * 60, interval_seconds=app.refresh_seconds)
    return 0 if ok else 1


def cmd_init_config(path: Path) -> int:
    if path.exists():
        print(f"{path} already exists; not changed", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_APP_CONFIG, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def cmd_init_folder(folder: Path) -> int:
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 1
    target = folder / FOLDER_CONFIG_NAME
    if target.exists():
        print(f"{target} already exists; not changed", file=sys.stderr)
        return 1
    target.write_text(EXAMPLE_FOLDER_CONFIG, encoding="utf-8")
    print(f"wrote {target}; edit it, then add the folder to the list in your config file")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="speakr-sync",
        description="Send new recordings to Speakr and save the transcripts as Markdown.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=f"global config (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug messages")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="log in and check the API token and folder configs")
    run = sub.add_parser("run", help="send new files once; wait for their transcripts")
    run.add_argument("--no-wait", action="store_true", help="do not wait for the jobs to finish")
    sub.add_parser("watch", help="repeat every refresh_seconds")
    sub.add_parser("status", help="list the files and their state")
    sub.add_parser("rerender", help="rebuild transcripts from the stored JSON with the current transforms")
    retr = sub.add_parser("retranscribe", help="ask Speakr to transcribe finished files again, then rewrite them")
    retr.add_argument("files", nargs="*", help="file names (or paths) as they were in the folder")
    retr.add_argument("--all", dest="everything", action="store_true", help="every finished recording")
    init_cfg = sub.add_parser("init-config", help="write an example global config")
    init_cfg.add_argument("path", type=Path, nargs="?", default=DEFAULT_CONFIG_PATH)
    init_folder = sub.add_parser("init-folder", help="write an example folder config")
    init_folder.add_argument("folder", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        if args.command == "init-config":
            return cmd_init_config(args.path.expanduser())
        if args.command == "init-folder":
            return cmd_init_folder(args.folder.expanduser().resolve())

        app = load_app_config(args.config)
        state = State(app.state_file)
        try:
            if args.command == "status":
                return cmd_status(app, state)
            if args.command == "rerender":
                return cmd_rerender(app, state)
            _load_folders(app)  # fail early with a clear message if a folder config is wrong
            client = _login(app)
            if args.command == "check":
                return cmd_check(app, client, state)
            if args.command == "retranscribe":
                return cmd_retranscribe(app, client, state, args.files, args.everything)
            if args.command == "run":
                return cmd_run(app, client, state, wait=not args.no_wait)
            if args.command == "watch":
                return cmd_watch(app, client, state)
        finally:
            state.close()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130
    except (ConfigError, auth.AuthError, SpeakrError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2  # pragma: no cover
