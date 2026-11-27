COMPOSE := docker compose
CADDY_IMAGE := caddy:2.10
AUTHELIA_IMAGE := authelia/authelia:4.38
PASS_LENGTH := 24
WAIT ?= 1

.PHONY: help init setup certs password pass caddy-sync authelia-sync build start stop restart logs status admin-password clean

help: ## List the available goals
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup:
	@if [ ! -f .env ]; then cp .env.example .env && sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)/; s/^SECRET_KEY=.*/SECRET_KEY=$$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9)/" .env && echo "Created .env, review it. Speakr login: make admin-password"; fi
	@mkdir -p data models caddy/data caddy/config caddy/certs authelia/secrets
	@chmod 700 authelia/secrets
	@for s in session storage jwt; do test -s authelia/secrets/$$s || { head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 > authelia/secrets/$$s; chmod 600 authelia/secrets/$$s; }; done
	@docker volume inspect speakr-models >/dev/null 2>&1 || docker volume create speakr-models >/dev/null

init: ## Create .env and the folders; warns if .env already exists (it is never changed)
	@if [ -f .env ]; then echo "WARNING: .env already exists and was NOT altered. Review it manually against .env.example (SITE_ADDRESS, PUBLIC_URL, SESSION_COOKIE_SECURE, HTTPS_PORT)."; fi
	@$(MAKE) --no-print-directory setup

certs: setup ## Create the local CA and the HTTPS certificate for SITE_ADDRESS in .env (FORCE=1 to renew)
	@FORCE=$(FORCE) scripts/gen-certs.sh
	@echo "Install caddy/certs/ca.crt on the machines that open Speakr, then run 'make restart'."

password: setup ## Set the login for Authelia: username (default admin) and a generated 24-character password, shown once
	@d=$$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2-); echo "$$d" | grep -Eq '^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$$|^[0-9.]+$$' || { echo "SITE_ADDRESS in .env must contain a dot (for example speakr.example.lan) or be an IP address, not '$$d'. Nothing was changed."; exit 1; }; \
	printf "Username [admin]: "; read u; u=$${u:-admin}; \
	echo "$$u" | grep -Eq '^[A-Za-z0-9_.-]+$$' || { echo "Username may only contain letters, digits, _ . and -. Nothing was changed."; exit 1; }; \
	p=$$(python3 scripts/gen_password.py $(PASS_LENGTH)) || exit 1; \
	h=$$(docker run --rm $(AUTHELIA_IMAGE) authelia crypto hash generate argon2 --password "$$p" | sed -n 's/^Digest: //p') || exit 1; \
	test -n "$$h" || { echo "Could not hash the password"; exit 1; }; \
	printf 'users:\n  %s:\n    displayname: "%s"\n    password: "%s"\n    groups:\n      - admin\n' "$$u" "$$u" "$$h" > authelia/users_database.yml; chmod 600 authelia/users_database.yml; \
	rm -f caddy/auth.caddy .caddy-credentials; sed -i '/^CADDY_USER=/d;/^CADDY_PASSWORD=/d' .env; \
	docker run --rm -v speakr-caddy-etc:/etc/caddy --entrypoint sh $(CADDY_IMAGE) -c 'rm -f /etc/caddy/auth.caddy' >/dev/null 2>&1 || true; \
	$(MAKE) --no-print-directory authelia-sync || { rm -f authelia/users_database.yml; echo "Could not copy the login into Authelia. The old login is still active; run make password again."; exit 1; }; \
	$(COMPOSE) restart authelia >/dev/null 2>&1 || true; \
	echo ""; echo "Login (Authelia, asked before Speakr). The password is shown only now and is not stored:"; \
	echo "  Username: $$u"; echo "  Password: $$p"; echo ""

pass: password ## Alias of make password

caddy-sync: setup ## Copy Caddyfile, login and certificate into the Caddy config volume
	@test -f caddy/Caddyfile -a -f caddy/certs/server.crt -a -f caddy/certs/server.key || { echo "Missing Caddy files: run 'make certs' first"; exit 1; }
	@$(COMPOSE) up --no-start caddy >/dev/null
	@docker run --rm -v speakr-caddy-etc:/etc/caddy --entrypoint mkdir $(CADDY_IMAGE) -p /etc/caddy/certs
	@docker run --rm -v speakr-caddy-etc:/etc/caddy --entrypoint mkdir $(CADDY_IMAGE) -p /etc/caddy/www
	@for f in Caddyfile certs/server.crt certs/server.key; do \
		docker run --rm -i -v speakr-caddy-etc:/etc/caddy --entrypoint sh $(CADDY_IMAGE) -c "cat > /etc/caddy/$$f" < caddy/$$f || exit 1; \
	done
	@docker run --rm -i -v speakr-caddy-etc:/etc/caddy --entrypoint sh $(CADDY_IMAGE) -c 'cat > /etc/caddy/www/waiting.html' < caddy/www/waiting.html

authelia-sync: setup ## Copy the Authelia config, login and secrets into the speakr-authelia volume
	@test -f authelia/configuration.yml.in -a -f authelia/users_database.yml -a -f authelia/secrets/session -a -f authelia/secrets/storage -a -f authelia/secrets/jwt || { echo "Missing Authelia files: run 'make password' first"; exit 1; }
	@domain=$$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2-); \
	echo "$$domain" | grep -Eq '^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$$|^[0-9.]+$$' || { echo "SITE_ADDRESS in .env must contain a dot (for example speakr.example.lan) or be an IP address for the Authelia login, not '$$domain'."; exit 1; }
	@docker volume create speakr-authelia >/dev/null
	@url=$$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2-); domain=$$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2-); \
	sed -e "s#@SITE_ADDRESS@#$$domain#g" -e "s#@PUBLIC_URL@#$$url#g" authelia/configuration.yml.in | \
		docker run --rm -i -v speakr-authelia:/config --entrypoint sh $(AUTHELIA_IMAGE) -c 'mkdir -p /config/secrets && cat > /config/configuration.yml' || exit 1
	@for f in users_database.yml secrets/session secrets/storage secrets/jwt; do \
		docker run --rm -i -v speakr-authelia:/config --entrypoint sh $(AUTHELIA_IMAGE) -c "cat > /config/$$f" < authelia/$$f || exit 1; \
	done

build: setup ## Pull the images
	$(COMPOSE) pull

start: setup ## Start Speakr, WhisperX and Caddy in the background
	@grep -qE '^SITE_ADDRESS=[A-Za-z0-9][A-Za-z0-9.-]*$$' .env || { echo "SITE_ADDRESS in .env must be a host name such as speakr.localhost (old values like :80 are rejected by Caddy)."; echo "Set SITE_ADDRESS=speakr.localhost (or your own name with a dot), PUBLIC_URL=https://speakr.localhost:8446 and SESSION_COOKIE_SECURE=true in .env, then run make start."; exit 1; }
	@test -f authelia/users_database.yml || { echo "No login set yet: run 'make password' first"; exit 1; }
	@test -f caddy/certs/server.crt || $(MAKE) --no-print-directory certs
	@$(MAKE) --no-print-directory caddy-sync
	@$(MAKE) --no-print-directory authelia-sync
	$(COMPOSE) up -d --build
	@if [ "$(WAIT)" != 0 ]; then \
		echo "Waiting for WhisperX to download and load the models (first start can take several minutes)..."; echo "While this runs, $$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2-) shows a status page after you log in."; \
		started=$$(docker inspect -f '{{.State.StartedAt}}' speakr-whisperx 2>/dev/null); \
		n=0; while ! { [ "$$(docker inspect -f '{{.State.Health.Status}}' speakr-whisperx 2>/dev/null)" = healthy ] && docker logs --since "$$started" speakr-whisperx 2>&1 | grep -q 'preloaded model'; }; do \
			[ "$$(docker inspect -f '{{.State.Health.Status}}' speakr-whisperx 2>/dev/null)" = unhealthy ] && { echo "WhisperX is unhealthy: see make logs"; exit 1; }; \
			n=$$((n+1)); [ $$n -gt 240 ] && { echo "Timed out after 40 minutes waiting for WhisperX: see make logs"; exit 1; }; \
			sleep 10; \
		done; \
		echo "Models ready: $$(docker logs --since "$$started" speakr-whisperx 2>&1 | grep -o 'preloaded model [^ ]*' | tail -1)"; \
	fi
	@echo "speakr: $$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2)"

stop: ## Stop everything
	$(COMPOSE) --profile '*' down

restart: stop start ## Restart everything

logs: ## Follow the logs
	$(COMPOSE) logs -f --tail=100

status: ## Show container state and disk used by data and models
	$(COMPOSE) ps
	@du -sh data models 2>/dev/null || true

admin-password: ## Show the Speakr login from .env and the Authelia username (the password is not stored)
	@url=$$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2-); email=$$(grep -E '^ADMIN_EMAIL=' .env | cut -d= -f2-); pw=$$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2-); \
	au=$$(sed -n 's/^  \([^ ][^:]*\):$$/\1/p' authelia/users_database.yml 2>/dev/null | head -1); \
	echo "Speakr login:"; echo "  URL:      $$url"; echo "  Email:    $$email"; echo "  Password: $$pw"; echo "  Log in with the email above, not a username."; \
	echo "Login in front of Speakr (Authelia):"; echo "  User:     $${au:-not set, run make password}"; echo "  Password: not stored; run make password to set a new one"

clean: stop ## Remove the containers (keeps data, models and the password)
	$(COMPOSE) --profile '*' rm -f


# ---------------------------------------------------------------------------
# Start automatically at boot (Ubuntu / any Linux with systemd)
#
# How it works:
#   1. service-install fills in systemd/speakr.service.in with this folder's
#      path and the docker binary, and copies it to /etc/systemd/system/.
#   2. `systemctl enable` links it into multi-user.target, so systemd runs
#      `docker compose up -d` from this folder on every boot, after Docker starts.
#   3. `systemctl stop speakr` (or shutdown) runs `docker compose down`.
#
# Once installed, use systemctl rather than make start/stop so systemd's
# view of the service stays correct:
#   sudo systemctl start|stop|restart speakr
#   systemctl status speakr
#
# Needs sudo, and Docker itself enabled at boot (service-install does that too).
# ---------------------------------------------------------------------------
SERVICE      := speakr
SERVICE_FILE := /etc/systemd/system/$(SERVICE).service
DOCKER_BIN   := $(shell command -v docker)

.PHONY: service-install service-uninstall service-status service-logs

service-install: setup ## Install and start the boot service (sudo)
	@test -f authelia/users_database.yml || { echo "No login set yet: run 'make password' first"; exit 1; }
	@test -n "$(DOCKER_BIN)" || { echo "docker not found in PATH"; exit 1; }
	sed -e "s#@WORKDIR@#$(CURDIR)#g" -e "s#@DOCKER@#$(DOCKER_BIN)#g" systemd/$(SERVICE).service.in | sudo tee $(SERVICE_FILE) > /dev/null
	sudo systemctl enable docker.service
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE).service
	@echo "Installed. speakr now starts at boot. Check with: make service-status"

service-uninstall: ## Stop the stack and remove the boot service (sudo)
	-sudo systemctl disable --now $(SERVICE).service
	sudo rm -f $(SERVICE_FILE)
	sudo systemctl daemon-reload
	@echo "Removed. Data, models and the password are untouched."

service-status: ## Show the boot service and container state
	-systemctl status $(SERVICE).service --no-pager
	$(COMPOSE) ps

service-logs: ## Show the boot service's own log (start and stop runs)
	journalctl -u $(SERVICE).service --no-pager -n 100
