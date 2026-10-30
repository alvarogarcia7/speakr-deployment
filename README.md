# Speakr on your server, behind Caddy

Library of recordings with a transcript editor (find and replace, speaker per segment), click a line to jump there, highlight following playback. Transcription runs locally with WhisperX; models are stored in `./models`. Only Caddy is reachable from outside, behind a username and password.

```bash
make init             # creates .env with random Speakr admin password and secret key
make certs            # local CA and HTTPS certificate in caddy/certs (install ca.crt on your machines)
make pass             # Caddy login: username (default admin) and a generated 24-character password (alias of make password)
make build            # pulls the images (WhisperX is several GB)
make start            # open PUBLIC_URL from .env, default https://localhost:8446
make admin-password   # URL, email and password for the Speakr login
make logs             # the first start downloads the Whisper model
make stop
```

Needs Docker with the Compose v2 plugin (`docker compose version`). Without it, install the plugin, for example for one user: `mkdir -p ~/.docker/cli-plugins` and put the `docker-compose` binary from the Compose releases there. `make password` and `make certs` need `python3` and `openssl` on the host.

## Settings worth knowing (`.env`)

- `WHISPER_MODEL`: model loaded at start, default `small`. On CPU, `small` or `medium` is practical; `large-v3` is slow without a GPU. `WHISPER_ALLOWED_MODELS` limits which ones Speakr may pick per upload.
- Speaker detection: needs a free Hugging Face token in `HF_TOKEN` and accepting the terms of `pyannote/speaker-diarization-community-1` on Hugging Face. Then set `ASR_DIARIZE=true`.
- GPU: uncomment `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` and set `WHISPERX_DEVICE=cuda`, `WHISPERX_COMPUTE_TYPE=float16`, `WHISPERX_BATCH_SIZE=16`.
- Summaries, titles and chat need a text model (`TEXT_MODEL_*`). Leave them empty to only transcribe and edit; point them at a local Ollama to keep everything on the server.
- `SPEAKR_VERSION=lite` keeps the image small; `latest` adds semantic search.

## Where things are

- `./models`: Whisper, alignment and speaker models (Hugging Face cache). Survives restarts and upgrades.
- `./data`: Speakr database, settings and uploaded audio. Back this up.
- `./caddy/auth.caddy`: the Caddy username and bcrypt hash. Run `make password` again to change it.
- `caddy/Caddyfile` and `caddy/auth.caddy` are copied into the `speakr-caddy-etc` volume by `make caddy-sync`, which `make start` and `make password` run. After editing either file, run `make restart`.

## Start automatically at boot

Pick one of the two:

**systemd unit (recommended on Ubuntu)**

```bash
make service-install      # sudo systemctl start|stop|restart speakr
make service-status
make service-uninstall
```

`systemd/speakr.service.in` becomes `/etc/systemd/system/speakr.service`. At boot, after Docker and the network are up, it runs `docker compose up -d` here; on stop or shutdown, `docker compose down`.

**init.d script**

```bash
make initd-install        # sudo service speakr start|stop|restart|status
make initd-uninstall
```

`init.d/speakr.in` becomes `/etc/init.d/speakr`, and `update-rc.d` links it into the start runlevels (2 to 5) and the stop runlevels (0, 1, 6). It runs the same `docker compose up -d` and `down`. On Ubuntu, systemd runs init.d scripts through its compatibility layer, so `systemctl status speakr` also works. The Makefile refuses to install both, since that would start the stack twice.

## HTTPS

Caddy serves HTTPS on `HTTPS_PORT` (default 8446) with a certificate from a local CA that `make certs` creates in `caddy/certs/` (`scripts/gen-certs.sh`):

- `ca.crt` is the public part of the CA. Install it on each machine that opens Speakr (macOS Keychain, Windows "Trusted Root Certification Authorities", or the browser's certificate store). Without it the browser warns about the certificate.
- `ca.key` and `server.key` stay private and are git-ignored.
- The certificate names are `localhost`, `127.0.0.1`, `::1`, the machine's hostname, `SITE_ADDRESS`, and any names in `CERT_HOSTS` (for example `CERT_HOSTS=speakr.lan make certs`). Run `FORCE=1 make certs` after changing names, then `make restart`.
- Plain HTTP on `HTTP_PORT` redirects to the HTTPS address.

For a public domain with a trusted certificate (Let's Encrypt), this setup is not enough: remove `auto_https off` and the `tls` line from `caddy/Caddyfile`, use the domain as `SITE_ADDRESS`, and point its DNS at the server with ports 80 and 443 open.

## Notes

- WhisperX ASR service is alpha software and its upstream targets NVIDIA GPUs. CPU mode works but long recordings are slow.
- Speakr is AGPL-3.0 with a paid commercial license; self-hosting for yourself is covered by the AGPL.

## Spoken punctuation

WhisperX writes "period", "comma" and "new line" as words when the speaker says them. The `asr-punctuate` service sits between Speakr and WhisperX and turns them into `. , ? !` and line breaks in every transcript, before Speakr stores it. The conversion lives in `scripts/spoken_punctuation.py`. Rebuild after changing it with `docker compose build asr-punctuate` and `make restart`.

To convert a text file by hand:

```bash
python3 scripts/spoken_punctuation.py < transcript.txt > punctuated.txt
```

## Chars/s in the ASR editor

The "Edit ASR Transcription" table has a Chars/s column: the sentence's character count divided by its duration. Normal speech is about 10 to 20. Red means above 25 (too fast: wrong timing or merged text), amber means below 5 (too slow: text padded over silence or a missing word). The column updates as you edit. It is defined in `speakr-patches/templates/modals/asr-editor-modal.html`, which the `app` image builds on top of Speakr's own image.
