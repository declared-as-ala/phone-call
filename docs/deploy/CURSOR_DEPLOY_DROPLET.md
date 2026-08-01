# Paste into Cursor Composer (Agent) — Deploy to DigitalOcean Droplet

Fill `<<<...>>>` then paste the whole fenced block.

```
Deploy the Outbound IVR / appel-verification project to my DigitalOcean Droplet end-to-end. I approve SSH and network commands.

## Project
Local path: /Users/yasinmokni/Desktop/Projects/Project
README: read first. Deploy scripts: deploy/digitalocean/

## Droplet
- IP: <<<164.92.x.x>>>
- SSH: ssh root@<<<IP>>> (key: ~/.ssh/id_ed25519)
- Region: Frankfurt fra1 (already created)
- Plan: 2GB Ubuntu 24.04
- DO project name: appel-verification

## Client test settings
- DEPLOY_MODE: api-only (mock telephony first — no Asterisk until I say)
- TELEPHONY_PROVIDER: mock in backend/.env
- ADMIN_EMAIL: <<<client@test.com>>>
- ADMIN_PASSWORD: <<<generate strong 16+ char and show me once>>>

## Git
- GITHUB_REPO_URL: <<<https://github.com/USER/repo.git OR "use scp from local path">>>

## Domains (optional — use IP if empty)
- APP_DOMAIN: <<<164.92.x.x>>>
- API_DOMAIN: <<<164.92.x.x>>>

## Rules
- Never commit .env or secrets
- Never change git config / no force push
- Do not use App Platform — Droplet only
- Run commands yourself; show summaries

## Tasks (in order)

### A — Reach server
1. ssh root@IP — verify connection
2. Run: bash deploy/digitalocean/install-server.sh (from repo after clone)

### B — Get code on server at /opt/ivr-project
- If GitHub URL provided: git clone
- Else: scp -r from /Users/yasinmokni/Desktop/Projects/Project root@IP:/opt/ivr-project (exclude node_modules, .venv, *.db)

### C — Backend
1. cp deploy/digitalocean/env/backend.env.template → backend/.env OR cp .env.example and edit
2. Set APP_ENV=production, TELEPHONY_PROVIDER=mock, JWT_SECRET_KEY=$(openssl rand -hex 32)
3. python3 -m venv .venv, pip install -r requirements.txt, alembic upgrade head
4. create_admin.py with ADMIN_EMAIL and ADMIN_PASSWORD

### D — Frontend
1. VITE_API_BASE_URL=http://APP_DOMAIN, VITE_WS_URL=ws://APP_DOMAIN/ws (or wss if HTTPS later)
2. VITE_ENABLE_MOBILE_SIMULATOR=false
3. npm ci && npm run build

### E — Nginx + systemd
1. For single-IP test: one nginx server block serving frontend/dist AND proxying /api and /ws to 127.0.0.1:8000
2. Or run deploy-remote.sh with APP_DOMAIN=API_DOMAIN=IP and DEPLOY_MODE=api-only
3. systemctl enable/start ivr-backend
4. Skip ivr-ari-bridge when mock mode

### F — Firewall
ufw: 22, 80, 443 open (5060/udp only when Asterisk enabled later)

### G — Verify
- curl http://IP/api/system/runtime (may need auth — also try docs or health)
- curl -I http://IP/
- systemctl status ivr-backend
Report: client URL http://IP, login email, password, what works

### H — Handoff message
Write 3-line message I can send client on Windows (Chrome/Edge, no install).

## If blocked
Ask only for: IP, GitHub URL, admin email, mock vs real calls.

Start now with step A.
```
