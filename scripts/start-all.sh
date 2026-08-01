#!/usr/bin/env bash
# Start full SIP UP stack: Asterisk Docker + backend + ARI bridge + frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/.local/logs"
mkdir -p "${LOG_DIR}"

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "Stopping process(es) on port ${port}: ${pids}"
    kill ${pids} 2>/dev/null || true
    sleep 1
  fi
}

echo "==> Asterisk (Docker)"
cd "${ROOT}/infra/sipup"
mkdir -p "${ROOT}/.local/asterisk-ivr/dyn"
if [[ ! -f "${ROOT}/.local/asterisk-ivr/consent.wav" ]]; then
  echo "    generating static IVR prompts (first run)…"
  bash "${ROOT}/infra/sipup/scripts/generate-local-prompts.sh" || true
fi
if docker ps -a --format '{{.Names}}' | grep -qx 'ivr-asterisk-dev'; then
  docker compose up -d --force-recreate asterisk >/dev/null 2>&1 || docker start ivr-asterisk-dev >/dev/null 2>&1 || true
else
  docker compose up -d
fi
sleep 2

echo "==> Backend (port 8000)"
stop_port 8000
nohup bash "${ROOT}/scripts/run_backend.sh" >"${LOG_DIR}/backend.log" 2>&1 &
echo "    log: ${LOG_DIR}/backend.log"

echo "==> SIP UP ARI bridge"
pkill -f "run_sip_up_ari_bridge.py" 2>/dev/null || true
sleep 1
nohup bash "${ROOT}/scripts/run_sipup_bridge.sh" >"${LOG_DIR}/sipup-bridge.log" 2>&1 &
echo "    log: ${LOG_DIR}/sipup-bridge.log"

echo "==> Frontend (port 5173)"
stop_port 5173
nohup bash "${ROOT}/scripts/run_frontend.sh" >"${LOG_DIR}/frontend.log" 2>&1 &
echo "    log: ${LOG_DIR}/frontend.log"

sleep 4

echo ""
echo "==> Health checks"
if curl -sf -o /dev/null "http://127.0.0.1:8000/docs"; then
  echo "  backend   OK  http://127.0.0.1:8000"
else
  echo "  backend   FAIL — see ${LOG_DIR}/backend.log"
fi
if curl -sf -o /dev/null "http://localhost:5173/"; then
  echo "  frontend  OK  http://localhost:5173"
else
  echo "  frontend  FAIL — see ${LOG_DIR}/frontend.log"
fi
if docker exec ivr-asterisk-dev asterisk -rx "pjsip show registrations" 2>/dev/null | grep -q Registered; then
  echo "  sip trunk OK  sip-up-registration Registered"
else
  echo "  sip trunk FAIL — run: docker exec ivr-asterisk-dev asterisk -rx 'pjsip show registrations'"
fi
if pgrep -f "run_sip_up_ari_bridge.py" >/dev/null; then
  echo "  bridge    OK  run_sip_up_ari_bridge.py"
else
  echo "  bridge    FAIL — see ${LOG_DIR}/sipup-bridge.log"
fi

PUBLIC_IP="$(curl -s --max-time 5 ifconfig.me 2>/dev/null || true)"
echo ""
echo "Open http://localhost:5173"
if [[ -n "${PUBLIC_IP}" ]]; then
  echo "Public IP (whitelist in SIP UP dashboard if outbound gets 403): ${PUBLIC_IP}"
fi
