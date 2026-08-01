#!/usr/bin/env bash
# Full client handoff zip: includes backend/.env + infra/sipup/.env (LuvVoice, SIP, etc.).
# Still excludes node_modules, .venv, git, and local DB files.
# WARNING: the zip contains secrets — send only to the client (not public upload).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="ivr-dashboard-full-$(date +%Y%m%d)"
OUT="${ROOT}/${NAME}.zip"
cd "${ROOT}/.."
echo "Creating FULL handoff zip (includes .env files): ${OUT}"
zip -r "${OUT}" "$(basename "${ROOT}")" \
  -x "$(basename "${ROOT}")/.git/*" \
  -x "$(basename "${ROOT}")/**/node_modules/*" \
  -x "$(basename "${ROOT}")/**/.venv/*" \
  -x "$(basename "${ROOT}")/**/__pycache__/*" \
  -x "$(basename "${ROOT}")/**/.pytest_cache/*" \
  -x "$(basename "${ROOT}")/**/dist/*" \
  -x "$(basename "${ROOT}")/**/.env.local" \
  -x "$(basename "${ROOT}")/**/.env.production.local" \
  -x "$(basename "${ROOT}")/**/*.db" \
  -x "$(basename "${ROOT}")/.cursor/*" \
  -x "$(basename "${ROOT}")/.brv/*" \
  -x "$(basename "${ROOT}")/**/.DS_Store" \
  -x "$(basename "${ROOT}")/backend/.venv/*" \
  -x "$(basename "${ROOT}")/frontend/node_modules/*"
ls -lh "${OUT}"
if [[ -f "${ROOT}/backend/.env" ]]; then
  echo "Included: backend/.env (LuvVoice + app config)"
else
  echo "WARNING: backend/.env missing on this machine — client will need LuvVoice token manually."
fi
echo "Done. Client runs: scripts\\windows\\install-all.cmd then start-backend + start-frontend."
