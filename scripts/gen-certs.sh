#!/usr/bin/env bash
# Create a local certificate authority and a server certificate for Caddy.
#
#   caddy/certs/ca.crt, ca.key      CA (ca.key stays private; ca.crt is what clients trust)
#   caddy/certs/server.crt, .key    server certificate for Caddy, signed by the CA
#
# Names in the certificate: localhost, 127.0.0.1, ::1, this machine's hostname and
# SITE_ADDRESS from .env (the only name you set). Change SITE_ADDRESS, then run with
# FORCE=1 to recreate the server certificate.
# The CA is kept unless it is missing, so clients that trust ca.crt stay valid.
set -euo pipefail

cd "$(dirname "$0")/.."
DIR=caddy/certs
mkdir -p "$DIR"
umask 077

env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }

names=(localhost "$(hostname)")
site=$(env_value SITE_ADDRESS)
case "$site" in
  ""|:*) echo "SITE_ADDRESS in .env must be a host name or IP (current: '${site}'). Set it, then run make certs again."; exit 1 ;;
esac
echo "Generating the server certificate for SITE_ADDRESS=${site} (from .env)"
names+=("$site")
if [[ "$site" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then site_san="IP:$site"; else site_san="DNS:$site"; fi

san="subjectAltName=DNS:localhost,IP:127.0.0.1,IP:0:0:0:0:0:0:0:1"
for n in "${names[@]}"; do
  case "$n" in
    localhost|"") ;;
    "$site") san+=",$site_san" ;;
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
