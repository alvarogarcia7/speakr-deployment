COMPOSE := docker compose
CADDY_IMAGE := caddy:2.10
PASS_LENGTH := 24
WAIT ?= 1

.PHONY: help init setup certs password pass caddy-sync build start stop restart logs status admin-password clean

help: ## List the available goals
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup:
	@if [ ! -f .env ]; then cp .env.example .env && sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)/; s/^SECRET_KEY=.*/SECRET_KEY=$$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9)/" .env && echo "Created .env, review it. Speakr login: make admin-password"; fi
	@mkdir -p data models caddy/data caddy/config caddy/certs
	@docker volume inspect speakr-models >/dev/null 2>&1 || docker volume create speakr-models >/dev/null

init: ## Create .env and the folders; warns if .env already exists (it is never changed)
	@if [ -f .env ]; then echo "WARNING: .env already exists and was NOT altered. Review it manually against .env.example (SITE_ADDRESS, PUBLIC_URL, SESSION_COOKIE_SECURE, HTTPS_PORT)."; fi
	@$(MAKE) --no-print-directory setup

certs: setup ## Create the local CA and the HTTPS certificate for SITE_ADDRESS in .env (FORCE=1 to renew)
	@FORCE=$(FORCE) scripts/gen-certs.sh
	@echo "Install caddy/certs/ca.crt on the machines that open Speakr, then run 'make restart'."

password: setup ## Set the Caddy login: username (default admin) and a generated 24-character password
	@printf "Username [admin]: "; read u; u=$${u:-admin}; \
	p=$$(python3 scripts/gen_password.py $(PASS_LENGTH)) || exit 1; \
	h=$$(docker run --rm $(CADDY_IMAGE) caddy hash-password --plaintext "$$p") || exit 1; \
	printf 'basic_auth {\n\t%s %s\n}\n' "$$u" "$$h" > caddy/auth.caddy; \
	printf 'caddy_user=%s\ncaddy_password=%s\n' "$$u" "$$p" > .caddy-credentials; chmod 600 .caddy-credentials; \
	echo ""; echo "Caddy login (copy it now; also saved in .caddy-credentials):"; \
	echo "  Username: $$u"; echo "  Password: $$p"; echo ""; \
	$(MAKE) --no-print-directory caddy-sync; \
	$(COMPOSE) exec caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1 && echo "Caddy reloaded" || true

pass: password ## Alias of make password

caddy-sync: setup ## Copy Caddyfile, login and certificate into the Caddy config volume
	@test -f caddy/Caddyfile -a -f caddy/auth.caddy -a -f caddy/certs/server.crt -a -f caddy/certs/server.key || { echo "Missing Caddy files: run 'make password' and 'make certs' first"; exit 1; }
	@$(COMPOSE) up --no-start caddy >/dev/null
	@docker run --rm -v speakr-caddy-etc:/etc/caddy --entrypoint mkdir $(CADDY_IMAGE) -p /etc/caddy/certs
	@docker run --rm -v speakr-caddy-etc:/etc/caddy --entrypoint mkdir $(CADDY_IMAGE) -p /etc/caddy/www
	@for f in Caddyfile auth.caddy certs/server.crt certs/server.key; do \
		docker run --rm -i -v speakr-caddy-etc:/etc/caddy --entrypoint sh $(CADDY_IMAGE) -c "cat > /etc/caddy/$$f" < caddy/$$f || exit 1; \
	done
	@docker run --rm -i -v speakr-caddy-etc:/etc/caddy --entrypoint sh $(CADDY_IMAGE) -c 'cat > /etc/caddy/www/waiting.html' < caddy/www/waiting.html

build: setup ## Pull the images
	$(COMPOSE) pull

start: setup ## Start Speakr, WhisperX and Caddy in the background
	@grep -qE '^SITE_ADDRESS=[A-Za-z0-9][A-Za-z0-9.-]*$$' .env || { echo "SITE_ADDRESS in .env must be a host name such as localhost (old values like :80 are rejected by Caddy)."; echo "Set SITE_ADDRESS=localhost, PUBLIC_URL=https://localhost:8446 and SESSION_COOKIE_SECURE=true in .env, then run make start."; exit 1; }
	@test -f caddy/auth.caddy || { echo "No login set yet: run 'make password' first"; exit 1; }
	@test -f caddy/certs/server.crt || $(MAKE) --no-print-directory certs
	@$(MAKE) --no-print-directory caddy-sync
	$(COMPOSE) up -d --build
	@if [ "$(WAIT)" != 0 ]; then \
		echo "Waiting for WhisperX to download and load the models (first start can take several minutes)..."; echo "While this runs, $$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2-) shows a status page."; \
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

admin-password: ## Show the Speakr login: URL, email and password
	@url=$$(grep -E '^PUBLIC_URL=' .env | cut -d= -f2-); email=$$(grep -E '^ADMIN_EMAIL=' .env | cut -d= -f2-); pw=$$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2-); \
	echo "Speakr login:"; echo "  URL:      $$url"; echo "  Email:    $$email"; echo "  Password: $$pw"; echo "  Log in with the email above, not a username."

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
	@test -f caddy/auth.caddy || { echo "No password set yet: run 'make password' first"; exit 1; }
	@test -n "$(DOCKER_BIN)" || { echo "docker not found in PATH"; exit 1; }
	@test ! -f /etc/init.d/$(SERVICE) || { echo "The init.d script is installed; run 'make initd-uninstall' first"; exit 1; }
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
# ---------------------------------------------------------------------------
# Alternative: SysV init.d script (for machines or habits that use init.d)
#
# How it works:
#   1. initd-install fills in init.d/$(SERVICE).in with this folder's path and
#      the docker binary, and installs it as /etc/init.d/$(SERVICE).
#   2. update-rc.d links it into runlevels 2-5 (start) and 0, 1, 6 (stop), so it
#      runs `docker compose up -d` at boot and `docker compose down` at shutdown.
#   3. On Ubuntu, systemd picks the script up automatically (systemd-sysv-generator),
#      so `sudo service $(SERVICE) start|stop|status` works.
#
# Pick ONE of service-install (systemd unit, recommended on Ubuntu) or
# initd-install. Installing both would start the stack twice.
# ---------------------------------------------------------------------------
INITD_FILE := /etc/init.d/$(SERVICE)

.PHONY: initd-install initd-uninstall

initd-install: setup ## Install the init.d script and start it (sudo)
	@test -f caddy/auth.caddy || { echo "No password set yet: run 'make password' first"; exit 1; }
	@test ! -f $(SERVICE_FILE) || { echo "The systemd unit is installed; run 'make service-uninstall' first"; exit 1; }
	sed -e "s#@NAME@#$(SERVICE)#g" -e "s#@WORKDIR@#$(CURDIR)#g" -e "s#@DOCKER@#$(DOCKER_BIN)#g" init.d/$(SERVICE).in | sudo tee $(INITD_FILE) > /dev/null
	sudo chmod 755 $(INITD_FILE)
	sudo update-rc.d $(SERVICE) defaults
	sudo systemctl enable docker.service 2>/dev/null || true
	sudo systemctl daemon-reload 2>/dev/null || true
	sudo service $(SERVICE) start
	@echo "Installed. Control it with: sudo service $(SERVICE) start|stop|restart|status"

initd-uninstall: ## Stop and remove the init.d script (sudo)
	-sudo service $(SERVICE) stop
	sudo update-rc.d -f $(SERVICE) remove
	sudo rm -f $(INITD_FILE)
	sudo systemctl daemon-reload 2>/dev/null || true
	@echo "Removed. Data, models and the password are untouched."
