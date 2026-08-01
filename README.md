# Outbound IVR verification dashboard

Full-stack demo for operations staff to create **app-issued** verification call sessions, drive a **local mock outbound IVR** (no real telephony), and watch **live call events** over **WebSockets**. Verification codes are **bcrypt-hashed** in SQLite; event text **masks digit runs** (only the **last two digits** of each contiguous run remain visible). Call events record an **actor** (`system`, `user`, `telephony_provider`, `admin`) and **AUDIT_STATE_CHANGE** rows for status/step transitions.

This project does **not** collect Messenger/Facebook/WhatsApp/email/bank codes, third-party OTPs, card numbers, passwords, or other external credentials. The safe flow accepts only a **6-digit code from the client’s own official verification system**.

## Documentation and runbooks

| Document | Purpose |
|----------|---------|
| [**`docs/runbooks/sipup-local-dry-run.md`**](docs/runbooks/sipup-local-dry-run.md) | Step-by-step manual dry run: backend, frontend, SIP UP stack, SIP, webhooks, negatives, troubleshooting. |
| [**`docs/runbooks/narayana-real-call-integration.md`**](docs/runbooks/narayana-real-call-integration.md) | Real-call preparation for Narayana SIP/WebRTC via Asterisk registration/trunk, softphone validation, DTMF, and safety gates. |
| [**`docs/runbooks/provider-cutover.md`**](docs/runbooks/provider-cutover.md) | Safe cutover from mock / lab Asterisk to the real client telephony API: preconditions, adapter checklist, safety gates, rollout, rollback, monitoring, go/no-go. |
| [**`docs/qa/manual-ivr-test-report-template.md`**](docs/qa/manual-ivr-test-report-template.md) | Reusable QA report template (metadata, dashboard events, scenarios 1–10). |

### Cutover readiness checklist (manual)

Track these before pointing production traffic at a real provider. Check items off in your ticket or a copied doc.

- [ ] **README** points to the runbooks (links above).
- [ ] **SIP UP local dry-run** completed once manually ([`sipup-local-dry-run.md`](docs/runbooks/sipup-local-dry-run.md)).
- [ ] **QA report** filled for one **happy path** ([template](docs/qa/manual-ivr-test-report-template.md)).
- [ ] **QA report** filled for one **negative path** (e.g. decline, hangup, or duplicate webhook).
- [ ] **Provider-cutover** checklist reviewed ([`provider-cutover.md`](docs/runbooks/provider-cutover.md)) before real API traffic.
- [ ] **No new feature** merged during cutover window (config and provider wiring only).

## Prerequisites

- Python 3.9+ (3.10+ recommended)
- Node.js 18+ and npm
- Docker (optional, for `infra/sipup` lab stack)

## Client setup (handoff quick start)

Use this for a **clean machine** or client handoff.

**Windows 10 + TeamViewer:** see [**`docs/runbooks/client-setup-windows10.md`**](docs/runbooks/client-setup-windows10.md) and double-click launchers in [`scripts/windows/`](scripts/windows/).

**Install everything in one command** (after unzip; needs Python 3.9+ and Node 18+):

```bash
bash scripts/install-all.sh
```

```bat
scripts\windows\install-all.cmd
```

Then create an admin once (`backend/scripts/create_admin.py`). Start with `scripts/run_backend.sh` + `scripts/run_frontend.sh` (or `scripts/windows/start-*.cmd`).

**Pinned dependencies:** authoritative list is **`backend/requirements.txt`** (runtime + Alembic + pytest). The repository root **`requirements.txt`** exists for visibility next to **`README.md`** and only includes `-r backend/requirements.txt` — installing from root or `backend/` resolves the **same packages**.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt        # same as: from repo root, pip install -r requirements.txt
cp .env.example .env                   # set ASTERISK_PASSWORD to match infra/sipup/config/ari.conf
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify install (optional):

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python -c "from app.main import app; print('backend import ok')"
PYTHONPATH=. python -m pytest tests -q
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Production-style check (optional):

```bash
cd frontend
npm install
npm run build
```

Copy [`frontend/.env.example`](frontend/.env.example) to **`frontend/.env.local`** when pointing at a non-proxied API (see Frontend section below).

### Asterisk (Docker lab)

```bash
cd infra/sipup
docker compose up -d
```

See [`infra/sipup/README.md`](infra/sipup/README.md) for SIP, ARI, and env vars.

### ARI bridge (separate process; SIP UP ⇄ backend)

From **`backend`** with the same env as Asterisk (for example sourcing `infra/sipup/.env` so `BACKEND_WS_TOKEN` matches the backend’s **`WS_BROADCAST_BRIDGE_TOKEN`** when using admin-driven IVR):

```bash
cd backend
source .venv/bin/activate
set -a
source ../infra/sipup/.env    # omit or substitute your own env file
set +a
python scripts/run_sip_up_ari_bridge.py
```

Repo wrappers (also source Asterisk `.env`): [`scripts/run_backend.sh`](scripts/run_backend.sh), [`scripts/run_sipup_bridge.sh`](scripts/run_sipup_bridge.sh), [`scripts/run_frontend.sh`](scripts/run_frontend.sh).

---

## Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The default SQLite file is `backend/ivr_verification.db` (override with **`DATABASE_URL`**, same variable used by Alembic and `app.database`).

**Environment (optional)**

- `DATABASE_URL` — SQLAlchemy URL (default `sqlite:///./ivr_verification.db`). Alembic reads this from `app.config`.
- `MAX_CALLS_PER_PHONE_PER_DAY` — cap on `POST /api/calls/start` per normalized phone per UTC day (default `100`; set `0` for unlimited).
- `DTMF_BUFFER_SECRET` — secret used to derive per-session Fernet keys for encrypted `dtmf_buffer` at rest (set a strong value in production).
- `APP_ENV` — when `development` / `dev` / `local`, `POST /api/calls/start` includes `demo_code` in the JSON response (not stored in the database). Use **`staging`** or **`production`** (or any other value) to omit **`demo_code`** from the start response.
- `JWT_SECRET_KEY` — secret for admin JWT access tokens. Development uses a clear local default with a startup warning when this is missing; staging/production fail startup without it.
- `JWT_ALGORITHM` — JWT signing algorithm, default `HS256`.
- `ACCESS_TOKEN_EXPIRE_MINUTES` — admin access token lifetime, default `480`.
- `VIRTUAL_CALL_DEVICE_ENABLED` — prints a local console transcript of what the recipient would hear. Defaults to `true` for `APP_ENV=development` / `dev` / `local`, and `false` otherwise. It masks DTMF/code digits and does not call any TTS API.
- `TELEPHONY_PROVIDER` — `mock` (default), `client_api`, or `sip_up`. On startup, **non-mock** modes require the corresponding credentials (see below) or the process exits with an error.
- `CLIENT_PROVIDER_BASE_URL`, `CLIENT_PROVIDER_API_KEY` — required when `TELEPHONY_PROVIDER=client_api` (real client API cutover; outbound wiring is separate). Optional: `CLIENT_PROVIDER_WEBHOOK_SECRET` for verifying inbound webhooks (not validated at startup).
- `ASTERISK_HOST`, `ASTERISK_PORT`, `ASTERISK_USERNAME`, `ASTERISK_PASSWORD`, `ASTERISK_CONTEXT`, `ASTERISK_ENDPOINT` — required when `TELEPHONY_PROVIDER=sip_up` (see `app/services/telephony/sip_up_ari_provider.py`). For a Narayana/generic SIP trunk via SIP UP, keep `TELEPHONY_PROVIDER=sip_up` and configure the local SIP UP stack files with `NARAYANA_*` variables from `infra/sipup/.env.example`; do not commit real SIP credentials.
- `DISABLE_ARI_SPEECH_TTS` — when `true`/`1`, the ARI speech bridge skips ephemeral macOS/Linux `say` + `afconvert` TTS and falls back strictly to Asterisk WAV assets for mapped prompt keys.

**Database migrations (Alembic)**

From `backend/`:

```bash
alembic upgrade head
```

- **New / empty database:** revision `0001_initial` creates `call_sessions`, `call_events` (including `actor_type`), and `verification_attempts`. `0002_add_call_event_actor_type` is a no-op if the column already exists.
- **Later revisions (idempotent where noted):** `0003` adds `call_sessions.ivr_outcome`; `0004` adds `dtmf_buffer`; `0005` widens `dtmf_buffer` for ciphertext, adds `expected_digits_count` and `buffer_updated_at`, and clears legacy plaintext buffers; `0006` adds **`telephony_event_receipts`** for webhook idempotency.
- **Admin auth:** `0009` adds the **`admin_users`** table for dashboard sign-in.
- **6-digit flow:** `0010` updates existing local rows from 8 expected digits to 6 expected digits.
- **Speech templates + staged admin-send:** `0011` introduces `speech_script_templates` seeded with compliance-approved defaults and aligns the persisted `SimulatorStep`/IVR checkpoints with **waiting_admin_code_send** ahead of keypad collection.
- **Existing SQLite without `call_events.actor_type`:** `0001_initial` skips creation when tables already exist; `0002` adds `actor_type` with default `system`.

If you previously relied only on app startup `create_all` and the schema already matches head, you can mark migrations as applied without re-running DDL:

```bash
alembic stamp head
```

**Reset local SQLite (development only)**

Delete the database file and run migrations again (or let the app recreate via `create_all`):

```bash
rm -f ivr_verification.db
alembic upgrade head
```

**Tests**

Tests use an **in-memory** SQLite engine injected in `tests/conftest.py`; they do **not** run Alembic. **Dependencies:** same `requirements.txt` as the API (includes **pytest**).

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python -m pytest tests/ -q
```

From the **repository root** (monorepo), set `PYTHONPATH` so `import app` resolves:

```bash
PYTHONPATH=backend python3 -m pytest backend/tests -q
```

**Compliance checklist (automated in `tests/test_compliance_checklist.py` + neighbours):** pytest passes; verification codes remain **bcrypt-hashed**; persisted event copy stays **masked** (`DIGITS_RECEIVED` lacks long plaintext runs); **DTMF keypad entry is gated** behind **admin acknowledgement** (`waiting_admin_code_send` ↔ `/admin/code-sent`); editable **speech templates** obey server-side bans (`tests/test_speech_scripts_api.py`); **3** verification attempts remain capped; **`actor_type`** is always populated; **AUDIT_STATE_CHANGE** persists step/status deltas; Asterisk webhook + simulator routes stay aligned with Narayana integrations.

API base URL: `http://127.0.0.1:8000`  
Interactive docs: `http://127.0.0.1:8000/docs`

### Admin authentication

Create the first admin locally from `backend/`:

```bash
python scripts/create_admin.py \
  --email admin@example.com \
  --password "StrongPassword123!" \
  --full-name "Admin"
```

The script hashes the password with bcrypt, refuses weak passwords, does not print the password, and exits without changing the user if the email already exists.

The React dashboard shows a professional login screen before rendering the console. After sign-in, the frontend stores the JWT access token in `localStorage`, sends it as `Authorization: Bearer <token>` for dashboard APIs, restores the session with `GET /api/auth/me`, and clears the token on logout or `401`.

Admin auth endpoints:

- `POST /api/auth/login` — returns `access_token`, `token_type`, and safe admin profile fields.
- `GET /api/auth/me` — returns the authenticated admin profile.
- `POST /api/auth/logout` — client-side logout helper; token invalidation is currently client-side.

Protected by admin JWT:

- `GET /api/calls`, `GET /api/calls/{call_id}`, `GET /api/calls/{call_id}/events`
- `POST /api/calls/start`
- `DELETE /api/calls/{call_id}` local/demo cleanup
- `POST /api/calls/{call_id}/admin/approve-verification`
- `POST /api/calls/{call_id}/admin/reject-verification`
- `POST /api/calls/{call_id}/admin/code-sent` — advance from **waiting_admin_code_send** to **verification_code** after the admin confirms the institutional code was sent on the client-owned channel (dashboard does **not** deliver OTP/SMS/third-party prompts).
- `GET /api/speech-scripts`, `PUT /api/speech-scripts`, `POST /api/speech-scripts/reset`
- `POST /api/simulator/{call_id}/...` local simulator endpoints
- `WS /ws?token=<access_token>` live dashboard stream

Telephony webhooks remain separate from admin authentication because Asterisk or the provider calls them directly. Keep webhook security provider-specific.

### Main endpoints

- `POST /api/calls/start` — Admin JWT required. Create session (name, university, phone), hash the 6-digit code, emit **CALL_CREATED** / **CALL_INITIATED** over WebSocket, then starts the configured provider: `MockTelephonyProvider` for `TELEPHONY_PROVIDER=mock`, or SIP UP media originate for `TELEPHONY_PROVIDER=sip_up`. Response: `call_id` and, **only when `APP_ENV` is `development` / `dev` / `local`**, `demo_code`.
- `GET /api/calls` — List sessions.
- `GET /api/calls/{call_id}` — Session detail.
- `GET /api/calls/{call_id}/events` — Historical events for a session.
- `POST /api/simulator/{call_id}/answered` — Admin JWT required for local simulator access. IVR: **CALL_ANSWERED**, step `consent`.
- `POST /api/simulator/{call_id}/press` — Body `{ "digit": "1" | "2" }`: **1** → **RECIPIENT_ACCEPTED**, step `waiting_admin_code_send` (“admin must send institutional code externally, then press Done — code sent in dashboard”); **2** → **RECIPIENT_DECLINED**, status `completed`.
- `POST /api/simulator/{call_id}/enter-code` — Allowed only once the administrator has tapped **Done — code sent** (real calls: `POST /api/calls/{call_id}/admin/code-sent`). Body `{ "digits": "123456" }`: stores encrypted entry, emits masked **DIGITS_RECEIVED**, and moves to **pending_admin_verification**. It does **not** auto-verify or use AI verification.
- `POST /api/calls/{call_id}/admin/approve-verification` — Admin-only review action from **pending_admin_verification**: emits **ADMIN_VERIFICATION_APPROVED**, then **VERIFICATION_SUCCESS**, and completes the call.
- `POST /api/calls/{call_id}/admin/reject-verification` — Admin-only review action from **pending_admin_verification**: emits **ADMIN_VERIFICATION_REJECTED**; retries return to `verification_code` until the max attempt count fails the call.
- `POST /api/simulator/{id}/action` — Body: `{ "action": "start_call" | "hangup" | "submit_digits", "digits": "..." }` (outbound mock + legacy keypad).
- `POST /api/telephony/events` — Provider webhook (`ANSWERED`, `DTMF`, `HANGUP`, `FAILED`). Does not use admin JWT. Optional **`provider_event_id`** enables idempotency: replays return **`status: duplicate_ignored`** without double-applying state, DTMF, or verification attempts. Responses use **`session_status`** for the call row’s status (the previous `status` field name was overloaded).
- `WS /ws?token=<access_token>` — Authenticated broadcast stream: `CALL_CREATED`, `CALL_INITIATED`, `call_event`, `session_update` messages (each event carries a masked `event` object when applicable).

## Frontend (React + Vite + Tailwind)

```bash
cd frontend
npm install
npm run dev
```

For **direct REST + WebSocket to port 8000** (recommended when fixing **Failed to fetch** / CORS), copy [`frontend/.env.example`](frontend/.env.example) to **`frontend/.env.local`** setting:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

**Restart** `npm run dev` whenever `.env*` changes (Vite loads them only at startup). The bundled [`frontend/.gitignore`](frontend/.gitignore) ignores `.env.local` by convention.

Repo shortcuts (executable): [`scripts/run_backend.sh`](scripts/run_backend.sh), [`scripts/run_sipup_bridge.sh`](scripts/run_sipup_bridge.sh), [`scripts/run_frontend.sh`](scripts/run_frontend.sh).

### Per-call provider selection (SIP UP)

Choosing **Start verification call** opens a modal: **Mock / current provider** sends `outbound_trunk=default` (the same behavior as before for your `TELEPHONY_PROVIDER`), or **SIP UP** sends `outbound_trunk=sip_up` to use **`SipUpTelephonyProvider`** (`SIPUP_*` only — **no** `ASTERISK_*` required). Set **`SIPUP_SIP_HOST`** **or** **`SIPUP_SIP_DOMAIN`** (carrier SIP domain fills in when host is unset), **`SIPUP_SIP_USERNAME`**, **`SIPUP_SIP_PASSWORD`**, **`SIPUP_PJSIP_ENDPOINT`**, **`SIPUP_OUTBOUND_CALLER_ID`**, optional **`SIPUP_DIAL_*`**, **`SIPUP_ORIGINATE_POST_URL`**. **Local development:** if registrar host/domain are both unset, **`sip.sipup.org`** is used unless **`SIPUP_FALLBACK_REGISTRAR`** overrides or **`SIPUP_FALLBACK_REGISTRAR=`** (empty) disables; staging/production require an explicit registrar. The API loads **`backend/.env`** for the FastAPI process; with local **`APP_ENV`** (not staging/production/prod), it **also merges** **`infra/sipup/.env`** when that file exists (non-overriding; disable with **`BACKEND_MERGE_INFRA_SIPUP_DOTENV=0`**). **`BACKEND_MERGE_INFRA_SIPUP_DOTENV=1`** still forces merge explicitly. Secrets stay untracked.

Open `http://localhost:5173` (or `5174` if the port is busy). The dev server can still proxy relative `/api` and `/ws` when you omit `VITE_API_BASE_URL`; with an absolute URL the browser talks to **`http://localhost:8000/api/...`** directly. Production builds should point `VITE_API_BASE_URL` at your deployed API origin. Sign in with an admin created by `backend/scripts/create_admin.py`.

### Dashboard layout (authenticated console)

Three columns emphasize **live Asterisk/mock state**:

1. **Left — outbound controls.** Start-call flow with a **provider picker** (default vs SIP UP), country picker + masked phone normalization, contextual banners, collapsible detailed **history queue** (`Open`/`Delete`).
2. **Middle — provider console.** Highlights `SimulatorStep`, runtime provider badges, scripted prompt previews (from **`GET /api/speech-scripts`**), timelines, masking reminders, actionable **Done — code sent**, then the admin verification panel (`tests` mirror this ordering).
3. **Right — workflow + configuration.** Compact **recent calls**, the six-stage **checkpoint rail**, and the **speech scripts** editor (`PUT /api/speech-scripts`, `POST /api/speech-scripts/reset`). **Show technical logs** toggles the verbose feed off by default.

### Mobile call simulator

The mobile call simulator is local development only and is disabled by default with:

```bash
VITE_ENABLE_MOBILE_SIMULATOR=false
```

Real-call mode uses Narayana/SIP UP call audio, not browser `speechSynthesis`. The admin dashboard only shows the call form, status, pending admin verification controls, activity feed, and call history. To re-enable the simulator for local debugging, set `VITE_ENABLE_MOBILE_SIMULATOR=true` before starting the frontend.

### Phone number entry

The **Start outbound verification** form has a compact country selector before the phone input. It defaults to **Tunisia** as `🇹🇳 +216`. Admins enter only the national number, for example `26 565 725`; the frontend strips spaces, dashes, and parentheses, then sends the existing backend field as an E.164-style value:

```text
phone_number = selectedDialCode + cleanedNationalNumber
```

For Tunisia with `26 565 725`, the backend receives `+21626565725`.

Recent organization names are suggested locally in the browser using `localStorage` key `ivr_recent_organizations`. Only organization names are stored for convenience. Phone numbers, verification codes, and DTMF digits are never stored in browser storage.

### Call history

The dashboard includes a **Call history** panel loaded from `GET /api/calls`. It shows previous local/demo calls with recipient, organization, masked phone, status, step, timestamps, and a short call ID. Use **Open** to load a call into the active dashboard view.

Use **Delete** to remove local/demo calls from history. The dashboard asks: `Delete this call from local history?` before calling `DELETE /api/calls/{call_id}`. Deletion is intended for local/demo cleanup.

### Local virtual call device

Before connecting Asterisk audio/TTS, you can watch the backend console for the local virtual device transcript:

```bash
export APP_ENV=development
export VIRTUAL_CALL_DEVICE_ENABLED=true
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

During a simulator or webhook flow, the backend prints blocks like:

```text
[VIRTUAL CALL DEVICE]
Call ID: ...
Phone: ******25
Step: pending_admin_verification
DTMF RECEIVED: ******13
SAY: Thank you. Please wait while an administrator verifies your code.
```

This is local-only text output for dry runs. It does not affect IVR state, does not auto-verify codes, and never prints the full 6-digit entry.

## Typical real-call flow (Narayana + Asterisk)

1. Confirm `pjsip show registrations` shows Narayana as **Registered**.
2. Start the backend with `TELEPHONY_PROVIDER=sip_up`.
3. Start the ARI bridge with the same Asterisk env.
4. Start the frontend and sign in to the dashboard.
5. Start one call from the dashboard.
6. The real phone rings through Narayana/Asterisk.
7. Recipient hears the scripted consent greeting and presses **1** to proceed.
8. Institution staff send the institutional verification credential through **their own official platform/channel** outside this stack. The dashboard only shows guidance + **Done — code sent**.
9. After **Done**, Asterisk cues the callee to enter the **6-digit** official verification value captured from the keypad.
10. Dashboard moves to **pending admin verification** once six digits arrive.
11. Admin approves or rejects from the dashboard (no automated acceptance).
12. Asterisk plays the final prompts using the persisted speech templates/TTS cues and hangs up once the backend reaches a terminal outcome.

## Full flow checklist (Asterisk + dashboard)

Use this when wiring **real SIP** (softphone) and **`POST /api/telephony/events`**. The table maps each acceptance item to **how it is covered** in this repo.

| Goal | Covered by | Notes |
|------|----------------|------|
| Local Asterisk can call a SIP softphone | **Manual** — `infra/sipup/` | Docker Compose + `pjsip.conf` (see **`infra/sipup/README.md`**). Register Zoiper/Linphone, dial test extension. |
| Answer event reaches backend | **Tests** + **manual** | `POST /api/telephony/events` with `event_type: "ANSWERED"` and `call_id` = UUID from **`POST /api/calls/start`**. See `tests/test_telephony_webhook.py`. |
| Press **1** (consent) reaches dashboard live | **Tests** + **manual** | After **ANSWERED**, each webhook triggers a WebSocket broadcast. Consent **1** persists **RECIPIENT_ACCEPTED**, moves **`waiting_admin_code_send`**, and surfaces the **Done — code sent** task (see `tests/test_telephony_webhook.py`). |
| **`POST /api/calls/{id}/admin/code-sent`** gated | **Tests** | Duplicate or out-of-order admin confirmations return **400**. |
| **6** DTMF digits reach backend one-by-one | **Tests** + **manual** | Only after `/admin/code-sent` should six **`DTMF`** events fill the keypad buffer (`tests/test_dtmf_buffering.py`). |
| Admin approval completes call | **Tests** + **manual** | The backend does not auto-verify code entry. Admin clicks **Approve**, which emits **ADMIN_VERIFICATION_APPROVED** and **VERIFICATION_SUCCESS**, then terminal **completed**. |
| Admin rejection retries then fails after **3** attempts | **Tests** | Admin clicks **Reject** from **pending_admin_verification**. Attempts remaining return to `verification_code`; the third rejection fails the call. See `test_admin_verification.py` and `test_compliance_flow.py`. |
| Duplicate webhook events do not duplicate state | **Tests** | Send a stable **`provider_event_id`** per provider delivery; replays return **`{"status": "duplicate_ignored"}`** (HTTP 200) with no extra DTMF, attempts, or step changes. Requires migration **`0006`** on your DB. See `tests/test_telephony_idempotency.py`. |
| Hangup during any step creates clean final state | **Tests** + **manual** | **`HANGUP`** maps to **CALL_HANGUP** and a terminal session outcome (failed or completed/declined depending on IVR step). See `test_telephony_webhook.py`. |
| Dashboard never shows raw full code in the **event stream** | **Design** + **tests** | `call_service.add_event` runs **`mask_digits_in_text`** before DB and WebSocket; **DIGITS_RECEIVED** messages must not contain long plaintext digit runs (`test_compliance_checklist.py`). |

**Recommended manual Asterisk path (summary):**

1. Start FastAPI + frontend; run **`infra/sipup`** per its README (SIP + ARI).
2. **`POST /api/calls/start`** → save **`call_id`** (UUID). Pass that UUID into your ARI/Stasis app (channel variable or originate argument) so every webhook includes the same **`call_id`**.
3. On answer → `{"provider":"sip_up","call_id":"<uuid>","event_type":"ANSWERED"}` (optional **`provider_call_id`**, **`provider_event_id`**).
4. On each DTMF → `{"event_type":"DTMF","digit":"3",...}` — one digit per request during verification. After 6 digits, the dashboard shows **pending admin verification** with only the masked entry (for example `****13`).
5. Admin reviews the masked entered code and clicks **Approve** or **Reject**. Audit logs remain masked. Approval completes the call; rejection allows retry until the max attempt count fails the call.
6. On teardown → **`HANGUP`** or **`FAILED`** as appropriate.
7. Open the dashboard **`WS /ws`** session and confirm **Live** events match steps above without raw 6-digit strings in log text.

Detailed SIP ports, `host.docker.internal`, and curl examples: **`infra/sipup/README.md`**. For a full manual procedure, use **[`docs/runbooks/sipup-local-dry-run.md`](docs/runbooks/sipup-local-dry-run.md)**.

## Narayana / Asterisk real-call mode

See **`infra/sipup/`** and **[`docs/runbooks/narayana-real-call-integration.md`](docs/runbooks/narayana-real-call-integration.md)** for Docker Compose, TLS SIP registration, ARI bridge startup, prompt sound files, and real-call test steps. Asterisk mode originates the call through Narayana and forwards real answer/DTMF/hangup events to `POST /api/telephony/events`.

## Project layout

Repository root overview (not every file listed):

```
.                          # outbound IVR verification dashboard
├── README.md
├── requirements.txt       # redirects to backend/requirements.txt (−r) for installs from repo root / IDE sidebar
├── backend/
│   ├── alembic/           # env.py + migrations (run: alembic upgrade head from backend/)
│   ├── app/
│   │   ├── main.py        # FastAPI app + CORS + router mount
│   │   ├── config.py      # DATABASE_URL, auth, provider mode
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   ├── auth.py
│   │   ├── websocket_manager.py
│   │   ├── services/
│   │   │   ├── call_service.py
│   │   │   ├── speech_script_service.py
│   │   │   ├── sip_up_ari_bridge.py   # used by scripts/run_sip_up_ari_bridge.py
│   │   │   ├── outbound_simulation.py
│   │   │   ├── telephony/               # mock_provider, sip_up_ari_provider, sip_up_provider, base
│   │   │   └── ...
│   │   └── routers/       # auth, calls, simulator, telephony, speech_scripts, websocket, system
│   ├── scripts/
│   │   ├── create_admin.py              # bootstrap first dashboard admin
│   │   └── run_sip_up_ari_bridge.py   # SIP UP ⇄ POST /telephony/events + optional backend WS
│   ├── tests/             # pytest (in-memory SQLite via conftest.py)
│   └── requirements.txt   # runtime + alembic + pytest (single handoff file)
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── socket.js
│       └── components/    # CallForm, LiveProviderPanel, LoginScreen, workflow/history modals, etc.
├── infra/
│   └── sipup/          # Docker Compose SIP lab, sample pjsip/ari configs, README, .env.example
├── docs/
│   ├── runbooks/          # sipup dry-run, Narayana integration, provider cutover
│   └── qa/
└── scripts/               # run_backend.sh, run_sipup_bridge.sh, run_frontend.sh (source infra env)
```

## Security notes

- Issued verification codes are stored with **bcrypt**; the local QA plaintext appears only in the create-session response. Entered DTMF digits are kept encrypted at rest while pending admin review and are shown only in masked form.
- Log lines run through **digit masking** before persistence and WebSocket broadcast.
- Replace the mock provider under `telephony/` with a real integration when you connect to actual carriers—keep hashing and masking in place.
