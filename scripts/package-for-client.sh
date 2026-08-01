#!/usr/bin/env bash
# Create a zip for email/USB. Use package-for-client-full.sh to include .env (LuvVoice, SIP).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--full" ]]; then
  exec bash "$(dirname "$0")/package-for-client-full.sh"
fi
NAME="ivr-dashboard-$(date +%Y%m%d)"
OUT="${ROOT}/${NAME}.zip"
cd "${ROOT}/.."
echo "Creating ${OUT} (no .env — use package-for-client-full.sh for client handoff) ..."
zip -r "${OUT}" "$(basename "${ROOT}")" \
  -x "$(basename "${ROOT}")/.git/*" \
  -x "$(basename "${ROOT}")/**/node_modules/*" \
  -x "$(basename "${ROOT}")/**/.venv/*" \
  -x "$(basename "${ROOT}")/**/__pycache__/*" \
  -x "$(basename "${ROOT}")/**/.pytest_cache/*" \
  -x "$(basename "${ROOT}")/**/dist/*" \
  -x "$(basename "${ROOT}")/**/.env" \
  -x "$(basename "${ROOT}")/**/.env.local" \
  -x "$(basename "${ROOT}")/**/.env.production.local" \
  -x "$(basename "${ROOT}")/infra/sipup/config/pjsip.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/ari.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/extensions.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/http.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/asterisk.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/modules.conf" \
  -x "$(basename "${ROOT}")/infra/sipup/config/logger.conf" \
  -x "$(basename "${ROOT}")/**/*.db" \
  -x "$(basename "${ROOT}")/.cursor/*" \
  -x "$(basename "${ROOT}")/.brv/*" \
  -x "$(basename "${ROOT}")/**/.DS_Store" \
  -x "$(basename "${ROOT}")/backend/.venv/*" \
  -x "$(basename "${ROOT}")/frontend/node_modules/*"
ls -lh "${OUT}"
echo "Done. Send this file — configure .env on the client PC (TeamViewer)."
