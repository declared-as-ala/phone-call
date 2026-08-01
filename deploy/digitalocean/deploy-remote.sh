#!/usr/bin/env bash
# Idempotent deploy on the Droplet. Run as root from /opt/ivr-project after git clone.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/ivr-project}"
APP_DOMAIN="${APP_DOMAIN:-app.example.com}"
API_DOMAIN="${API_DOMAIN:-api.example.com}"
DEPLOY_MODE="${DEPLOY_MODE:-full}"

cd "$REPO_DIR"
git pull --ff-only

# Backend
cd "$REPO_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip setuptools wheel
.venv/bin/pip install -q -r requirements.txt
if [[ -f .env ]]; then
  set -a && source .env && set +a
fi
.venv/bin/alembic upgrade head

# SEC-4: services run as the unprivileged `ivr` user (see install-server.sh).
# Only the paths the app actually writes to need that ownership — the venv and
# repo code stay root-owned and world-readable, which is sufficient for the
# service to read/execute them under systemd's ProtectSystem=strict.
mkdir -p "$REPO_DIR/.local" "$REPO_DIR/.local/backups"
chown -R ivr:ivr "$REPO_DIR/backend" "$REPO_DIR/.local"
[[ -f "$REPO_DIR/backend/.env" ]] && chmod 600 "$REPO_DIR/backend/.env"
[[ -f "$REPO_DIR/infra/sipup/.env" ]] && chown ivr:ivr "$REPO_DIR/infra/sipup/.env" && chmod 600 "$REPO_DIR/infra/sipup/.env"

# Frontend
cd "$REPO_DIR/frontend"
# Production must not bake localhost API URL — leave VITE_API_BASE_URL unset so the
# built app uses window.location.origin (/api on the same host).
cat > .env.local <<'ENV'
VITE_ENABLE_MOBILE_SIMULATOR=false
ENV
export VITE_ENABLE_MOBILE_SIMULATOR=false
unset VITE_API_BASE_URL VITE_WS_URL
npm ci
npm run build:production

# SIP UP media stack (full mode)
if [[ "$DEPLOY_MODE" == "full" ]]; then
  cd "$REPO_DIR/infra/sipup"
  docker compose up -d
fi

# Nginx
cp "$REPO_DIR/deploy/digitalocean/nginx-api.conf" /etc/nginx/sites-available/ivr-api.conf
cp "$REPO_DIR/deploy/digitalocean/nginx-app.conf" /etc/nginx/sites-available/ivr-app.conf
sed -i "s/__API_DOMAIN__/${API_DOMAIN}/g" /etc/nginx/sites-available/ivr-api.conf
sed -i "s/__APP_DOMAIN__/${APP_DOMAIN}/g" /etc/nginx/sites-available/ivr-app.conf
sed -i "s|__REPO_DIR__|${REPO_DIR}|g" /etc/nginx/sites-available/ivr-app.conf
ln -sf /etc/nginx/sites-available/ivr-api.conf /etc/nginx/sites-enabled/
ln -sf /etc/nginx/sites-available/ivr-app.conf /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# systemd
cp "$REPO_DIR/deploy/digitalocean/systemd/ivr-backend.service" /etc/systemd/system/
sed -i "s|__REPO_DIR__|${REPO_DIR}|g" /etc/systemd/system/ivr-backend.service
systemctl daemon-reload
systemctl enable ivr-backend.service
systemctl restart ivr-backend.service

cp "$REPO_DIR/deploy/digitalocean/systemd/ivr-backup.service" /etc/systemd/system/
cp "$REPO_DIR/deploy/digitalocean/systemd/ivr-backup.timer" /etc/systemd/system/
sed -i "s|__REPO_DIR__|${REPO_DIR}|g" /etc/systemd/system/ivr-backup.service
systemctl daemon-reload
systemctl enable --now ivr-backup.timer

if [[ "$DEPLOY_MODE" == "full" ]]; then
  cp "$REPO_DIR/deploy/digitalocean/systemd/ivr-ari-bridge.service" /etc/systemd/system/
  sed -i "s|__REPO_DIR__|${REPO_DIR}|g" /etc/systemd/system/ivr-ari-bridge.service
  systemctl enable ivr-ari-bridge.service
  systemctl restart ivr-ari-bridge.service
else
  systemctl disable --now ivr-ari-bridge.service 2>/dev/null || true
fi

echo "Deploy finished. API: https://${API_DOMAIN}/api/system/runtime  App: https://${APP_DOMAIN}"
