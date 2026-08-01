#!/usr/bin/env bash
# Set LUVVOICE_API_TOKEN in backend/.env (Mac / Git Bash / Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/backend/.env"
TOKEN="${1:-}"

if [[ -z "${TOKEN}" ]]; then
  echo "Usage: bash scripts/configure-luvvoice.sh YOUR_LUVVOICE_TOKEN"
  echo "Get token: LuvVoice Dashboard → API Tokens (Plus plan+)"
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT}/backend/.env.example" "${ENV_FILE}"
  echo "Created backend/.env from .env.example"
fi

python3 - <<PY
from pathlib import Path
p = Path("${ENV_FILE}")
token = """${TOKEN}"""
lines = p.read_text(encoding="utf-8").splitlines()
lines = [ln for ln in lines if not ln.strip().startswith("LUVVOICE_API_TOKEN=") and not ln.strip().startswith("LUVVOICE_DEFAULT_VOICE_ID=")]
lines.append(f"LUVVOICE_API_TOKEN={token}")
lines.append("LUVVOICE_DEFAULT_VOICE_ID=voice-001")
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("OK — LuvVoice configured in backend/.env")
print("Restart backend: bash scripts/run_backend.sh")
PY
