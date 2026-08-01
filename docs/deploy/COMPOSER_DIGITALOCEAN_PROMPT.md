# Composer prompt — Deploy IVR / appel téléphonique on DigitalOcean

Copy everything inside the fenced block below and paste it into **Cursor Composer** (Agent mode). Fill in the `<<<PLACEHOLDERS>>>` before sending.

---

```
You are deploying the Outbound IVR verification project to DigitalOcean on a single Ubuntu Droplet with full telephony (FastAPI + React + Asterisk Docker).

## Project (local path on my Mac)
/Users/yasinmokni/Desktop/Projects/Project

Stack:
- backend/ — FastAPI, uvicorn port 8000, Alembic, SQLite default (or Postgres if I provide DATABASE_URL)
- frontend/ — Vite/React, production build in frontend/dist
- infra/sipup/ — docker compose (SIP 5060/udp, RTP 10000-10100/udp, ARI 8088)
- backend/scripts/run_sip_up_ari_bridge.py — separate long-running process
- README.md and docs/runbooks/ — follow for env var names

## My inputs (I will fill these — ask me if any are missing)
- GITHUB_REPO_URL: <<<https://github.com/USER/ivr-project.git>>>
- DROPLET_IP: <<<1.2.3.4>>>
- SSH_USER: <<<root>>>  (or deploy)
- SSH_KEY_PATH: <<<~/.ssh/id_ed25519>>>
- APP_DOMAIN: <<<app.example.com>>>     (dashboard)
- API_DOMAIN: <<<api.example.com>>>     (FastAPI + WebSocket)
- ADMIN_EMAIL: <<<admin@example.com>>>
- ADMIN_PASSWORD: <<<I will type this only in .env on server, never commit>>>
- DEPLOY_MODE: <<<full>>>  (full = Asterisk on Droplet | api-only = no Asterisk, mock or external SIP webhooks only)

Optional (real calls via SIP UP):
- SIPUP_SIP_DOMAIN, SIPUP_SIP_USERNAME, SIPUP_SIP_PASSWORD, SIPUP_OUTBOUND_CALLER_ID
- LUVVOICE_API_TOKEN if using TTS

## Hard rules
- NEVER commit .env, secrets, passwords, or API keys.
- NEVER force-push or change git config.
- Do not use DigitalOcean App Platform for Asterisk — use a Droplet for full mode.
- Match existing project conventions; read README.md before changing app code.
- Create commits only if I explicitly ask.

## Goal
Production-ready deployment on one Droplet:
1. Public HTTPS dashboard at https://APP_DOMAIN
2. API + WebSocket at https://API_DOMAIN (proxied to localhost:8000)
3. Asterisk in Docker (full mode) with firewall ports open
4. systemd services for backend, ARI bridge, and auto-start on reboot
5. Document what I must do manually in DigitalOcean UI (DNS A records, firewall)

## Execute end-to-end (you run commands; I approve SSH/network as needed)

### Phase A — Prepare repository (local Mac)
1. Open project at the path above.
2. Ensure .gitignore excludes: backend/.env, infra/sipup/.env, *.db, node_modules, .venv, frontend/dist.
3. If no remote: help me create GitHub repo and push (ask for gh auth if needed).
4. Add deployment artifacts under `deploy/digitalocean/` (do not break local dev):
   - `deploy/digitalocean/install-server.sh` — apt packages: git, docker.io, docker compose v2, nginx, certbot, python3-venv, nodejs 18+, ufw, ffmpeg
   - `deploy/digitalocean/nginx-api.conf` — reverse proxy API_DOMAIN → 127.0.0.1:8000, WebSocket upgrade for /ws
   - `deploy/digitalocean/nginx-app.conf` — serve frontend/dist, or proxy to static root
   - `deploy/digitalocean/systemd/ivr-backend.service`
   - `deploy/digitalocean/systemd/ivr-ari-bridge.service` (only if DEPLOY_MODE=full)
   - `deploy/digitalocean/env/backend.env.template` and `env/sipup.env.template` (no secrets, placeholders only)
   - `deploy/digitalocean/deploy-remote.sh` — idempotent remote setup: clone/pull, venv, pip, alembic, npm build, copy env templates, enable systemd, docker compose up
   - `deploy/digitalocean/README.md` — operator checklist

### Phase B — DigitalOcean (document steps for me if you cannot use doctl)
1. Instruct me: Create → Droplets → Ubuntu 22.04, 2GB+ RAM, my SSH key, same region as SIP if possible.
2. DNS: A record APP_DOMAIN and API_DOMAIN → DROPLET_IP.
3. Cloud Firewall (if used): TCP 22, 80, 443; UDP 5060; UDP 10000-10100 (or match ASTERISK_RTP_* in .env).

### Phase C — Remote server setup (SSH)
SSH as SSH_USER@DROPLET_IP using SSH_KEY_PATH.

1. Run install-server.sh.
2. Clone GITHUB_REPO_URL to /opt/ivr-project (or pull if exists).
3. Backend:
   - cd /opt/ivr-project/backend
   - python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   - Copy backend/.env.example → .env and set at minimum:
     APP_ENV=production
     TELEPHONY_PROVIDER=sip_up (full) or mock (api-only)
     DATABASE_URL if Postgres provided
     ASTERISK_HOST=127.0.0.1, ASTERISK_PORT=8088, matching ari.conf passwords
     SIPUP_* if using sip_up trunk
     Strong JWT/session secrets (generate random)
   - alembic upgrade head
   - PYTHONPATH=. .venv/bin/python scripts/create_admin.py --email ADMIN_EMAIL --password "<from secure channel>"
4. Asterisk (full mode only):
   - cd /opt/ivr-project/infra/sipup
   - cp .env.example .env — align ASTERISK_PASSWORD / BACKEND_WS_TOKEN / WS_BROADCAST_BRIDGE_TOKEN with backend .env
   - docker compose up -d
   - Verify: docker compose ps, asterisk -rx "pjsip show endpoints" (via docker exec)
5. ARI bridge (full mode):
   - systemd unit loads infra/sipup/.env + runs backend/scripts/run_sip_up_ari_bridge.py from backend venv
6. Frontend:
   - cd /opt/ivr-project/frontend && npm ci && npm run build
   - VITE_API_BASE_URL=https://API_DOMAIN, VITE_WS_URL=wss://API_DOMAIN/ws, VITE_ENABLE_MOBILE_SIMULATOR=false
7. Nginx:
   - Enable site configs for APP_DOMAIN and API_DOMAIN
   - certbot --nginx -d APP_DOMAIN -d API_DOMAIN (non-interactive flags if possible)
8. systemd:
   - Enable and start ivr-backend.service (and ivr-ari-bridge if full)
9. ufw:
   - allow OpenSSH, 80, 443, 5060/udp, 10000:10100/udp (full mode)

### Phase D — Verification (you run and report)
- curl -s https://API_DOMAIN/api/health or equivalent health endpoint
- curl -I https://APP_DOMAIN
- systemctl status ivr-backend ivr-ari-bridge
- docker compose -f /opt/ivr-project/infra/sipup/docker-compose.yml ps
- From my machine: open https://APP_DOMAIN, login with ADMIN_EMAIL, start a test call (mock or real per TELEPHONY_PROVIDER)

### Phase E — Handoff
Deliver a short report:
- URLs (app + api)
- Where .env files live on server
- How to redeploy: `git pull && ./deploy/digitalocean/deploy-remote.sh`
- Rollback: systemctl stop, git checkout previous tag, alembic if needed
- Link to project runbooks: docs/runbooks/asterisk-local-dry-run.md, provider-cutover.md

## If blocked
- Ask me for: GitHub URL, Droplet IP, domain names, SIP UP credentials, whether full or api-only mode.
- Do not guess secrets.

Start with Phase A on my Mac, then Phase C via SSH. Show me each major command output summary.
```

---

## Quick variant (API + UI only, no Asterisk on server)

Set `DEPLOY_MODE=api-only` and in backend `.env` use `TELEPHONY_PROVIDER=mock` or external webhook-only SIP UP without local Docker Asterisk. Skip ARI bridge systemd and UDP firewall rules.
