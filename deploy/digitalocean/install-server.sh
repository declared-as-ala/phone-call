#!/usr/bin/env bash
# One-time DigitalOcean Droplet setup (Ubuntu 22.04+). Run as root.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  git curl ca-certificates ufw \
  python3 python3-venv python3-pip \
  nginx certbot python3-certbot-nginx \
  docker.io docker-compose-v2 \
  ffmpeg

# Node.js 20 LTS (Vite build)
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

systemctl enable --now docker

# Dedicated unprivileged system account for both app services (SEC-4). Neither
# ivr-backend.service nor ivr-ari-bridge.service should run as root — only the
# ARI bridge's `docker exec`/`docker cp` calls (see sip_up_ari_bridge.py) need
# elevated Docker access, granted via docker-group membership, not root.
if ! id -u ivr >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin ivr
fi
usermod -aG docker ivr

ufw --force reset || true
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5060/udp
ufw allow 10000:10100/udp
ufw --force enable

echo "install-server.sh done. Node: $(node -v) Python: $(python3 --version) Docker: $(docker --version)"
