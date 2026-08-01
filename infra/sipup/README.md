# Local Asterisk development (optional)

This stack is used for the Narayana real-call path. The FastAPI app selects outbound behavior with `TELEPHONY_PROVIDER`: use `mock` for local-only simulation, or `asterisk` to originate real calls through SIP UP/Narayana and receive ARI events.

## Goals

- Run Asterisk in Docker with **PJSIP** (softphone registration) and **ARI** over HTTP.
- Keep **all secrets in environment variables or local files** that are **gitignored**—only `*.example` files are committed.
- Document how Asterisk (or a small ARI companion) calls the backend **`POST /api/telephony/events`**.

## Layout

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | Asterisk container, ports, volumes |
| `config/*.example` | Safe templates—copy to `config/*.conf` and edit |
| `.env.example` | Port bindings / documentation hints—copy to `.env` |
| `scripts/curl-telephony-event.example.sh` | Example webhook POSTs from the host |

## Quick start

1. Copy examples (do **not** commit the copies):

   ```bash
   cd infra/sipup
   cp config/asterisk.conf.example config/asterisk.conf
   cp config/pjsip.conf.example config/pjsip.conf
   cp config/extensions.conf.example config/extensions.conf
   cp config/http.conf.example config/http.conf
   cp config/ari.conf.example config/ari.conf
   cp config/modules.conf.example config/modules.conf
   cp .env.example .env
   ```

2. Edit **`config/ari.conf`**: set a **strong random** `password=` for the user section (the section name, e.g. `[ari-dev-user]`, is the **ARI username**).

3. Edit **`config/pjsip.conf`**: set `REPLACE_SIP_USER` / `REPLACE_SIP_PASSWORD` for your softphone. If you are using a provider trunk, render the `${NARAYANA_*}` placeholders from local environment variables or replace them only in your uncommitted local copy.

4. Start:

   ```bash
   docker compose up -d
   docker compose logs -f asterisk
   ```

5. For real-call audio prompts on macOS, generate local static WAV files:

   ```bash
   bash scripts/generate-local-prompts.sh
   ```

6. ARI base URL (typical): `http://localhost:${ASTERISK_HTTP_BIND:-8088}/asterisk/ari` with HTTP basic auth (**username** = ARI section name, **password** = from `ari.conf`).

### Environment variables (documentation / compose)

| Variable | Role |
|----------|------|
| `ASTERISK_SIP_BIND`, `ASTERISK_HTTP_BIND`, `ASTERISK_RTP_*` | Host port mapping in `docker-compose.yml` |
| `ASTERISK_ARI_USER`, `ASTERISK_ARI_PASSWORD` | **Documentary** in compose—Asterisk still reads **`ari.conf`**; align values manually |
| `ASTERISK_CONTEXT` | Should match dialplan context (example: **`ivr-local-dev`**) |
| `ASTERISK_ENDPOINT` | Optional label for your PJSIP endpoint object name in `pjsip.conf` |

Never commit `.env` or non-example `config/*.conf` with real passwords.

## Using Narayana SIP provider

The client provided access to a Narayana SIP/WebRTC provider dashboard. Treat it as a generic SIP registration/trunk behind Asterisk, **not** as a Twilio-like REST API. Real calls should be originated through SIP UP using Narayana SIP credentials, while the FastAPI app keeps the existing IVR state machine, masking, and admin approval flow.

Keep the backend in Asterisk mode with:

```bash
TELEPHONY_PROVIDER=sip_up
```

Do **not** store Narayana credentials in source code or committed config. Use local environment variables, a local `.env`, or deployment secrets. The safe example variables are:

```bash
APP_ENV=development
TELEPHONY_PROVIDER=sip_up
NARAYANA_SIP_DOMAIN=rdx.narayana.im
NARAYANA_SIP_USERNAME=372810444412235
NARAYANA_SIP_PASSWORD=
NARAYANA_SIP_PORT=5061
NARAYANA_SIP_TRANSPORT=tls
NARAYANA_DTMF_MODE=rfc4733
NARAYANA_OUTBOUND_CALLER_ID=18009359935
NARAYANA_DIAL_PREFIX=
ASTERISK_HOST=localhost
ASTERISK_PORT=8088
ASTERISK_USERNAME=
ASTERISK_PASSWORD=
ASTERISK_CONTEXT=ivr-outbound
ASTERISK_ENDPOINT=narayana-trunk
ASTERISK_ARI_APP=ivr-bridge
ASTERISK_ARI_SUBSCRIBE_ALL=true
BACKEND_TELEPHONY_EVENTS_URL=http://127.0.0.1:8000/api/telephony/events
```

Values the developer must copy from the Narayana dashboard:

- SIP domain / registrar / proxy → `NARAYANA_SIP_DOMAIN` (observed as `rdx.narayana.im`)
- SIP account username or auth user → `NARAYANA_SIP_USERNAME`
- SIP account password / secret → `NARAYANA_SIP_PASSWORD`
- SIP port → `NARAYANA_SIP_PORT` (Narayana recommends TLS first, so use `5061` by default)
- Transport → `NARAYANA_SIP_TRANSPORT` (Narayana recommends `tls`; fall back only after provider confirmation)
- DTMF mode → `NARAYANA_DTMF_MODE` (`rfc4733` / RFC2833-compatible for IVR keypad digits)
- Outbound caller ID / CLI / assigned DID → `NARAYANA_OUTBOUND_CALLER_ID`
- Dial prefix or number format → `NARAYANA_DIAL_PREFIX` if Narayana requires a prefix, or leave blank and dial E.164/national format as confirmed by Narayana
- ARI credentials and endpoint names → `ASTERISK_USERNAME`, `ASTERISK_PASSWORD`, `ASTERISK_ENDPOINT`, and matching values in `config/ari.conf` / `config/pjsip.conf`

### Observed Narayana SIP device values

The Narayana dashboard currently shows these values for the test SIP device:

| Field | Observed value | Notes |
|-------|----------------|-------|
| SIP Login | `372810444412235` | Use as `NARAYANA_SIP_USERNAME` only if Narayana confirms it is also the auth username. |
| SIP Server | `rdx.narayana.im` | Use as `NARAYANA_SIP_DOMAIN`. |
| Caller ID | `18009359935` | Use as `NARAYANA_OUTBOUND_CALLER_ID` if outbound CLI is allowed. |
| Encryption | `DTLS-SRTP` | Narayana recommends TLS for SIP signaling. Confirm whether DTLS-SRTP means WebRTC-only media or whether SIP TLS/SRTP is supported by Asterisk. |
| IP Auth | `192.168.1.1` | This is a private placeholder-looking IP. If IP authentication is required, replace it in Narayana with the public Asterisk server IP. |
| PIN Code | Present in UI | Do **not** treat the PIN as the SIP password unless Narayana explicitly confirms it. |

The current default Asterisk template attempts TLS registration on port 5061. DTLS-SRTP/WebRTC encryption may require additional Asterisk TLS/SRTP or WebRTC endpoint configuration beyond this basic SIP TLS registration template.

The `config/pjsip.conf.example` file includes a provider trunk template:

```text
narayana-auth
narayana-aor
narayana-registration
narayana-identify
narayana-trunk
```

The sample includes endpoint, auth, AOR, registration, optional identify, RFC4733 DTMF mode, and outbound auth. Asterisk does not automatically substitute shell environment variables inside the committed `.example` file. Copy the example files, keep the copies uncommitted, then render placeholders locally. One simple local workflow:

```bash
cd infra/sipup
cp .env.example .env
# Fill only your local .env with the real Narayana username/password/caller ID.
set -a
source .env
set +a
envsubst < config/pjsip.conf.example > config/pjsip.conf
```

After rendering, confirm `config/pjsip.conf` contains no blank required provider values, then start Asterisk:

```bash
docker compose up -d
docker compose logs -f asterisk
docker compose exec asterisk asterisk -rx "pjsip show registrations"
docker compose exec asterisk asterisk -rx "pjsip show endpoints"
```

For outbound calls, the ARI/dialplan side should dial through the provider endpoint using a destination number in the format Narayana expects. The sample `extensions.conf.example` includes:

```text
Dial(PJSIP/${NARAYANA_DIAL_PREFIX}${EXTEN}@narayana-trunk,60)
```

If calls fail with provider-side rejection, confirm whether Narayana wants E.164 (`+216...`), digits only (`216...`), national format, or a prefix before the destination.

Registration troubleshooting:

- `Rejected` usually means wrong auth username/password, wrong transport, SIP account not enabled, or IP whitelist/IP Auth mismatch.
- If TLS 5061 is rejected, test the same credentials in Zoiper/Linphone using TLS and ask Narayana whether WebRTC/DTLS-SRTP-only mode or IP authentication is required.
- Do not proceed to dashboard real calls until `pjsip show registrations` shows `Registered`.

Keep IVR behavior unchanged: Asterisk/provider integration only transports the call and DTMF events. The FastAPI backend still owns the 6-digit code state, pending admin verification, approval/rejection, and webhook handling.

### ARI event bridge

When `TELEPHONY_PROVIDER=sip_up`, the backend originates calls through ARI and passes `CALL_ID` / `__CALL_ID` channel variables. Run the bridge process alongside the backend so live Asterisk events are forwarded to the existing webhook contract:

```bash
cd backend
source .venv/bin/activate
export TELEPHONY_PROVIDER=sip_up
export ASTERISK_HOST=localhost
export ASTERISK_PORT=8088
export ASTERISK_USERNAME=<ari-user>
export ASTERISK_PASSWORD=<ari-password>
export ASTERISK_CONTEXT=ivr-outbound
export ASTERISK_ENDPOINT=narayana-trunk
export ASTERISK_ARI_APP=ivr-bridge
export BACKEND_TELEPHONY_EVENTS_URL=http://127.0.0.1:8000/api/telephony/events
python scripts/run_sip_up_ari_bridge.py
```

The bridge connects to the configured ARI events path, usually `ws://<ASTERISK_HOST>:<ASTERISK_PORT>/asterisk/ari/events`, listens for `StasisStart`, answered `ChannelStateChange`, `ChannelDtmfReceived`, `ChannelHangupRequest`, `StasisEnd`, and failed `Dial`/destroy events, then posts:

```json
{
  "provider": "sip_up",
  "provider_call_id": "<asterisk-channel-id>",
  "provider_event_id": "<deterministic-id>",
  "call_id": "<backend-call-session-uuid>",
  "event_type": "ANSWERED | DTMF | HANGUP | FAILED",
  "digit": "optional for DTMF"
}
```

Do not log ARI passwords or SIP credentials. If the ARI event does not carry `CALL_ID`, the bridge tries to read `CALL_ID` / `__CALL_ID__` from the Asterisk channel variable API before forwarding.

Safety notes:

- Never commit SIP credentials, rendered `pjsip.conf`, or local `.env` values.
- Put real credentials only in local `.env`, deployment secrets, or a secret manager.
- Use one test phone number first and keep `MAX_CALLS_PER_PHONE_PER_DAY` low during testing.
- Do not collect third-party OTPs or external credentials; only the client’s official verification code is in scope.
- Keep masking/security behavior unchanged: event messages stay safe, and sensitive buffers remain encrypted at rest.

## Softphone (Zoiper / Linphone)

1. Create a **SIP account** pointing at your host IP (or `127.0.0.1` if the phone runs on the same machine as Docker).
2. **Username / password**: same as `username=` / `password=` in **`pjsip.conf`** (`softphone-auth`).
3. **Domain / server**: host running Docker; **port** `5060` UDP (or the value of `ASTERISK_SIP_BIND`).
4. Place a test call to extension **`100`** (see `extensions.conf.example`) once registered—context **`ivr-local-dev`**.

## Backend webhook: `POST /api/telephony/events`

The FastAPI route accepts JSON such as:

```json
{
  "provider": "sip_up",
  "call_id": "<UUID from POST /api/calls/start>",
  "event_type": "ANSWERED | DTMF | HANGUP | FAILED",
  "digit": "optional single DTMF 0-9 for DTMF",
  "provider_call_id": "optional Asterisk channel uniqueid / linkedid",
  "provider_event_id": "optional stable id for this delivery; replays return duplicate_ignored",
  "raw_payload": { "source": "ari", "channel": "..." }
}
```

Use a **unique** `provider_event_id` per ARI/AMI event (e.g. channel id + sequence) so network retries do not double-apply DTMF or verification attempts.

**`call_id`** must be the **`call_id`** returned when your dashboard (or API client) starts a session. In a full integration, set a channel variable from ARI when the outbound call is created (e.g. `StasisStart` argument) so your Stasis application always knows which UUID to send.

### Recommended integration pattern

- **ARI (HTTP + WebSocket)** is the usual way to subscribe to **DTMF**, **channel state**, and drive playback. AMI is optional; an example **`manager.conf.example`** is included if you prefer AMI tooling.
- A small **Stasis** application (Node, Python, etc.) should:
  1. Originate or handle the inbound leg.
  2. On answer → `POST` **`ANSWERED`** (or rely on your app’s existing mock timing—keep one source of truth).
  3. On each DTMF → `POST` **`DTMF`** with **`digit`** (the backend buffers per-digit for verification).
  4. On hangup / error → **`HANGUP`** or **`FAILED`**.

Plain **dialplan** cannot emit rich JSON easily; use **`scripts/curl-telephony-event.example.sh`** from the host for manual tests, or **`func_curl` / AGI** if you embed HTTP from dialplan (not shown here—prefer ARI for maintainability).

### Reachability from Docker

The compose file adds **`host.docker.internal:host-gateway`** so containers can reach a FastAPI process on the host:

```text
http://host.docker.internal:8000/api/telephony/events
```

On pure Linux Docker, if that alias is missing, use the docker bridge IP of the host (often `172.17.0.1`) or run the backend in the same Compose project and use the service name.

## Example local call flow (high level)

1. **Start session** via `POST /api/calls/start` → obtain **`call_id`** (UUID).
2. **SIP** softphone registers to Asterisk (`pjsip.conf`).
3. **Dial** extension `100` → dialplan **answers**, plays **`beep`** as a **consent placeholder** (replace with a real sound under `/var/lib/asterisk/sounds`).
4. **`Read()`** collects a **consent digit**, then up to **6 digits** for the official verification code (dialplan collects a string; your ARI integration should still send **per-digit** `DTMF` events if you want parity with the mock webhook).
5. **Stasis / curl** sends events to **`/api/telephony/events`** as described above.

## Troubleshooting

### SIP registration fails

- Confirm **UDP 5060** is not blocked; try **TCP** if your client supports it (compose exposes both).
- **Username/password** must match `auth` in `pjsip.conf`.
- If the phone is on another machine, use the **LAN IP** of the Docker host as the registrar, not `127.0.0.1`.
- Check `docker compose logs` and run inside the container: `asterisk -rx "pjsip show endpoints"`.

### One-way audio / NAT

- Set **`external_media_address`** and **`external_signaling_address`** on the **transport** (or endpoint) to your **public or LAN** address seen by the remote party.
- Keep **`direct_media = no`** for early media debugging.
- Open the **RTP port range** mapped in `docker-compose.yml`; expand the range if you run multiple calls.
- Quick check during a live call: `docker exec ivr-asterisk-dev asterisk -rx "pjsip show channelstats"` — **Receive Count must be > 0** for RFC4733 audio/DTMF return path.
- On Windows + Docker Desktop, run elevated: `.\scripts\open-rtp-firewall.ps1`, and forward **UDP 10000–10100** on your router to this PC. SIP trunks typically ignore ICE.

### DTMF: RFC4733 (default for SIP UP / PSTN trunks)

- Trunk uses **`dtmf_mode = rfc4733`** (via `SIPUP_DTMF_MODE` in `.env`): keypad digits arrive as RTP telephone-event packets.
- **Inbound RTP must work** — during a live call, `pjsip show channelstats` must show **Receive Count > 0**. If Receive stays `0`, DTMF will never arrive regardless of mode.
- On Windows + Docker Desktop: run elevated `.\scripts\open-rtp-firewall.ps1`, forward **UDP 10000–10100** on your router to this PC, then `.\scripts\verify-rtp.ps1`.
- Pin **`ASTERISK_EXTERNAL_IP`** in `infra/sipup/.env` to your current public IP if your ISP changes it often; re-run `docker compose up -d --force-recreate`.
- After changing DTMF mode: restart Asterisk, restart the ARI bridge, place a new call, press **1**, and look for `DTMF received digit=1` in the bridge log.
- Only set `SIPUP_DTMF_MODE=info` if SIP UP support confirms they send DTMF via SIP INFO (uncommon for PSTN gateways).

### Webhook URL not reachable from the container

- Test from inside the container:  
  `docker compose exec asterisk wget -qO- http://host.docker.internal:8000/docs`  
  (or `curl` if installed).
- Use host firewall rules allowing Docker bridge → host API port.
- Prefer **HTTPS** + proper ingress in real deployments; local dev often uses HTTP on a LAN-only interface.

## Provider Selection

Set `TELEPHONY_PROVIDER=sip_up` on the backend when running the real Narayana flow. In that mode, dashboard call starts originate through SIP UP and the ARI bridge is the source of answer, DTMF, hangup, and failure events.
