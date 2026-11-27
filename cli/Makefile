# Tasks for speakr-sync. Run from this folder.
#   make install                 create .venv with uv and install speakr-sync with the test tools
#   make test                    run the test suite
#   make check                   log in to the server and check the folder configs
#   make run                     send new files, wait for their transcripts, pick up edits
#   make watch                   same, repeated every refresh_seconds (Ctrl+C to stop)
#   make status                  list the files and their state
#   make rerender                rebuild transcripts from the stored JSON
#   make retranscribe FILE=name  ask Speakr to transcribe a finished file again (ALL=1 for every file)
#   make init-config             write an example global config (~/.config/speakr-sync/config.yaml)
#   make init-folder FOLDER=dir  write an example .speakr-sync.yaml into a folder
#
# Requires uv (https://docs.astral.sh/uv/). Variables: CONFIG (global config file),
# FOLDER (for init-folder), PYTHON (interpreter for the venv, default python3).

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
CONFIG ?=
FOLDER ?=
FILE   ?=
ALL    ?=

# Pass --config only when CONFIG is set; otherwise speakr-sync uses its default path
CONFIG_ARG := $(if $(CONFIG),--config $(CONFIG),)

.DEFAULT_GOAL := help
.PHONY: help install test check run watch status rerender retranscribe init-config init-folder clean

help: ## List the tasks
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

# uv creates the venv and installs the package (no pip needed)
$(BIN)/speakr-sync: pyproject.toml $(wildcard speakr_sync/*.py)
	@test -x $(BIN)/python || uv venv --quiet --python $(PYTHON) $(VENV)
	uv pip install --quiet --python $(BIN)/python -e ".[test]"
	@touch $@

install: $(BIN)/speakr-sync ## Create .venv and install speakr-sync with the test tools

test: install ## Run the test suite
	$(BIN)/python -m pytest -q

check: install ## Log in to the server and check the token and folder configs
	$(BIN)/speakr-sync $(CONFIG_ARG) check

run: install ## Send new files, wait for their transcripts, pick up edits
	$(BIN)/speakr-sync $(CONFIG_ARG) run

watch: install ## Repeat every refresh_seconds (Ctrl+C to stop)
	$(BIN)/speakr-sync $(CONFIG_ARG) watch

status: install ## List the files and their state
	$(BIN)/speakr-sync $(CONFIG_ARG) status

rerender: install ## Rebuild transcripts from the stored JSON with the current transforms
	$(BIN)/speakr-sync $(CONFIG_ARG) rerender

init-config: install ## Write an example global config (refuses to overwrite)
	$(BIN)/speakr-sync $(CONFIG_ARG) init-config $(CONFIG)

retranscribe: install ## Ask Speakr to transcribe FILE=name again (or ALL=1)
	@test -n "$(FILE)$(ALL)" || { echo "usage: make retranscribe FILE=name.m4a   or   make retranscribe ALL=1"; exit 1; }
	$(BIN)/speakr-sync $(CONFIG_ARG) retranscribe $(if $(ALL),--all,) $(FILE)

init-folder: install ## Write an example .speakr-sync.yaml into FOLDER=dir
	@test -n "$(FOLDER)" || { echo "usage: make init-folder FOLDER=path/to/folder"; exit 1; }
	$(BIN)/speakr-sync init-folder "$(FOLDER)"

clean: ## Remove the venv, caches and build output
	rm -rf $(VENV) build *.egg-info .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +
