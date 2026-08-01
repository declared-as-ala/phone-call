# Runbook: Narayana Real-Call Integration

Use this runbook to validate real outbound calls through the client's Narayana SIP/WebRTC provider. Narayana appears to provide SIP accounts, so this is an **Asterisk SIP registration/trunk integration**, not a Twilio-like REST API integration.

The application business flow must stay unchanged: consent first; pressing `1` moves to **waiting_admin_code_send**, where admins deliver the credential on the client's **official external platform**, confirm **Done — code sent**, then keypad collection gathers the institutional 6-digit value, then pending admin verification, manual approve/reject. Do not bypass masking, encrypted DTMF storage, rate limits, or admin approval.

## Safety Rules

- Never commit SIP credentials, real SIP passwords, rendered `pjsip.conf`, or local `.env` files.
- Put real Narayana credentials only in local `.env`, deployment secrets, or a secret manager.
- Start with one internal test phone number only.
- Keep call limits low during testing, for example `MAX_CALLS_PER_PHONE_PER_DAY=1` or another small staging value.
- Do not collect third-party OTPs, banking codes, email codes, card numbers, passwords, or external credentials.
- Use only the client’s own official verification code for this IVR flow.

## Local lab startup order (exact)

Narayana trunk may refuse SIP **REGISTER** (for example HTTP **404**) while **IP-auth INVITE / manual originate** still works. Keep **`[narayana-registration]`** commented in **`infra/sipup/config/pjsip.conf`**. Normalize Tunisia national **`56340093`** → **`21656340093`** in the backend when **`NARAYANA_DIAL_FORMAT=e164_no_plus`** and **`NARAYANA_DEFAULT_COUNTRY_CODE=216`**.

**A.** Start SIP UP stack:

```bash
cd infra/sipup
docker compose up -d
```

**B.** Confirm manual call path:

```bash
docker exec ivr-asterisk-dev asterisk -rx "channel originate PJSIP/21656340093@narayana-trunk extension s@ivr-outbound"
```

(Optionally confirm **`ASTERISK_PROMPT_PREROLL_MS=300`** (default in code if unset) in **`infra/sipup/.env`** before starting **`run_sip_up_ari_bridge.py`** so consent audio waits briefly for RTP to settle.)

**C.** Start backend on port **8000**:

```bash
cd backend
source .venv/bin/activate
set -a
source ../infra/sipup/.env
set +a
PYTHONPATH=. python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**D.** Start ARI bridge (separate terminal):

```bash
cd backend
source .venv/bin/activate
set -a
source ../infra/sipup/.env
set +a
python scripts/run_sip_up_ari_bridge.py
```

**E.** Start frontend:

```bash
cd frontend
npm run dev
```

**F.** Open the Vite URL (port may shift if busy):

- `http://localhost:5173` or `http://localhost:5174`

**G.** Dashboard login (**create user first** with `backend/scripts/create_admin.py` when needed):

- `admin@example.com`
- *(your admin password — do not paste into tickets)*

**H.** Start call: Tunisia, phone **`56340093`**. Expected backend originate userpart (**no** `+`, **no** `00`): **`PJSIP/21656340093@narayana-trunk`**.

Shortcuts (executable): `scripts/run_backend.sh`, `scripts/run_sipup_bridge.sh`, `scripts/run_frontend.sh` from the repo root (they `source infra/sipup/.env` without printing it).

Frontend: copy **`frontend/.env.example`** → **`frontend/.env.local`** (see **`VITE_API_BASE_URL`** / **`VITE_WS_URL`**), then **restart** `npm run dev`.

## Required Narayana Values

Collect these from the Narayana dashboard before configuring Asterisk:

| Variable | Required value |
|----------|----------------|
| `NARAYANA_SIP_DOMAIN` | SIP registrar/proxy domain. Observed example: `rdx.narayana.im`. |
| `NARAYANA_SIP_USERNAME` | SIP account username or auth user. |
| `NARAYANA_SIP_PASSWORD` | SIP account password/secret. Store only in secrets/local `.env`. |
| `NARAYANA_SIP_PORT` | SIP port. Narayana recommends TLS first, so use `5061` by default. |
| `NARAYANA_SIP_TRANSPORT` | `tls` by default per Narayana recommendation. Test other transports only after provider confirmation. |
| `NARAYANA_DTMF_MODE` | Use `rfc4733` / RFC2833-compatible RTP telephone-event for keypad digits. |
| `NARAYANA_OUTBOUND_CALLER_ID` | Assigned caller ID / CLI / DID, if required. |
| `NARAYANA_DIAL_PREFIX` | Optional prefix or dial format Narayana requires. Leave blank until confirmed. |

Also prepare the SIP UP media values used by the backend/provider bridge:

```bash
APP_ENV=development
TELEPHONY_PROVIDER=sip_up
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

### Observed Narayana SIP Device Values

The Narayana dashboard currently shows:

- SIP Login: `372810444412235`
- SIP Server: `rdx.narayana.im`
- Caller ID: `18009359935`
- Transport: TLS recommended
- Encryption: `DTLS-SRTP`
- IP Auth: `192.168.1.1` shown in UI, but this is a private placeholder-looking IP and likely must be replaced with the public Asterisk server IP if IP authentication is used.
- PIN Code exists, but should not be treated as the SIP password unless Narayana confirms that explicitly.

Current Asterisk registration result was `Rejected`, meaning Asterisk reached Narayana but Narayana refused authentication/config. The app/backend is not the blocker.

### Before Running a Real Call

Confirm all of the following before using the dashboard for real outbound calls:

- Exact SIP password.
- Whether SIP Login `372810444412235` is also the auth username.
- Required transport: TLS first, or whether UDP/TCP/WebRTC is required instead.
- Whether `DTLS-SRTP` means WebRTC only, or whether SIP TLS/SRTP is supported by Asterisk.
- DTMF mode: RFC4733 or SIP INFO.
- Allowed outbound caller ID, currently observed as `18009359935`.
- Required outbound dial format, for example `+216xxxxxxxx`, `216xxxxxxxx`, or `00216xxxxxxxx`.
- IP whitelist / IP Auth requirements and the correct public Asterisk server IP.

## 1. Test Credentials in Linphone or Zoiper

Before touching Asterisk, validate the Narayana SIP account directly in a softphone.

1. Create a SIP account in Linphone or Zoiper.
2. Set server/domain to `NARAYANA_SIP_DOMAIN`, for example `rdx.narayana.im`.
3. Set username/auth user to `NARAYANA_SIP_USERNAME`.
4. Set password to `NARAYANA_SIP_PASSWORD`.
5. Set port and transport to Narayana’s recommended values first: `5061` and `tls`.
6. Set DTMF to RFC2833/RFC4733 if the softphone exposes the option.
7. Register the account and place one test call to the approved test phone number.

Pass criteria:

- SIP account registers.
- Test call rings the target number.
- Audio works both ways.
- Pressing keypad digits is accepted by the call path, or at least not blocked by the softphone/provider settings.

Do not continue to Asterisk until registration and a basic test call work from the softphone.

## 2. Configure Asterisk

From `infra/sipup`:

```bash
cp .env.example .env
cp config/pjsip.conf.example config/pjsip.conf
cp config/extensions.conf.example config/extensions.conf
cp config/http.conf.example config/http.conf
cp config/ari.conf.example config/ari.conf
cp config/modules.conf.example config/modules.conf
```

Edit only the uncommitted local copies:

- Fill `.env` with Narayana SIP values.
- Set ARI username/password in `config/ari.conf`.
- Render or replace `${NARAYANA_*}` placeholders in `config/pjsip.conf`.
- Confirm `config/extensions.conf` has the `ivr-outbound` context and Narayana dial target.

Example local render workflow:

```bash
set -a
source .env
set +a
envsubst < config/pjsip.conf.example > config/pjsip.conf
envsubst < config/extensions.conf.example > config/extensions.conf
```

Start SIP UP stack:

```bash
docker compose up -d
docker compose logs -f asterisk
```

Verify registration:

```bash
docker compose exec asterisk asterisk -rx "pjsip show registrations"
docker compose exec asterisk asterisk -rx "pjsip show endpoints"
```

The Narayana registration should show registered/reachable before dashboard testing.

## 3. Run Backend in Asterisk Mode

From `backend`:

```bash
source .venv/bin/activate
export APP_ENV=development
export TELEPHONY_PROVIDER=sip_up
export ASTERISK_HOST=localhost
export ASTERISK_PORT=8088
export ASTERISK_USERNAME=<ari-user>
export ASTERISK_PASSWORD=<ari-password>
export ASTERISK_CONTEXT=ivr-outbound
export ASTERISK_ENDPOINT=narayana-trunk
export MAX_CALLS_PER_PHONE_PER_DAY=1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Use deployment secrets instead of shell exports outside local testing.

In a second terminal, run the ARI event bridge:

```bash
cd backend
source .venv/bin/activate
export ASTERISK_HOST=localhost
export ASTERISK_PORT=8088
export ASTERISK_USERNAME=<ari-user>
export ASTERISK_PASSWORD=<ari-password>
export ASTERISK_ARI_APP=ivr-bridge
export ASTERISK_ARI_SUBSCRIBE_ALL=true
export BACKEND_TELEPHONY_EVENTS_URL=http://127.0.0.1:8000/api/telephony/events
# Optional but recommended for admin approve/reject call audio:
# export BACKEND_WS_URL=ws://127.0.0.1:8000/ws
# export BACKEND_WS_TOKEN=<admin-jwt>
python scripts/run_sip_up_ari_bridge.py
```

The bridge connects to SIP UP media WebSocket and translates live events into the existing backend webhook:

| ARI event | Backend event |
|-----------|---------------|
| `StasisStart` with an up channel, or `ChannelStateChange` to `Up` | `ANSWERED` |
| `ChannelDtmfReceived` | `DTMF` with `digit` |
| `ChannelHangupRequest` / `StasisEnd` | `HANGUP` |
| Failed `Dial` / non-normal destroyed channel | `FAILED` |

Every forwarded payload includes `provider="sip_up"`, `provider_call_id`, `provider_event_id`, and `call_id` from Asterisk channel variables. The originate path sets both `CALL_ID` and inherited `__CALL_ID` variables.

### Asterisk prompt audio

Real-call mode does not use browser `speechSynthesis`. The ARI bridge plays static Asterisk sound files on the live channel:

| Prompt key | Default sound name | Spoken text expected in the recording |
|------------|--------------------|----------------------------------------|
| `consent` | `ivr/consent` | `Hello. This is the exam verification system. To continue, press 1. To decline, press 2.` |
| `verification_code` | `ivr/verification-code` | `You received a 6 digit verification code from the official verification system. Please enter it now.` |
| `pending_admin` | `ivr/pending-admin` | `Please wait while the administrator verifies your code.` |
| `approved` | `ivr/approved` | `Approved. Thank you.` |
| `rejected` | `ivr/rejected` | `Code not verified. Please try again.` |
| `failed` | `ivr/failed` | `Verification failed. Please contact the administration.` |
| `declined` | `ivr/declined` | `Verification declined. Goodbye.` |

Place prompt recordings under Asterisk sounds, for example `/var/lib/asterisk/sounds/ivr/consent.wav`, or override names with `ASTERISK_PROMPT_*` env vars. Dynamic name/university audio requires a local TTS/audio generation step that is not implemented here; use the generic consent prompt recording until that exists. Do not use paid APIs or browser speech for the real-call test.

On macOS, generate and install generic local prompt files with:

```bash
cd infra/sipup
bash scripts/generate-local-prompts.sh
```

## 4. Start One Dashboard Test Call

1. Start the frontend with `npm run dev`.
2. Sign in as an admin.
3. Start one verification call to the approved test phone number.
4. Confirm Asterisk originates through `narayana-trunk`.
5. Confirm the phone rings.
6. Answer the call and verify the dashboard event stream receives answer/ringing state from the SIP UP bridge.

With `TELEPHONY_PROVIDER=sip_up`, `POST /api/calls/start` originates through SIP UP. The mock provider and mobile simulator do not emit answer/DTMF/hangup events in this mode; real events come from the ARI bridge.

## 5. Verify IVR Behavior

Complete the happy path:

1. Recipient answers the real call.
2. Recipient presses `1` to consent.
3. Institution staff sends the verification credential externally (Narayana/console/SMS/other client-owned channel—not sent by our stack). Operators click **Done — code sent** in the dashboard.
4. Callee hears the scripted keypad instruction (`code_sent_prompt`); Recipient enters the 6-digit official verification code using DTMF.
5. Dashboard reaches pending admin verification.
6. Admin sees the submitted code in the admin review panel; activity logs remain masked.
7. Admin clicks approve.
8. Dashboard emits admin approval and verification success.
9. Call ends cleanly.

Also test negative paths:

- Recipient presses `2` to decline.
- Recipient hangs up before consent.
- Admin rejects once, recipient retries, then admin approves.
- Wrong/rejected code reaches max attempts and fails cleanly.

For each case, verify:

- Event stream order is correct.
- DTMF `1` / `2` and all 6 code digits arrive.
- Pending admin verification appears before any success.
- Admin approve/reject remains manual.
- Masking/security behavior remains unchanged for persisted events and logs.

## 6. Troubleshooting

### Registration Failed

- Confirm `NARAYANA_SIP_DOMAIN`, port, and transport match the dashboard.
- Check DNS resolution from inside the Asterisk container.
- Run `pjsip show registrations` and inspect the registration status.
- Try the same credentials in Linphone/Zoiper again to isolate provider vs Asterisk config.
- `Rejected` usually means wrong auth username/password, wrong transport, SIP account not enabled, or IP whitelist/IP Auth mismatch.
- If TLS 5061 fails, test the same credentials in Zoiper/Linphone using TLS before changing Asterisk.
- Ask Narayana whether DTLS-SRTP means WebRTC-only media or whether SIP TLS/SRTP is supported by Asterisk.
- Do not proceed to dashboard real calls until `pjsip show registrations` shows `Registered`.

#### Recovering after `Maximum retries reached`

If `pjsip show registrations` shows `Rejected` and `/var/log/asterisk/pjsip-debug.log`
contains `Maximum retries reached when attempting outbound registration`, PJSIP has
permanently stopped retrying for this `outbound_registration` object until reload.
Common cause: a transient TLS / "no response" stretch from Narayana (e.g. while you
were testing the same SIP user on the Narayana web softphone) exhausted the retry
counter.

To force a fresh REGISTER without restarting the whole container:

```bash
docker exec ivr-asterisk-dev asterisk -rx "pjsip set logger on"
docker exec ivr-asterisk-dev asterisk -rx "module reload res_pjsip.so"
sleep 5
docker exec ivr-asterisk-dev asterisk -rx "pjsip show registrations"
```

You should see a `401 Unauthorized` followed by a `200 OK` in the SIP trace and the
status flip to `Registered (exp. ~7600s)`. If it still fails, log into the Narayana
portal and confirm the SIP account is not in use elsewhere (web softphone) and that
the public IP shown by `curl -s ifconfig.me` is whitelisted on the SIP user.

### 401 Unauthorized

- Check `NARAYANA_SIP_USERNAME` and `NARAYANA_SIP_PASSWORD`.
- Some providers require separate auth username and display/caller ID values. Confirm with Narayana.
- Confirm `client_uri`, `server_uri`, `contact_user`, and `from_user` match provider expectations.

### No Audio or One-Way Audio

- Open RTP ports from `ASTERISK_RTP_START` to `ASTERISK_RTP_END`.
- Set `external_media_address` and `external_signaling_address` for NAT.
- Keep `direct_media = no` while debugging.
- Confirm codecs allowed by Narayana, typically `ulaw`/`alaw`.

### DTMF Not Detected

- Use `NARAYANA_DTMF_MODE=rfc4733`.
- Confirm the softphone/provider sends RTP telephone-event, not inband-only DTMF.
- Watch Asterisk logs for DTMF events.
- Confirm the ARI/AMI bridge posts each digit to `POST /api/telephony/events` as a single `DTMF` event.

### Wrong Dial Format

The dashboard now exposes a configurable normalizer (`NARAYANA_DIAL_FORMAT`) so you
can switch dial formats without redeploying code. Acceptable values:

| `NARAYANA_DIAL_FORMAT` | Dial string for `+21652603967` |
|---|---|
| `e164_plus`            | `+21652603967` |
| `e164_no_plus`         | `21652603967`        *(default; recommended for Narayana)* |
| `international_00`     | `0021652603967` |
| `national`             | `52603967` *(country code from `NARAYANA_DEFAULT_COUNTRY_CODE`)* |
| `raw`                  | pass-through after stripping spaces, dashes and parentheses |

Use these manual `Originate` commands from `infra/sipup/` to discover which
format Narayana actually accepts for your account. Whichever rings the Orange
test phone is the format to set in `.env`:

```bash
docker compose exec asterisk asterisk -rx \
  "channel originate PJSIP/+21652603967@narayana-trunk extension s@ivr-outbound"
docker compose exec asterisk asterisk -rx \
  "channel originate PJSIP/21652603967@narayana-trunk extension s@ivr-outbound"
docker compose exec asterisk asterisk -rx \
  "channel originate PJSIP/0021652603967@narayana-trunk extension s@ivr-outbound"
docker compose exec asterisk asterisk -rx \
  "channel originate PJSIP/52603967@narayana-trunk extension s@ivr-outbound"
```

In another shell, watch the SIP/RTP wire to see Narayana's response code and
hangup cause:

```bash
docker compose logs -f asterisk
docker compose exec asterisk asterisk -rvvv -x "pjsip set logger on"
```

You should be able to identify each call by:

- the `INVITE` URI Asterisk sent to Narayana
- the SIP response code (200 = ringing/answer, 4xx/5xx = rejected)
- the `Dial` event `dialstatus` (`ANSWER`, `BUSY`, `CHANUNAVAIL`, `NOANSWER`, `CONGESTION`, `FAILED`)
- the channel hangup cause

After identifying the working format, set it in `infra/sipup/.env`:

```bash
NARAYANA_DIAL_FORMAT=e164_no_plus    # or international_00 / national / e164_plus
NARAYANA_DEFAULT_COUNTRY_CODE=216
NARAYANA_DIAL_PREFIX=                # only if Narayana requires a carrier prefix
```

Restart the backend and confirm `GET /api/system/runtime` reports the new
`asterisk.dial_format` value. The next call from the dashboard will originate
through SIP UP using the same dial string.

### Diagnosing pre-answer vs post-answer hangups

The dashboard activity feed now distinguishes the two failure modes:

- *"Call ended before answer (asterisk). Check dial format or provider routing."*
  → Asterisk `Dial` reported `BUSY/CHANUNAVAIL/CONGESTION/FAILED/NOANSWER`,
  Narayana responded with a 4xx/5xx, or the `INVITE` was rejected. Use the
  manual originate steps above to find the working dial format.
- *"Call ended after answer..."*
  → Narayana accepted and the channel reached `Up`, then dropped. Look at the
  ARI bridge logs for `StasisStart` followed by an early `StasisEnd`, audio
  prompt errors, or DTMF mode mismatches.

### Caller ID Rejected

- Set `NARAYANA_OUTBOUND_CALLER_ID` to an assigned/verified caller ID.
- Remove custom caller ID locally if Narayana rejects unverified CLI.
- Ask Narayana whether the caller ID should be username, DID, or blank.

### NAT or Firewall Issues

- Ensure SIP signaling and RTP media ports are reachable.
- Use the correct LAN/public IP in Asterisk transport settings.
- Avoid using `127.0.0.1` for softphones or providers outside the host machine.
- Confirm Docker port mappings match `.env`.

### Provider Balance Insufficient

- Check Narayana account balance/credits.
- Confirm the destination country/route is enabled.
- Confirm the test phone number is allowed by the provider account.

## 7. Move From Softphone Test to Asterisk

Use this progression:

1. Linphone/Zoiper registers directly to Narayana and can place one test call.
2. Asterisk registers to Narayana using the same SIP account or a dedicated trunk account.
3. Asterisk can dial the same test phone through `narayana-trunk`.
4. The Asterisk event bridge sends `ANSWERED`, per-digit `DTMF`, `HANGUP`, and `FAILED` events to the backend.
5. The dashboard happy path passes with one test number.
6. Negative paths pass.
7. Only then expand to a small allowlist with low daily call limits.

## 8. Message Template for Narayana

```text
Hello,

I found the SIP device settings for account 372810444412235:

- SIP Login: 372810444412235
- SIP Server: rdx.narayana.im
- Caller ID: 18009359935
- Transport: TLS recommended
- Encryption: DTLS-SRTP
- IP Auth currently shows 192.168.1.1

Could you please confirm the exact settings needed for Asterisk registration?

1. Should Asterisk register with SIP username/password, or is this device IP-auth only?
2. What is the exact SIP password, or where can we safely reset/generate it?
3. Required port and transport: TLS 5061, UDP 5060, TCP 5060, or WebRTC/DTLS-SRTP only?
4. Should SIP Login also be used as the auth username?
5. What DTMF mode should we use: RFC4733 or SIP INFO?
6. Is outbound calling enabled for this device?
7. Is caller ID 18009359935 allowed for outbound calls?
8. Is IP whitelisting required? If yes, should we replace 192.168.1.1 with our public Asterisk server IP?
9. What outbound dial format should we use, for example +216xxxxxxxx, 216xxxxxxxx, or 00216xxxxxxxx?

We are currently seeing registration rejected from Asterisk and need these details to complete the integration.

Best regards,
Yasin
```
