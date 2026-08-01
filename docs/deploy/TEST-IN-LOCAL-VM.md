# Test deployment in a local Ubuntu VM (before DigitalOcean)

Simulates the same Linux server you will use on a Droplet. Your Mac runs the VM; you open the app in a browser using the VM’s IP.

## 1. Install a hypervisor (Mac)

| Mac | Tool |
|-----|------|
| Apple Silicon (M1/M2/M3) | [UTM](https://mac.getutm.app/) (free) |
| Intel Mac | UTM or [VirtualBox](https://www.virtualbox.org/) |

## 2. Create the VM

| Setting | Value |
|---------|--------|
| OS | Ubuntu Server **24.04 LTS** (ARM64 on Apple Silicon, AMD64 on Intel) |
| RAM | **2048 MB** (same as $12 Droplet) |
| Disk | **25–50 GB** |
| Network | **Bridged** (so you get an IP like `192.168.x.x` on your Wi‑Fi) |

During Ubuntu install: enable **OpenSSH server**, create user e.g. `deploy` with password (or use SSH keys).

## 3. Copy project into the VM

**Option A — Git (best)**  
Push project to GitHub from Mac, then in VM:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/YOUR_USER/ivr-project.git /opt/ivr-project
```

**Option B — Shared folder**  
UTM/VirtualBox shared folder → copy `Project` to `/opt/ivr-project`

**Option C — From Mac (scp)**  
```bash
scp -r "/Users/yasinmokni/Desktop/Projects/Project" deploy@VM_IP:/tmp/ivr-project
# In VM: sudo mv /tmp/ivr-project /opt/ivr-project
```

## 4. Install stack (same as Droplet)

In the VM as root:

```bash
cd /opt/ivr-project
sudo bash deploy/digitalocean/install-server.sh
```

## 5. Client-test config (mock calls, no Asterisk yet)

```bash
cd /opt/ivr-project/backend
sudo cp .env.example .env
sudo nano .env
```

Set:

```env
APP_ENV=production
TELEPHONY_PROVIDER=mock
JWT_SECRET_KEY=<openssl rand -hex 32>
```

```bash
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo .venv/bin/alembic upgrade head
sudo env PYTHONPATH=. .venv/bin/python scripts/create_admin.py \
  --email client@test.com --password 'TestClient123!@#'
```

Find VM IP: `ip -4 addr show` → e.g. `192.168.1.50`

```bash
cd /opt/ivr-project/frontend
export VITE_API_BASE_URL=http://192.168.1.50
export VITE_WS_URL=ws://192.168.1.50/ws
export VITE_ENABLE_MOBILE_SIMULATOR=false
npm ci && npm run build
```

Deploy nginx + backend (mock mode, no ARI bridge):

```bash
export APP_DOMAIN=192.168.1.50
export API_DOMAIN=192.168.1.50
export DEPLOY_MODE=api-only
export REPO_DIR=/opt/ivr-project
sudo -E bash deploy/digitalocean/deploy-remote.sh
```

Edit nginx if needed: both domains are the same IP; `deploy-remote.sh` uses separate server_name blocks — for VM test, use the manual nginx block in README or single combined config.

**Quick manual run (two terminals):**

Terminal 1:
```bash
cd /opt/ivr-project/backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal 2: use `deploy/digitalocean/nginx-app.conf` + proxy `/api` and `/ws` to 8000 (see main README).

## 6. Test from Mac (simulates client on Windows)

Browser on Mac: `http://192.168.1.50`  
Login: `client@test.com` / `TestClient123!@#`

Another device on same Wi‑Fi (phone/PC): same URL — like client testing.

API check:
```bash
curl http://192.168.1.50:8000/api/system/runtime
```

## 7. Full telephony in VM (optional, step 2)

```bash
cd /opt/ivr-project/infra/sipup
cp .env.example .env
# fill SIP UP / ARI passwords aligned with backend/.env
docker compose up -d
```

Set `TELEPHONY_PROVIDER=sip_up`, restart backend, start ARI bridge systemd or manual script.

## 8. When VM works → DigitalOcean

Same commands on Droplet with public IP + domain. No code changes.

## Faster path (skip VM)

On Mac only (already documented in README):

```bash
# terminal 1: backend
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# terminal 2: frontend
cd frontend && npm run dev

# optional: asterisk
cd infra/sipup && docker compose up -d
```

Use VM when you want to prove **Linux + nginx + systemd** before paying for DO.
