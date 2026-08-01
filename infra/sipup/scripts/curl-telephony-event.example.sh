#!/usr/bin/env sh
# Example: POST one telephony webhook event (no secrets in repo — export vars locally).
#
#   export TELEPHONY_WEBHOOK_URL="http://host.docker.internal:8000/api/telephony/events"
#   export CALL_ID="<uuid from POST /api/calls/start>"
#   export PROVIDER_CALL_ID="<asterisk channel uniqueid or linkedid>"
#
# Usage:
#   ./curl-telephony-event.example.sh ANSWERED
#   ./curl-telephony-event.example.sh DTMF 5
#   ./curl-telephony-event.example.sh HANGUP

set -eu

EVENT="${1:?event_type ANSWERED|DTMF|HANGUP|FAILED}"
DIGIT="${2:-}"

: "${TELEPHONY_WEBHOOK_URL:?set TELEPHONY_WEBHOOK_URL}"
: "${CALL_ID:?set CALL_ID (UUID)}"

BODY=$(printf '%s' "{
  \"provider\": \"asterisk\",
  \"call_id\": \"${CALL_ID}\",
  \"event_type\": \"${EVENT}\",
  \"provider_call_id\": \"${PROVIDER_CALL_ID:-}\"
}")

if [ "$EVENT" = "DTMF" ]; then
  : "${DIGIT:?second arg digit required for DTMF}"
  BODY=$(printf '%s' "{
    \"provider\": \"asterisk\",
    \"call_id\": \"${CALL_ID}\",
    \"event_type\": \"DTMF\",
    \"digit\": \"${DIGIT}\",
    \"provider_call_id\": \"${PROVIDER_CALL_ID:-}\"
  }")
fi

curl -sS -X POST "$TELEPHONY_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "$BODY"
