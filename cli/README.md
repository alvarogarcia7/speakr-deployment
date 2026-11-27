# speakr-sync

Command line client for the Speakr server in this repo. It sends new audio and video files from
local folders to Speakr, waits for the transcription, and writes Markdown next to the audio.

## Install

Needs [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer. uv creates the virtual environment.

```bash
cd cli
make install        # creates .venv with uv and installs speakr-sync with the test tools
. .venv/bin/activate  # optional: makes `speakr-sync` available directly
```

Without make: `uv venv .venv && uv pip install --python .venv/bin/python -e ".[test]"`.

Every task in the Makefile runs from `.venv` (`make help` lists them): `make check`, `make run`,
`make watch`, `make status`, `make rerender`, `make test`, `make clean`.

## Set up

1. Global config (servers, folders, refresh rate):
   ```bash
   speakr-sync init-config            # writes ~/.config/speakr-sync/config.yaml
   ```
   Set `server.url` to the `PUBLIC_URL` from the server's `.env`. For the local CA, copy
   `caddy/certs/ca.crt` from the server and set `server.ca_bundle`.
2. Create a Speakr API token in Speakr (API tokens page) and export it:
   ```bash
   export SPEAKR_API_TOKEN=...      # name set by server.api_token_env
   ```
3. Each watched folder needs its own config:
   ```bash
   speakr-sync init-folder ~/Recordings/Meetings   # writes .speakr-sync.yaml in the folder
   ```
   Add the folder to `folders:` in the global config.
4. Check the login and the configs:
   ```bash
   SPEAKR_PASSWORD=... speakr-sync check
   ```
   `SPEAKR_PASSWORD` is the Authelia password (the one from `make password` on the server).
   If it is not set, the command asks for it on a terminal. Unattended runs need the variable.

## Commands

| Command | What it does |
|---|---|
| `speakr-sync check` | Logs in, checks the API token, validates every folder config |
| `speakr-sync run` | Sends new files once, then waits for their transcripts (up to `wait_minutes`) |
| `speakr-sync run --no-wait` | Sends new files and exits; a later `run` or `watch` fetches the results |
| `speakr-sync watch` | Repeats every `refresh_seconds`: sends new files, fetches finished transcripts |
| `speakr-sync status` | Lists every file the client knows, its status and its report |
| `speakr-sync rerender` | Rebuilds the transcripts from the stored JSON with the current `transforms` (no server needed) |
| `speakr-sync retranscribe FILE…` | Asks Speakr to transcribe finished files again with the folder's current settings, waits, rewrites the outputs. `--all` for every finished file |

Add `--config FILE` to use another global config, and `-v` for debug messages.

## Login

The server puts Authelia in front of Speakr. The client:

1. posts the username and password to `/authelia/api/firstfactor` and keeps the session cookie;
2. sends the Speakr API token as `Authorization: Bearer ...` on every API call.

If the Authelia session expires (12 hours, or 1 hour without activity), the client logs in again
once and retries. Passwords are never written to disk.

## Folder config (`.speakr-sync.yaml`)

```yaml
language: en              # ISO 639-1; empty = auto-detect
transcription_model:      # empty = server default
hotwords: ""
initial_prompt: ""
min_speakers:
max_speakers:
attributes:               # Speakr upload fields: title, participants, notes, folder_id, tag_ids, meeting_date
  participants: "Alice, Bob"
extensions: [.mp3, .m4a, .wav]
output_dir: transcripts   # relative to the folder
show_timestamps: true
apple_transcript: false   # true: add the Apple Voice Memos transcript to .transcript.md
transforms:
  - drop_speakers_if_single
```

Unknown keys are errors, so a typo is reported instead of ignored.

## Files are sent once

Each file is identified by the SHA-256 of its content, stored in the state file
(`state_file`, default `~/.local/state/speakr-sync/state.sqlite3`). A renamed or copied file is
not sent again. Files that are still being copied are skipped until they are `settle_seconds`
old. Upload errors are retried on the next run; the upload carries the SHA-256 as
`idempotency_key`, so the server does not create a second recording for the same file. A job the
server reports as failed is not retried: remove its row from the state file to retry it.

## Edits made in Speakr

Open a finished recording in Speakr, edit the transcript (fix text, rename speakers), and the next
`run` or `watch` pass rewrites its `.transcript.md`, `.job.md` and raw JSON. It uses Speakr's change
feed (`GET /api/v1/recordings/changes`) with a cursor kept in the state file, so it only fetches
recordings that changed. Edits never cause a new upload. Recordings deleted on the server are marked
`removed` in the state file, and their local files are kept and not sent again.

## Output

For every file, in `output_dir` next to the audio:

- `<name>.job.md`: a report with the job link (`/recordings/<id>` on the server), a clickable link
  to the local file, processing date, upload date, status, audio duration, language, speakers,
  participants, transforms applied, transcript and raw JSON links, and the SHA-256.
- `<name>.transcript.md`: the transcript after the transforms, one line per segment:
  `[00:01:23] **Alice:** text`.
- `raw/<name>.json`: the transcript as Speakr returned it. `rerender` uses this file.

## Apple Voice Memos transcript

When `apple_transcript: true`, `.transcript.md` gets a second section, "Apple Voice Memos transcript", after the
Speakr one. It holds the transcript that Voice Memos generated, read from the `.m4a` file itself (a `tsrp` atom with JSON, reverse engineered from sample
files; Apple does not document it). Use it to compare with the Speakr transcript. A file without one
shows a note instead.

## Transforms

Transforms edit the transcript before it is written. They run in the order listed in the folder
config. Built-in:

| Name | Options | Effect |
|---|---|---|
| `drop_speakers_if_single` | | One speaker in the recording: remove the speaker name from every line |
| `rename_speakers` | `map` | Rename speakers, by raw label (`SPEAKER_00`) or current name |
| `merge_consecutive` | | Join neighbouring segments of the same speaker |
| `drop_empty` | | Remove segments with no text |
| `replace` | `rules: [{pattern, replacement, regex}]` | Find and replace in the text |

To add one, write a function in `speakr_sync/transforms.py` with the `@transform("name")`
decorator. It takes a `Transcript` and returns a new one.

## Tests

```bash
make test
```

The end-to-end tests run against a fake Authelia and Speakr server, not a real deployment.

## Assumptions to check on the first real run

The Speakr endpoints come from the Speakr API v1 reference (`POST /api/v1/recordings/upload`,
`GET /api/v1/recordings/{id}/status`, `/transcript?format=json`, `/recordings/{id}`). Not checked
against a live server here. The client assumes:

- the upload answer has an `id` field, and statuses are `COMPLETED` or `FAILED`/`ERROR`;
- Speakr accepts the Bearer token behind the Authelia forward-auth check (the request also
  carries the Authelia session cookie);
- the Authelia 4.38 endpoints `firstfactor` and `state` exist under `/authelia/api/`.

`speakr-sync check` tests the login and the token. `run --no-wait` on one small file is the
quickest test of the whole path.
