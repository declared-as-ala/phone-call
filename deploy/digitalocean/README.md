# DigitalOcean Droplet deployment

Used by the Composer prompt in [`docs/deploy/COMPOSER_DIGITALOCEAN_PROMPT.md`](../../docs/deploy/COMPOSER_DIGITALOCEAN_PROMPT.md).

## Operator checklist (you)

1. Create a **Droplet** (Ubuntu 22.04, 2 GB+ RAM) and add your SSH key.
2. Point DNS **A records** at the Droplet IP:
   - `app.yourdomain.com` → dashboard
   - `api.yourdomain.com` → API + WebSocket
3. Open firewall: TCP 22, 80, 443; for real calls also UDP **5060** and **10000–10100**.
4. Fill placeholders in the Composer prompt and run deploy.

## Files

| File | Purpose |
|------|---------|
| `install-server.sh` | One-time OS packages on the Droplet |
| `deploy-remote.sh` | Pull repo, build, restart services |
| `nginx-*.conf` | Nginx site templates |
| `systemd/*` | Backend, ARI bridge, and scheduled SQLite backup units |
| `env/*.template` | Non-secret env templates |

## After deploy

```bash
ssh root@YOUR_IP 'sudo systemctl status ivr-backend ivr-ari-bridge --no-pager'
ssh root@YOUR_IP 'sudo systemctl status ivr-backup.timer --no-pager'
```

Redeploy:

```bash
ssh root@YOUR_IP 'sudo /opt/ivr-project/deploy/digitalocean/deploy-remote.sh'
```

## Service account (SEC-4)

Both `ivr-backend.service` and `ivr-ari-bridge.service` run as a dedicated, unprivileged
system user (`ivr`), not root — created by `install-server.sh`. `install-server.sh` and
`deploy-remote.sh` still run as root (they manage systemd units, nginx, and package
installs, which do need root), but the long-running application processes themselves do
not.

**Smoke-test this after the first deploy to a new droplet** (systemd sandboxing directives
are easy to get subtly wrong and the failure mode is a service that silently can't write
its cache or reach Docker):

```bash
ssh root@YOUR_IP 'sudo systemctl status ivr-backend ivr-ari-bridge --no-pager'
ssh root@YOUR_IP 'sudo -u ivr touch /opt/ivr-project/.local/tts-cache/.write-test && echo OK'
ssh root@YOUR_IP 'sudo -u ivr docker ps >/dev/null && echo "docker group OK"'
# Then place one real test call end-to-end and confirm TTS prompts play and the callee's
# DTMF reaches the dashboard (see docs/runbooks/sipup-local-dry-run.md for the full flow).
```

If `ivr-ari-bridge.service` fails with `docker: permission denied`, the `ivr` user's
`docker` group membership hasn't taken effect yet — `systemctl restart ivr-ari-bridge`
after `usermod -aG docker ivr` (group membership is read at login/process-start time).
