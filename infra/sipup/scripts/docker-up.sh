#!/usr/bin/env bash
# Render pjsip.conf from .env, then start/restart the Asterisk stack (SIP UP + Narayana trunks).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing infra/sipup/.env — copy from .env.example and fill SIPUP_* secrets." >&2
  exit 1
fi

python3 scripts/render_pjsip_from_env.py 2>/dev/null || sh scripts/render_pjsip_from_env.sh
exec docker compose up -d "$@"
