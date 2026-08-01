#!/usr/bin/env bash
# Start FastAPI backend on port 8000 with optional SIP UP stack env merged in.
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
PYTHONPATH=. exec python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
