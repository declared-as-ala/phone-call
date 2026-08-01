# Runbook: Local Asterisk IVR dry run (end-to-end)

Step-by-step manual test of the verification flow when **SIP + Asterisk** are in the loop and the FastAPI **`POST /api/telephony/events`** webhook drives IVR state. The app still **defaults to `MockTelephonyProvider`** after **`POST /api/calls/start`**; the mock may emit lifecycle events in parallel with Asterisk. For a **clean Asterisk-only** signal path, start the session from the dashboard (or API) and rely on your **ARI / dialplan / curl** bridge to send webhook payloads—optionally pause or disable the mock in code for that session if double events are confusing.

---

## ARI bridge — single process (local dev)

Run **exactly one** `run_sip_up_ari_bridge` process per SIP UP Stasis app. Multiple bridge PIDs each subscribe to the backend websocket and can **replay** admin-driven speech (for example `code_sent_prompt` looping).

Check running instances:

```bash
ps aux | grep run_sip_up_ari_bridge | grep -v grep
```

Expected logs on startup include **`SIP UP media websocket connected`** with **`bridge_instance=…`** and **`pid=…`**, and when the dashboard websocket is configured: **`ARI backend WS subscribed`** (with the same bridge instance id).

---

## 1. Prerequisites

Before the dry run, confirm:

| Requirement | How to verify |
|-------------|----------------|
| **Backend running** | `http://127.0.0.1:8000/docs` loads. |
| **Frontend running** | `http://localhost:5173` loads; API proxy to port 8000 works. |
| **Alembic at head** | From `backend/`: `alembic upgrade head` (includes **`telephony_event_receipts`** / `0006` for idempotent webhooks). |
| **Asterisk Docker stack** | From `infra/sipup/`: configs copied from `*.example`, `docker compose ps` shows **healthy/running** container. |
| **SIP softphone registered** | Zoiper/Linphone shows **registered**; Asterisk CLI: `pjsip show endpoints` (inside container) lists your endpoint **Avail**. |
| **DTMF mode RFC 4733** | Softphone uses **RTP telephone-event** (RFC 2833 / 4733), not inband-only. Match Asterisk **`dtmf_mode = rfc4733`** (or equivalent) in `pjsip.conf` per **`infra/sipup/README.md`**. |

---

## 2. Environment variables

Set these in the shell (or `.env` consumed by your process manager) **before** starting the backend.

### Application (FastAPI)

| Variable | Purpose |
|----------|---------|
| **`APP_ENV=development`** | **`POST /api/calls/start`** returns **`demo_code`** once for QA (not stored in DB). Omit or use a non-dev value in production-like runs. |
| **`VIRTUAL_CALL_DEVICE_ENABLED=true`** | Prints a local backend-console transcript of what the recipient would hear before real Asterisk audio/TTS. Defaults to true in development and false in staging/production-like environments. |
| **`DTMF_BUFFER_SECRET`** | Secret for encrypting **`call_sessions.dtmf_buffer`** at rest. Use a long random string; **never** commit it. |

Optional:

| Variable | Purpose |
|----------|---------|
| **`DATABASE_URL`** | Defaults to `sqlite:///./ivr_verification.db` under `backend/`. |
| **`MAX_CALLS_PER_PHONE_PER_DAY`** | Rate limit for starts (default `100`; `0` = unlimited). |

### Asterisk integration (Python `SipUpAriProvider` / future ARI client)

These names match **`backend/app/services/telephony/asterisk_provider.py`**. They are **not** required for the webhook-only dry run if you only **`curl`** `POST /api/telephony/events` from the host; set them when you run code that calls **`SipUpAriProvider`**.

| Variable | Purpose |
|----------|---------|
| **`ASTERISK_HOST`** | ARI HTTP host (e.g. `127.0.0.1` or container-reachable address). |
| **`ASTERISK_PORT`** | ARI HTTP port (numeric string; default in code if unset: **8088**). |
| **`ASTERISK_USERNAME`** | ARI username (section name in `ari.conf`). |
| **`ASTERISK_PASSWORD`** | ARI password (**required** for real `SipUpAriProvider` use). |
| **`ASTERISK_CONTEXT`** | Dialplan context for originate (e.g. `ivr-local-dev`). |
| **`ASTERISK_ENDPOINT`** | PJSIP endpoint or channel technology label for originate. |
| **`ASTERISK_PROMPT_PREROLL_MS`** | Milliseconds after answer before the first consent prompt plays (helps RTP/audio path warm-up); default **300** (clamp **0–5000** in code). |
| **`ASTERISK_PROMPT_SILENCE_MEDIA`** | Optional ARI `media` string (e.g. `sound:silence/1` if shipped in your Asterisk sounds) played once after preroll **only when** preroll is active; omit for sleep-only warmup. |

Align values with **`infra/sipup/config/ari.conf`** and **`pjsip.conf`** (copied from examples).

---

## 2b. Cheap verification (minimal paid SIP)

1. **`VIRTUAL_CALL_DEVICE_ENABLED=true`** transcript in the backend console validates script order **without RTP**.  
2. **`PYTHONPATH=backend python3 -m pytest backend/tests -q`** validates preroll wiring, webhook dedupe (`provider_event_id`), duplicate DTMF `1`, and sequencing logic without dialing.  
3. **Softphone ↔ local Asterisk** (registration + ` originate`/`Stasis`): one controlled leg after logs look right. Prefer a **single** Narayana/origination check rather than iterative paid retries.

---

## 3. Commands

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
export APP_ENV=development
export VIRTUAL_CALL_DEVICE_ENABLED=true
export DTMF_BUFFER_SECRET='replace-with-long-random-secret'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Asterisk (Docker)

```bash
cd infra/sipup
# First-time: copy config/*.example to config/*.conf and edit (see infra/sipup/README.md)
docker compose up -d
docker compose logs -f asterisk   # optional: watch startup
```

### Virtual call device (pre-Asterisk audio check)

With `APP_ENV=development` and `VIRTUAL_CALL_DEVICE_ENABLED=true`, the backend console prints local-only transcript blocks for the same events that drive the dashboard:

```text
[VIRTUAL CALL DEVICE]
Call ID: ...
Phone: ******25
Step: consent
SAY: Hello Yassin. This is an official verification call from Polytech. ...
WAITING FOR DTMF: press 1 to continue, 2 to decline
```

Use this to verify prompt text and event ordering before wiring real Asterisk audio or a TTS engine. It is side-effect only: it does not change IVR state, does not auto-verify entries, and masks 6-digit DTMF/code values.

### Tests (from repository root)

```bash
cd /path/to/Project   # repo root containing backend/ and frontend/
PYTHONPATH=backend python3 -m pytest backend/tests -q
```

---

## 4. Manual flow (happy path)

Use the **dashboard** and your **softphone + integration** (ARI app, AGI, or **`scripts/curl-telephony-event.example.sh`** from **`infra/sipup`**) to send JSON to:

`http://127.0.0.1:8000/api/telephony/events`

(From inside Docker, prefer `http://host.docker.internal:8000/api/telephony/events` as in **`infra/sipup/README.md`**.)

1. **Create a call** from the dashboard (**Start outbound verification**). Note **`call_id`** (UUID) and, with **`APP_ENV=development`**, **`demo_code`** in the banner.
2. **Early events (WebSocket / Live logs)**  
   - Expect at least **`CALL_CREATED`**, **`CALL_INITIATED`**.  
   - If the **mock** outbound task runs, you may also see **`DIAL_STARTED`**, **`CALL_RINGING`**, and legacy **`ANSWERED`** (pre-consent channel) before consent—see root **README** “Full flow checklist”.  
   - Your SIP UP bridge may mirror similar lifecycle events if you implement them.
3. **Answer the softphone** on the Asterisk leg (dial test extension per **`infra/sipup`** docs).
4. **Post answer to backend** (or have automation do it):

   ```json
   {
     "provider": "sip_up",
     "call_id": "<UUID-from-step-1>",
     "event_type": "ANSWERED",
     "provider_event_id": "ari-answer-1",
     "provider_call_id": "<optional channel id>"
   }
   ```

   Confirm **`CALL_ANSWERED`** in the live event stream (consent prompt step).
5. **Press 1** (consent accept). Send:

   ```json
   {
     "provider": "sip_up",
     "call_id": "<UUID>",
     "event_type": "DTMF",
     "digit": "1",
     "provider_event_id": "ari-dtmf-consent-1"
   }
   ```

   Confirm **`RECIPIENT_ACCEPTED`**, **`waiting_admin_code_send`**, spoken **admin wait** prompt hints, plus the amber **Done — code sent** task in the React console.
6. **Admin confirms external dispatch** (`POST /api/calls/<UUID>/admin/code-sent` with JWT—or click **Done — code sent** in the dashboard). Confirm **`ADMIN_CODE_SENT_CONFIRMED`**, **`verification_code`** step, and audible **`code_sent_prompt`** cues from Asterisk/TTS plumbing.
7. **Enter the 6-digit official verification code** as six sequential **`DTMF`** requests (digits `0–9`; one **`digit` per webhook**):

   ```json
   {
     "provider": "sip_up",
     "call_id": "<UUID>",
     "event_type": "DTMF",
     "digit": "0",
     "provider_event_id": "ari-dtmf-ver-<n>-<digit>"
   }
   ```

   Use a **unique** `provider_event_id` per delivery. After each digit arrives, **`DIGIT_RECEIVED`** (masked payload). Once the sixth digit lands, **`DIGITS_RECEIVED`**, **`PENDING_ADMIN_VERIFICATION`** follow. Backend **never auto-verifies** and **never** calls external AI adjudication.
8. **Approve / reject** from **Pending admin verification**: **Approve** emits **`ADMIN_VERIFICATION_APPROVED`**, **`VERIFICATION_SUCCESS`**, and completes the session. **Reject** emits **`ADMIN_VERIFICATION_REJECTED`**, rewinds attempts to **`verification_code`**, and fails after reaching the capped attempts.
9. **Dashboard live updates**: **`WS /ws`** publishes **`session_update`** plus masked **`call_event`** payloads so timeline + checkpoint rail stay synced with Asterisk.
---

## 5. Negative tests

Perform the same **`call_id`** / webhook pattern; after each scenario, confirm DB and UI (or **`GET /api/calls/{id}/events`**) match expectations.

| Scenario | Actions | Expected |
|----------|---------|----------|
| **Decline at consent** | After **`ANSWERED`**, send **`DTMF`** with **`digit": "2"`** | **`RECIPIENT_DECLINED`**, terminal **completed** (declined). |
| **Reject code × 3** | After `/admin/code-sent`, submit six keypad digits → reject each **pending admin verification**, repeat twice more | **`ADMIN_VERIFICATION_REJECTED`** each cycle; rewinds remain on **`verification_code`** until max attempts ⇒ **failed**. |
| **Duplicate `provider_event_id`** | Replay the **same** JSON (same `provider_event_id`) | HTTP **200** with **`status": "duplicate_ignored"`**; no double DTMF buffer, attempts, or step jumps. |
| **Hang up during consent** | After **`CALL_ANSWERED`**, send **`event_type": "HANGUP"`** | **`CALL_HANGUP`**; terminal state consistent with consent hangup (**completed** / declined-style outcome per server logic). |
| **Hang up during verification** | After **`/admin/code-sent`**, send partial keypad digits, then **`HANGUP`** | **`CALL_HANGUP`**; session **failed** (abandoned verification path). |
| **DTMF after terminal** | After success or failure terminal state, send another **`DTMF`** | Response indicates **noop** (e.g. **`noop": true`**) with detail that DTMF was ignored; no new verification events. |

---

## 6. Expected dashboard output (Live logs)

For each **`call_event`** (and related WS types), the UI row should show:

| Column | Content |
|--------|---------|
| **Timestamp** | Server **`created_at`** (ISO), formatted locally. |
| **Event type** | Canonical types (e.g. **`CALL_ANSWERED`**, **`DIGIT_RECEIVED`**, **`RECIPIENT_ACCEPTED`**, **`PENDING_ADMIN_VERIFICATION`**, **`ADMIN_VERIFICATION_APPROVED`**, **`VERIFICATION_SUCCESS`**). |
| **Actor** | **`system`**, **`user`**, **`telephony_provider`**, or **`admin`** per persisted **`actor_type`**. |
| **Masked payload** | **`message`** after server-side **`mask_digits_in_text`**: long digit runs show only the **last two** digits of each run; no full 6-digit plaintext in event text. |

The **“Call started”** banner may show full **`demo_code`** only when **`APP_ENV`** is dev-like and the API returned it—that is intentional for local QA, not the same as the masked event stream.

---

## 7. Troubleshooting

| Symptom | Things to check |
|---------|------------------|
| **No SIP registration** | UDP **5060** (or mapped port) open; **username/password** match **`pjsip.conf`**; softphone uses host **LAN IP** if not on the same machine as Docker; **`pjsip show endpoints`** / **`pjsip show registrations`** in Asterisk CLI. |
| **No audio (one-way or silent)** | NAT: **`external_media_address`** / **`external_signaling_address`** in transport; **`direct_media = no`** for debugging; RTP port range in **`docker-compose.yml`** matches firewall; codecs **ulaw/alaw** negotiated. |
| **DTMF not detected** | Softphone and Asterisk both on **RFC 4733** / telephone-event; avoid inband-only; see **`infra/sipup/README.md`** DTMF section. |
| **Backend unreachable from Docker** | From container: `wget`/`curl` **`http://host.docker.internal:8000/docs`**; on Linux without **host-gateway**, use host bridge IP or run API in the same compose network. |
| **Duplicate / double state** | Send **`provider_event_id`** on every webhook; run **`alembic upgrade head`** so **`telephony_event_receipts`** exists; avoid two systems (mock + Asterisk) posting conflicting lifecycles without coordination. |
| **Migrations missing** | **`Table ... telephony_event_receipts doesn't exist`** or idempotency errors: `cd backend && alembic upgrade head`. Fresh SQLite: delete DB file only in dev, then upgrade again. |

---

## References

- Root **`README.md`** — API summary, checklist, **`WS /ws`** behavior.  
- **`infra/sipup/README.md`** — Compose, SIP, ARI, webhook JSON, **`host.docker.internal`**.  
- **`POST /api/telephony/events`** — OpenAPI **`/docs`** on the running backend.
