# Speakr on your server, behind Caddy

Library of recordings with a transcript editor (find and replace, speaker per segment), click a line to jump there, highlight following playback. Transcription runs locally with WhisperX; models are stored in `./models`. Only Caddy is reachable from outside, behind a username and password.

```bash
make init             # creates .env with a random Speakr admin password and secret key
make password         # the username and password Caddy asks for (outer lock)
make build            # pulls the images (WhisperX is several GB)
make start            # open PUBLIC_URL from .env, default http://<server>:8086
make admin-password   # the Speakr login (inner lock): admin + generated password
make logs             # the first start downloads the Whisper model
make stop
```

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

Set `SITE_ADDRESS` to your domain, `HTTP_PORT=80`, `HTTPS_PORT=443`, `PUBLIC_URL=https://<domain>` and `SESSION_COOKIE_SECURE=true`. Without HTTPS the Caddy password travels in clear text, so use plain HTTP only over Tailscale or a trusted LAN.

## Notes

- WhisperX ASR service is alpha software and its upstream targets NVIDIA GPUs. CPU mode works but long recordings are slow.
- Speakr is AGPL-3.0 with a paid commercial license; self-hosting for yourself is covered by the AGPL.
