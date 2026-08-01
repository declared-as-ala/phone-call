#!/usr/bin/env bash
# SIP UP media ⇄ backend event bridge (same env file as SIP UP lab).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/backend"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi
if [[ -f "${ROOT}/infra/sipup/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/infra/sipup/.env"
  set +a
fi
exec python scripts/run_sip_up_ari_bridge.py
