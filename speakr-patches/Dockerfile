# Speakr with the patched ASR editor (adds a Chars/s column).
# Build context is this folder; the base image tag comes from SPEAKR_VERSION in .env.
ARG SPEAKR_VERSION=lite
FROM learnedmachine/speakr:${SPEAKR_VERSION}
COPY templates/modals/asr-editor-modal.html /app/templates/modals/asr-editor-modal.html
