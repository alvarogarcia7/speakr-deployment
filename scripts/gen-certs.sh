#!/usr/bin/env bash
# Create a local certificate authority and a server certificate for Caddy.
#
#   caddy/certs/ca.crt, ca.key      CA (ca.key stays private; ca.crt is what clients trust)
#   caddy/certs/server.crt, .key    server certificate for Caddy, signed by the CA
#
# Names in the certificate: localhost, 127.0.0.1, ::1, this machine's hostname,
# SITE_ADDRESS from .env, and any extra names in CERT_HOSTS (comma separated).
# Run with FORCE=1 to recreate the server certificate (for example after adding a name).
# The CA is kept unless it is missing, so clients that trust ca.crt stay valid.
set -euo pipefail

cd "$(dirname "$0")/.."
DIR=caddy/certs
mkdir -p "$DIR"
umask 077

env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }

names=(localhost "$(hostname)")
site=$(env_value SITE_ADDRESS); [ -n "$site" ] && names+=("$site")
IFS=',' read -r -a extra <<< "${CERT_HOSTS:-}"
for n in "${extra[@]}"; do [ -n "$n" ] && names+=("$(echo "$n" | xargs)"); done

san="subjectAltName=DNS:localhost,IP:127.0.0.1,IP:0:0:0:0:0:0:0:1"
for n in "${names[@]}"; do
  case "$n" in
    localhost|""|:*|*[!A-Za-z0-9.-]*) ;;   # skip empty, port-only and non-hostname values
    *) san+=",DNS:$n" ;;
  esac
done
san=$(echo "$san" | tr ',' '\n' | awk '!seen[$0]++' | paste -sd, -)

if [ ! -f "$DIR/ca.crt" ] || [ ! -f "$DIR/ca.key" ]; then
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout "$DIR/ca.key" -out "$DIR/ca.crt" \
    -subj "/CN=Speakr local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  echo "Created CA: $DIR/ca.crt (install this file on the machines that open Speakr)"
fi

if [ "${FORCE:-0}" = 1 ] || [ ! -f "$DIR/server.crt" ] || [ ! -f "$DIR/server.key" ]; then
  openssl req -new -newkey rsa:2048 -nodes -keyout "$DIR/server.key" -out "$DIR/server.csr" \
    -subj "/CN=speakr" 2>/dev/null
  printf '%s\n' "$san" "basicConstraints=CA:FALSE" "keyUsage=critical,digitalSignature,keyEncipherment" \
    "extendedKeyUsage=serverAuth" > "$DIR/server.ext"
  openssl x509 -req -in "$DIR/server.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
    -days 825 -sha256 -extfile "$DIR/server.ext" -out "$DIR/server.crt" 2>/dev/null
  rm -f "$DIR/server.csr" "$DIR/server.ext"
  echo "Created server certificate: $DIR/server.crt"
  echo "  names: $san"
fi
chmod 644 "$DIR/ca.crt" "$DIR/server.crt"
chmod 600 "$DIR/ca.key" "$DIR/server.key"
