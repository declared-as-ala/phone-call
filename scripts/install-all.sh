#!/usr/bin/env bash
# Install backend (venv + pip + DB) and frontend (npm) in one run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd python3
need_cmd npm

echo "==> Backend: venv + pip + alembic"
cd "${ROOT}/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created backend/.env from .env.example — edit TELEPHONY_PROVIDER and secrets."
fi
PYTHONPATH=. python -m alembic upgrade head

echo "==> Frontend: npm install"
cd "${ROOT}/frontend"
npm install

echo ""
echo "Install complete."
echo "  1) Edit backend/.env if needed"
echo "  2) Create admin: cd backend && source .venv/bin/activate && python scripts/create_admin.py --email YOU --password 'YourPass123!'"
echo "  3) Start: bash scripts/run_backend.sh  +  bash scripts/run_frontend.sh"
echo "     Windows: scripts\\windows\\start-backend.cmd + start-frontend.cmd"
echo "  4) Open http://localhost:5173"
