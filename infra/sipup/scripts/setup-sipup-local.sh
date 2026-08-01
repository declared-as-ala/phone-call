#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "Usage: infra/sipup/scripts/setup-sipup-local.sh"
  echo "Prompts for SIP UP device credentials, writes gitignored .env, renders pjsip.conf."
  exit 0
fi

ARI_USER="${ASTERISK_USERNAME:-ari-dev-user}"
ARI_PASSWORD="${ASTERISK_PASSWORD:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)}"

SIPUP_SIP_DOMAIN="${SIPUP_SIP_DOMAIN:-sip.sipup.org}"
SIPUP_SIP_HOST="${SIPUP_SIP_HOST:-}"
SIPUP_SIP_PORT="${SIPUP_SIP_PORT:-5060}"
SIPUP_SIP_USERNAME="${SIPUP_SIP_USERNAME:-}"
SIPUP_PJSIP_ENDPOINT="${SIPUP_PJSIP_ENDPOINT:-sip-up-trunk}"
SIPUP_OUTBOUND_CALLER_ID="${SIPUP_OUTBOUND_CALLER_ID:-}"
SIPUP_DIAL_FORMAT="${SIPUP_DIAL_FORMAT:-e164_no_plus}"
SIPUP_DEFAULT_COUNTRY_CODE="${SIPUP_DEFAULT_COUNTRY_CODE:-216}"

export ARI_USER ARI_PASSWORD
export SIPUP_SIP_DOMAIN SIPUP_SIP_HOST SIPUP_SIP_PORT SIPUP_SIP_USERNAME
export SIPUP_PJSIP_ENDPOINT SIPUP_OUTBOUND_CALLER_ID SIPUP_DIAL_FORMAT SIPUP_DEFAULT_COUNTRY_CODE

if [ -z "$SIPUP_SIP_USERNAME" ]; then
  printf "SIP UP device username (Appareils tab): " >&2
  read -r SIPUP_SIP_USERNAME
fi

if [ -z "${SIPUP_SIP_PASSWORD:-}" ]; then
  printf "SIP UP device password for %s: " "$SIPUP_SIP_USERNAME" >&2
  stty -echo
  read -r SIPUP_SIP_PASSWORD
  stty echo
  printf "\n" >&2
fi

if [ -z "$SIPUP_SIP_USERNAME" ] || [ -z "$SIPUP_SIP_PASSWORD" ]; then
  echo "SIPUP_SIP_USERNAME and SIPUP_SIP_PASSWORD are required." >&2
  exit 1
fi

if [ -z "$SIPUP_OUTBOUND_CALLER_ID" ]; then
  printf "SIP UP outbound caller ID: " >&2
  read -r SIPUP_OUTBOUND_CALLER_ID
fi

export SIPUP_SIP_PASSWORD SIPUP_OUTBOUND_CALLER_ID

cat > .env <<EOF
APP_ENV=development
TELEPHONY_PROVIDER=sip_up

ASTERISK_SIP_BIND=5060
ASTERISK_SIP_TCP_BIND=5060
ASTERISK_SIP_TLS_BIND=5061
ASTERISK_HTTP_BIND=8088
ASTERISK_RTP_START=10000
ASTERISK_RTP_END=10100

ASTERISK_HOST=localhost
ASTERISK_PORT=8088
ASTERISK_USERNAME=$ARI_USER
ASTERISK_PASSWORD=$ARI_PASSWORD
ASTERISK_CONTEXT=ivr-outbound
ASTERISK_ENDPOINT=$SIPUP_PJSIP_ENDPOINT
ASTERISK_ARI_PREFIX=/asterisk/ari
ASTERISK_ARI_APP=ivr-bridge
ASTERISK_ARI_SUBSCRIBE_ALL=true
BACKEND_TELEPHONY_EVENTS_URL=http://127.0.0.1:8000/api/telephony/events
BACKEND_WS_URL=ws://127.0.0.1:8000/ws
BACKEND_WS_TOKEN=
ASTERISK_PROMPT_CONSENT=ivr/consent
ASTERISK_PROMPT_VERIFICATION_CODE=ivr/verification-code
ASTERISK_PROMPT_PENDING_ADMIN=ivr/pending-admin
ASTERISK_PROMPT_APPROVED=ivr/approved
ASTERISK_PROMPT_REJECTED=ivr/rejected
ASTERISK_PROMPT_FAILED=ivr/failed
ASTERISK_PROMPT_DECLINED=ivr/declined

SIPUP_SIP_DOMAIN=$SIPUP_SIP_DOMAIN
SIPUP_SIP_HOST=$SIPUP_SIP_HOST
SIPUP_SIP_PORT=$SIPUP_SIP_PORT
SIPUP_SIP_USERNAME=$SIPUP_SIP_USERNAME
SIPUP_SIP_PASSWORD=$SIPUP_SIP_PASSWORD
SIPUP_PJSIP_ENDPOINT=$SIPUP_PJSIP_ENDPOINT
SIPUP_OUTBOUND_CALLER_ID=$SIPUP_OUTBOUND_CALLER_ID
SIPUP_DIAL_FORMAT=$SIPUP_DIAL_FORMAT
SIPUP_DEFAULT_COUNTRY_CODE=$SIPUP_DEFAULT_COUNTRY_CODE

NARAYANA_SIP_DOMAIN=rdx.narayana.im
NARAYANA_SIP_USERNAME=
NARAYANA_SIP_PASSWORD=
NARAYANA_SIP_PORT=5061
NARAYANA_SIP_TRANSPORT=tls
NARAYANA_DTMF_MODE=rfc4733
NARAYANA_OUTBOUND_CALLER_ID=
NARAYANA_DIAL_FORMAT=e164_no_plus
NARAYANA_DEFAULT_COUNTRY_CODE=216
NARAYANA_DIAL_PREFIX=
EOF

for f in ari.conf http.conf modules.conf asterisk.conf; do
  if [[ ! -f "config/$f" ]] && [[ -f "config/${f}.example" ]]; then
    cp "config/${f}.example" "config/$f"
  fi
done

if [[ ! -f config/ari.conf ]] || grep -q 'change-me' config/ari.conf 2>/dev/null; then
  cat > config/ari.conf <<EOF
[general]
enabled = yes
pretty = yes
allowed_origins = *

[$ARI_USER]
type = user
read_only = no
password_format = plain
password = $ARI_PASSWORD
EOF
fi

python3 scripts/render_pjsip_from_env.py

echo "SIP UP local Asterisk config written under infra/sipup/."
echo "ARI user: $ARI_USER"
echo "SIP UP trunk endpoint: $SIPUP_PJSIP_ENDPOINT (registrar: ${SIPUP_SIP_HOST:-$SIPUP_SIP_DOMAIN}:$SIPUP_SIP_PORT)"
echo "Next: docker compose up -d"
echo "Verify: docker compose exec asterisk asterisk -rx \"pjsip show endpoint sip-up-trunk\""
