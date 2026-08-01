#!/bin/sh
# Render config/pjsip.conf from config/pjsip.conf.template + .env (no Python required).
# Used by docker compose pjsip-render and scripts/docker-up.sh.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ROOT}/.env"
TEMPLATE="${ROOT}/config/pjsip.conf.template"
OUTPUT="${ROOT}/config/pjsip.conf"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE (copy from .env.example and fill SIPUP_* secrets)." >&2
  exit 1
fi
if [ ! -f "$TEMPLATE" ]; then
  echo "Missing $TEMPLATE" >&2
  exit 1
fi

# Strip Windows CR so sourcing works when .env was edited on Windows (CRLF → exit 127).
ENV_FILE_UNIX="$(mktemp)"
trap 'rm -f "$ENV_FILE_UNIX"' EXIT
tr -d '\r' < "$ENV_FILE" > "$ENV_FILE_UNIX"
# shellcheck disable=SC1090
. "$ENV_FILE_UNIX"

SIPUP_SIP_HOST="${SIPUP_SIP_HOST:-}"
SIPUP_SIP_DOMAIN="${SIPUP_SIP_DOMAIN:-sip.sipup.org}"
SIPUP_SIP_PORT="${SIPUP_SIP_PORT:-5060}"
REGISTRAR="${SIPUP_SIP_HOST:-$SIPUP_SIP_DOMAIN}"
FROM_DOMAIN="${SIPUP_SIP_DOMAIN:-$REGISTRAR}"
AOR_CONTACT="sip:${REGISTRAR}:${SIPUP_SIP_PORT}"
SERVER_URI="sip:${REGISTRAR}:${SIPUP_SIP_PORT}"
CLIENT_URI="sip:${SIPUP_SIP_USERNAME}@${FROM_DOMAIN}"

escape_sed() {
  printf '%s' "$1" | sed -e 's/[\\/&|]/\\&/g'
}

NARAYANA_SIP_USERNAME="${NARAYANA_SIP_USERNAME:-}"
NARAYANA_SIP_PASSWORD="${NARAYANA_SIP_PASSWORD:-}"
NARAYANA_OUTBOUND_CALLER_ID="${NARAYANA_OUTBOUND_CALLER_ID:-}"
NARAYANA_SIP_DOMAIN="${NARAYANA_SIP_DOMAIN:-rdx.narayana.im}"
NARAYANA_SIP_PORT="${NARAYANA_SIP_PORT:-5061}"
NARAYANA_AOR_CONTACT="sip:${NARAYANA_SIP_DOMAIN}:${NARAYANA_SIP_PORT}"
NARAYANA_SERVER_URI="${NARAYANA_AOR_CONTACT}"
NARAYANA_CLIENT_URI="sip:${NARAYANA_SIP_USERNAME}@${NARAYANA_SIP_DOMAIN}"
SIPUP_SIP_USERNAME="${SIPUP_SIP_USERNAME:-}"
SIPUP_SIP_PASSWORD="${SIPUP_SIP_PASSWORD:-}"
SIPUP_OUTBOUND_CALLER_ID="${SIPUP_OUTBOUND_CALLER_ID:-}"
SIPUP_DTMF_MODE="${SIPUP_DTMF_MODE:-rfc4733}"
SOFTPHONE_USER="${ASTERISK_SIP_USER:-${SOFTPHONE_SIP_USER:-softphone1}}"
SOFTPHONE_PASSWORD="${ASTERISK_SIP_PASSWORD:-${SOFTPHONE_SIP_PASSWORD:-changeme-softphone}}"

ASTERISK_EXTERNAL_IP="${ASTERISK_EXTERNAL_IP:-}"
if [ -z "$ASTERISK_EXTERNAL_IP" ]; then
  ASTERISK_EXTERNAL_IP="$(curl -fsS --max-time 5 ifconfig.me 2>/dev/null || true)"
fi
if [ -z "$ASTERISK_EXTERNAL_IP" ]; then
  echo "Set ASTERISK_EXTERNAL_IP in $ENV_FILE (your public IP for RTP/SIP NAT)." >&2
  exit 1
fi

RTP_TEMPLATE="${ROOT}/config/rtp.conf.template"
RTP_OUTPUT="${ROOT}/config/rtp.conf"
if [ -f "$RTP_TEMPLATE" ]; then
  sed -e "s|REPLACE_ASTERISK_EXTERNAL_IP|$(escape_sed "$ASTERISK_EXTERNAL_IP")|g" \
    "$RTP_TEMPLATE" > "$RTP_OUTPUT"
  echo "Wrote $RTP_OUTPUT (externaddr=$ASTERISK_EXTERNAL_IP)"
fi

sed \
  -e "s|REPLACE_ASTERISK_EXTERNAL_IP|$(escape_sed "$ASTERISK_EXTERNAL_IP")|g" \
  -e "s|REPLACE_SIP_USER|$(escape_sed "$SOFTPHONE_USER")|g" \
  -e "s|REPLACE_SIP_PASSWORD|$(escape_sed "$SOFTPHONE_PASSWORD")|g" \
  -e "s|REPLACE_NARAYANA_SIP_USERNAME|$(escape_sed "$NARAYANA_SIP_USERNAME")|g" \
  -e "s|REPLACE_NARAYANA_SIP_PASSWORD|$(escape_sed "$NARAYANA_SIP_PASSWORD")|g" \
  -e "s|REPLACE_NARAYANA_AOR_CONTACT|$(escape_sed "$NARAYANA_AOR_CONTACT")|g" \
  -e "s|REPLACE_NARAYANA_SERVER_URI|$(escape_sed "$NARAYANA_SERVER_URI")|g" \
  -e "s|REPLACE_NARAYANA_CLIENT_URI|$(escape_sed "$NARAYANA_CLIENT_URI")|g" \
  -e "s|REPLACE_NARAYANA_FROM_DOMAIN|$(escape_sed "$NARAYANA_SIP_DOMAIN")|g" \
  -e "s|REPLACE_NARAYANA_OUTBOUND_CALLER_ID|$(escape_sed "$NARAYANA_OUTBOUND_CALLER_ID")|g" \
  -e "s|REPLACE_SIPUP_SIP_USERNAME|$(escape_sed "$SIPUP_SIP_USERNAME")|g" \
  -e "s|REPLACE_SIPUP_SIP_PASSWORD|$(escape_sed "$SIPUP_SIP_PASSWORD")|g" \
  -e "s|REPLACE_SIPUP_OUTBOUND_CALLER_ID|$(escape_sed "$SIPUP_OUTBOUND_CALLER_ID")|g" \
  -e "s|REPLACE_SIPUP_AOR_CONTACT|$(escape_sed "$AOR_CONTACT")|g" \
  -e "s|REPLACE_SIPUP_IDENTIFY_MATCH|$(escape_sed "$REGISTRAR")|g" \
  -e "s|REPLACE_SIPUP_FROM_DOMAIN|$(escape_sed "$FROM_DOMAIN")|g" \
  -e "s|REPLACE_SIPUP_SERVER_URI|$(escape_sed "$SERVER_URI")|g" \
  -e "s|REPLACE_SIPUP_CLIENT_URI|$(escape_sed "$CLIENT_URI")|g" \
  -e "s|REPLACE_SIPUP_DTMF_MODE|$(escape_sed "$SIPUP_DTMF_MODE")|g" \
  "$TEMPLATE" > "$OUTPUT"

if grep -E '^[^;]*REPLACE_[A-Z0-9_]+' "$OUTPUT" >/dev/null 2>&1; then
  echo "Unreplaced placeholders remain in $OUTPUT — check .env SIPUP_* / NARAYANA_* values." >&2
  grep -E '^[^;]*REPLACE_[A-Z0-9_]+' "$OUTPUT" >&2 || true
  exit 1
fi

echo "Wrote $OUTPUT (SIP UP contact=$AOR_CONTACT external_ip=$ASTERISK_EXTERNAL_IP)"
