# Implementation Changelog

Chronological log of every change made under `docs/IMPLEMENTATION_TODO.md`. One entry per completed task.

---

## 2026-08-01 — Baseline

- **Task ID:** N/A (baseline)
- **Files modified:** none (read-only inspection); recreated `backend/.venv` (build artifact, not source — original venv was created on a different machine and its Python launcher path was broken)
- **Problem fixed:** N/A
- **Solution implemented:** N/A
- **Tests executed:** `PYTHONPATH=. pytest tests -q` (backend), `npm run build` (frontend) — see baseline report in conversation for full results
- **Result:** Baseline recorded; `docs/IMPLEMENTATION_TODO.md` and this file created
- **Remaining risks:** None yet — implementation not started

---

## 2026-08-01 — SEC-1: Close public admin self-registration

- **Task ID:** SEC-1
- **Files modified:**
  - `backend/app/routers/auth.py` — `/register` gated behind `Depends(get_current_admin)`; response changed from `AuthTokenResponse` (token + cookie side-effect) to `AdminRead` only (no token issued, caller's own session/cookie untouched).
  - `frontend/src/api.js` — `registerAdmin()` renamed `createAdmin()`; no longer calls `markAuthSessionActive()`.
  - `frontend/src/components/LoginScreen.jsx` — removed the sign-in/register mode toggle and all register-only fields (full name, confirm password); page is sign-in only.
  - `backend/tests/test_admin_auth.py` — replaced `test_register_creates_account_and_logs_in` (asserted the vulnerable behavior) with `test_register_rejects_anonymous_caller` (401) and `test_authenticated_admin_can_create_new_admin` (201, verifies no session hijack, new admin can log in independently); updated the duplicate-email/weak-password tests to use the authenticated fixture client instead of an anonymous one.
- **Problem fixed:** `POST /api/auth/register` had no authentication guard and the login screen exposed a public "Create account" toggle — any unauthenticated visitor could self-provision an admin account with full operational access (start real outbound calls, approve verification codes, edit speech scripts).
- **Solution implemented:** Registration now requires an existing authenticated admin, in every environment (no dev-mode bypass). The first admin is created exclusively via the already-existing, already-documented `backend/scripts/create_admin.py` CLI bootstrap — this avoids a first-deploy race condition that an API-based "zero admins exist" bootstrap path would introduce. When an admin creates another admin, the response contains only the new admin's public profile; no token is issued and no cookie is set, so the calling admin's own session cannot be accidentally swapped.
- **Tests executed:** `PYTHONPATH=. pytest tests/test_admin_auth.py -q` → 11 passed. Full suite `pytest tests -q` → 249 passed, 10 failed (all 10 pre-existing and unrelated — see SEC-7). `npm run build` → clean, no errors.
- **Result:** Public self-registration closed. Frontend has no register affordance in any build.
- **Remaining risks:** None for this specific vulnerability. Follow-up: an authenticated "Administration" screen to actually surface `createAdmin()` in the UI is scheduled under FE-9/Task 9 (currently only reachable via direct API call by a signed-in admin).

## 2026-08-01 — SEC-2: Authenticate telephony webhook

- **Task ID:** SEC-2 (+ discovered: BE-9)
- **Files modified:**
  - new `backend/app/webhook_security.py` — HMAC-SHA256 signature verification (`X-Webhook-Timestamp` + `X-Webhook-Signature`), constant-time comparison via `hmac.compare_digest`, timestamp-window replay guard.
  - `backend/app/config.py` — added `TELEPHONY_WEBHOOK_SECRET` / `TELEPHONY_WEBHOOK_TOLERANCE_SECONDS`; `validate_auth_configuration()` now requires the secret in staging/production and warns in development when unset.
  - `backend/app/routers/telephony.py` — router-level `Depends(verify_telephony_webhook_signature)`.
  - `backend/app/services/sip_up_ari_bridge.py` — `SipUpAriBridgeConfig` gained `backend_webhook_secret`; `_post_backend_event` signs outbound requests when configured.
  - `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`, `deploy/digitalocean/env/sipup.env.template` — documented the new shared secret on both the backend and ARI-bridge sides.
  - new `backend/tests/test_telephony_webhook_auth.py`.
- **Problem fixed:** `POST /api/telephony/events` had zero authentication — anyone who learned/guessed a `call_id` UUID could forge ANSWERED/DTMF/HANGUP webhook events and manipulate a real verification call's state from outside the system.
- **Solution implemented:** Shared-secret HMAC-SHA256 signing (Stripe/GitHub-style), enforced only when `TELEPHONY_WEBHOOK_SECRET` is configured — which production startup validation now mandates, while development/test defaults stay unsigned so none of the ~15 pre-existing webhook test files needed changes. The ARI bridge (the only real caller of this endpoint today) signs its own requests using the same secret via its independent env file. `(provider, provider_event_id)` idempotency (`telephony_event_receipts`) was left untouched — it already handles legitimate duplicate deliveries; the new signing handles authenticity/replay.
- **Tests executed:** `test_telephony_webhook_auth.py` (7 tests: valid signature, missing headers, invalid signature, wrong secret, stale timestamp/replay, unsigned-when-unconfigured) — stable across 3 repeated combined runs with `test_telephony_idempotency.py` + `test_telephony_provider_config.py` + `test_telephony_webhook.py` (38/38 each run). Full suite (`pytest tests -q`): **256 passed, 10 failed** — identical 10 failures to the original baseline, zero new failures. Confirms SEC-1 and SEC-2 introduced no regressions.
- **Result:** Webhook endpoint is authenticated end-to-end once `TELEPHONY_WEBHOOK_SECRET` is set; existing Asterisk/mock integration behavior unchanged when unset (dev parity preserved).
- **Remaining risks:** `CLIENT_PROVIDER_WEBHOOK_SECRET` (documented for the separate, not-yet-implemented `client_api` outbound provider) remains unwired — out of scope until that provider's outbound path exists. Discovered an unrelated, **pre-existing** intermittent `sqlite3.InterfaceError` in `test_telephony_webhook.py` that surfaces only under heavy combined test-file load (reproduces with none of this task's files involved); logged as new backlog item **BE-9** rather than fixed here to avoid scope creep into core DB session/threading under a security task.

## 2026-08-01 — SEC-3: Stop verification-digit leakage

- **Task ID:** SEC-3
- **Files modified:**
  - `backend/app/security.py` — `mask_digits_in_text()` now performs real masking (regex over digit runs, keeps last 2 chars, `*` for the rest); was a documented no-op.
  - `backend/app/event_types.py` — added `ADMIN_ENTERED_CODE_VIEWED`.
  - `backend/app/models.py` — `CallSession.masked_entered_code` now actually masks (was `return self.entered_code`, i.e. identical to the full code); `entered_code` docstring updated to state it must never be added to a general-purpose schema.
  - `backend/app/schemas.py` — removed `entered_code` from `CallSessionRead`.
  - `backend/app/routers/calls.py` — `get_admin_entered_code` is now `async`, takes the authenticated admin, and writes an `ADMIN_ENTERED_CODE_VIEWED` audit event (admin email, no digits) before returning the plaintext.
  - `frontend/src/components/LiveProviderPanel.jsx` — "Submitted OTP" card now fetches the code through `fetchAdminEnteredCode()` (the audited endpoint) instead of reading `session.entered_code` directly off the general session object.
  - Test files updated for the new (correct) contract: `test_security_mask.py`, `test_compliance_checklist.py`, `test_admin_verification.py`, `test_dtmf_buffering.py`, `test_ivr_state_machine.py`, `test_telephony_webhook.py`.
- **Problem fixed:** Two related leaks. (1) `mask_digits_in_text()` was a no-op, so `DIGITS_RECEIVED`/`PENDING_ADMIN_VERIFICATION` event messages carried the full plaintext verification code into the persisted audit log (`call_events` table) and the live WebSocket broadcast to every connected client — directly contradicting README/compliance.py's documented masking claims. (2) Independently discovered while implementing the fix: `CallSessionRead.entered_code` returned the full decrypted code on **every** `GET /api/calls` and `GET /api/calls/{id}` response — not gated behind any deliberate "reveal" action — and the one real frontend UI that displayed it (`LiveProviderPanel.jsx`) read it from there with zero audit trail. A second, unused component (`AdminVerificationPanel.jsx`) already implemented the correct audited-fetch pattern but was never wired into the app.
- **Solution implemented:** Real masking (last-2-digits-visible) now applies uniformly to all persisted/broadcast event text — as a side effect this also fixed several `logger.info` calls in the telephony provider code that were always written expecting masking to work. `CallSessionRead` no longer carries the plaintext at all; only the masked field. The single dedicated reveal endpoint (`GET /api/calls/{id}/admin/entered-code`) is now the only path to the plaintext, and it writes its own audit event identifying the admin, without echoing the code into that audit message. The frontend's real (wired-in) reveal UI now goes through that endpoint.
- **Tests executed:** Every touched/added test verified individually (deterministic pass) and in combination; full suite `pytest tests -q` → 257 passed, 11 failed — all 11 trace to either the original 10 pre-existing baseline failures or the pre-existing BE-9 SQLite concurrency flake (independently reproduced across ~8 unrelated test names during this task's verification, always passing in isolation, absent from the very first clean baseline before any of today's changes). Zero deterministic regressions from this task. `npm run build` → clean.
- **Result:** No code path returns or persists the full verification code except the one dedicated, authenticated, now-audited endpoint.
- **Remaining risks:** None specific to this fix. BE-9 (pre-existing test flakiness) remains open and unrelated.

## 2026-08-01 — SEC-4: Remove root execution / systemd hardening

- **Task ID:** SEC-4
- **Files modified:**
  - `deploy/digitalocean/install-server.sh` — creates system user `ivr` (no login shell, no home dir), adds it to the `docker` group.
  - `deploy/digitalocean/deploy-remote.sh` — `chown -R ivr:ivr` on `backend/` and repo-root `.local/` after every deploy; `chmod 600` on both `.env` files.
  - `deploy/digitalocean/systemd/ivr-backend.service` — `User=ivr`/`Group=ivr` (was `root`); added `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, `ReadWritePaths=backend/ .local/`.
  - `deploy/digitalocean/systemd/ivr-ari-bridge.service` — same, plus `SupplementaryGroups=docker` (needs the Docker socket for `docker exec`/`docker cp` into the Asterisk container); `ReadWritePaths=.local/` only (doesn't need `backend/` write access).
  - `deploy/digitalocean/README.md` — added a staging smoke-test checklist.
- **Problem fixed:** Both services ran as root. Any RCE-class bug (a dependency CVE, a subprocess/ffmpeg issue) would execute as root on the droplet.
- **Solution implemented:** Dedicated unprivileged service account, systemd sandboxing directives, and `ReadWritePaths` scoped to exactly the filesystem paths the code actually writes to — determined by tracing every `tempfile`/`Path(__file__)`/cache-dir usage across `backend/app/services/` rather than guessing, specifically to avoid silently breaking the LuvVoice TTS cache or the Asterisk WAV staging directory the way an over-broad `ProtectSystem=strict` easily could.
- **Tests executed:** None possible in this environment — this is OS/systemd-level configuration with no droplet or root access available here. Added an explicit smoke-test checklist to the deploy README instead (service status, a write-permission probe as `ivr`, a `docker ps` probe as `ivr`, then one real end-to-end test call) and marked SEC-4 "code-complete, staging smoke test still required" rather than fully DONE without that verification.
- **Result:** No component of the deployed system runs as root except the one-time `install-server.sh`/`deploy-remote.sh` provisioning scripts themselves (which need root for systemd/nginx/package management).
- **Remaining risks:** **Must be smoke-tested on a real staging droplet before production rollout** — systemd sandboxing failure modes are silent (a service that starts fine but can't write its cache, or gets `docker: permission denied`) rather than loud. If real-call audio/prompt playback breaks after this change, the fix is almost certainly a missing `ReadWritePaths` entry or stale `docker` group membership (documented in the README).

<!-- New entries are appended below this line, most recent last, oldest first. -->

## 2026-08-01 — SEC-5: Login protection and session hardening

- **Task ID:** SEC-5
- **Files modified:**
  - `backend/app/routers/auth.py` — per-email/per-IP rolling-window lockout; persistent success/failure audit rows; generic 429 with `Retry-After`; successful-login reset boundary; logout token-version bump and commit.
  - `backend/app/auth.py`, `backend/app/models.py`, `backend/alembic/versions/0019_admin_login_attempts_and_token_version.py` — completed the already-landed JWT token-version, model, and base migration support.
  - new `backend/alembic/versions/0020_index_admin_login_attempt_ip.py` — adds the missing IP lookup index without rewriting migration 0019.
  - `backend/app/config.py` — configurable login threshold/window and default access-token lifetime reduced from 480 to 60 minutes.
  - `frontend/src/api.js` — central `authHeaders()` now sends `X-Requested-With: XMLHttpRequest` on every fetch, including direct action/blob paths.
  - `backend/.env.example`, `deploy/digitalocean/env/backend.env.template` — documented token, cookie, and login-limiter settings; production template enables `AUTH_COOKIE_SECURE=1`.
  - `backend/tests/test_admin_auth.py` — lockout/audit, enumeration resistance, reset, CSRF, revocation, cookie, and expiry coverage.
- **Problem fixed:** Login had no abuse controls or attempt audit trail, logout only cleared client state while old JWTs remained valid, and cookie-authenticated mutations had no explicit CSRF marker. The frontend's apparent Bearer flow was misleading because JavaScript cannot read the server's HttpOnly cookie; normal production calls are cookie-authenticated.
- **Solution implemented:** Persist and query login attempts by normalized email and client IP, lock after the configured number within the window, preserve audit history while treating the most recent success as a counter reset, revoke all older JWTs by incrementing `token_version`, and require/send a non-simple custom header for cookie-authenticated mutations. Kept every existing response contract other than the new expected 429 branch.
- **Tests executed:** focused auth+CORS 22/22; broader auth/config regression 29/29; SQLite migration upgrade/downgrade/re-upgrade verified, including index presence/absence; full backend suite 267 passed / 12 failed (ten known baseline failures plus two documented BE-9 SQLite concurrency flakes, zero focused regressions); `npm run build` passed (59 modules).
- **Result:** Login throttling, session revocation, production cookie flags, token expiry, and cookie-path CSRF defenses are implemented end-to-end.
- **Remaining risks:** Rate limiting is database-backed and process-safe but has no scheduled retention yet; audit rows will grow over time. Reverse-proxy deployment must preserve the real client address for per-IP limiting (the current Uvicorn/nginx path is expected to do so). Existing BE-9 and baseline test failures remain separate work.

## 2026-08-01 — BE-5: Environment-driven CORS

- **Task ID:** BE-5
- **Files modified:** `backend/app/config.py`, `backend/app/main.py`, `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`, new `backend/tests/test_cors_config.py`.
- **Problem fixed:** The API hardcoded a development-only localhost origin list with no production override, so cross-origin production deployment could not be configured correctly and could silently start with the wrong policy.
- **Solution implemented:** `CORS_ALLOWED_ORIGINS` now supplies a trimmed/de-duplicated comma-separated allowlist. Development retains the prior Vite port defaults only when the variable is unset; staging/production startup rejects a missing list, and wildcard origins are forbidden while credentials are enabled.
- **Tests executed:** `test_cors_config.py` 4/4; included in the 22-test and 29-test focused runs above; frontend production build passed.
- **Result:** Credentialed CORS is explicit in production and backward-compatible in local development.
- **Remaining risks:** Deployers must replace `https://CHANGE_ME_DOMAIN` with the actual public dashboard origin before starting production.

## 2026-08-01 — SEC-6: Encrypt SIP UP account settings at rest

- **Task ID:** SEC-6
- **Files modified:**
  - `backend/app/security.py` — reusable purpose-derived Fernet secret encryption/decryption helpers with a versioned ciphertext prefix.
  - `backend/app/config.py` — added `SIP_UP_SETTINGS_SECRET` and production startup enforcement.
  - `backend/app/services/sip_up_settings_store.py` — encrypts password before disk writes, transparently migrates legacy plaintext on read, fails closed on key mismatch, writes atomically, and applies mode `0600` to both the JSON store and required Asterisk env file.
  - `backend/tests/test_sip_up_settings_store.py`, `backend/tests/test_cors_config.py` — ciphertext, round-trip, preservation, migration, wrong-key, and production validation coverage.
  - `backend/.env.example`, `deploy/digitalocean/env/backend.env.template` — documented/provisioned the new key.
  - new `docs/runbooks/sip-credential-storage.md` — key generation, backup/recovery, file handling, and credential-rotation requirements.
- **Problem fixed:** Dashboard-edited `sip_password` was persisted verbatim in `backend/.local/sip_up_account.json`, exposing the live credential to any local file reader or backup containing that file.
- **Solution implemented:** Passwords are encrypted with a dedicated, purpose-derived Fernet key before atomic JSON replacement. Existing plaintext stores migrate on the first read without logging the value. A changed/lost key raises a clear non-secret error and leaves the ciphertext intact rather than silently erasing it. Public API behavior remains unchanged.
- **Tests executed:** focused credential/config/security suite 15/15 passed. A broader run including `test_dtmf_buffering.py` produced 19 passes and the same two pre-existing DTMF expectation failures documented in the baseline; the DTMF encryption regression tests themselves passed.
- **Result:** The dashboard settings JSON no longer persists a raw SIP password, and production cannot start without an explicit encryption key.
- **Remaining risks:** The previously exposed SIP UP password still requires client-side rotation. Asterisk still needs its operational password in the untracked `infra/sipup/.env`; permissions are restricted to `0600`, but host/root access can read it by design. Losing `SIP_UP_SETTINGS_SECRET` requires restoring the key or re-entering the SIP password.

## 2026-08-01 — BE-4: Startup environment validation

- **Task ID:** BE-4
- **Files modified:** `backend/app/config.py`, `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`, new `backend/tests/test_startup_configuration.py`, `backend/tests/test_cors_config.py`.
- **Problem fixed:** Production validation covered JWT and webhook secrets piecemeal but still allowed implicit development database/DTMF defaults, absent CORS/SIP encryption configuration, and a non-Secure auth cookie. Misconfiguration could survive import and fail later or weaken production security.
- **Solution implemented:** The existing lifespan validator now reports every missing production-wide variable together, requires `AUTH_COOKIE_SECURE=1`, and validates the CORS policy at startup. The existing telephony provider validator remains responsible for mode-specific Client API/Asterisk credentials immediately afterward. Development behavior is unchanged.
- **Tests executed:** parameterized missing-variable coverage for all seven requirements plus a complete production environment; combined startup/CORS/provider/auth suite 37/37 passed.
- **Result:** Staging/production configuration errors stop process startup with actionable variable names before database initialization or telephony work begins.
- **Remaining risks:** Validation proves presence and basic CORS/cookie semantics, not reachability of the configured database, Asterisk, or external provider; readiness probes are tracked under DEPLOY-1.

## 2026-08-01 — DB-1: Add missing call query indexes

- **Task ID:** DB-1
- **Files modified:** `backend/app/models.py`, new `backend/alembic/versions/0021_add_call_query_indexes.py`, new `backend/tests/test_database_indexes.py`.
- **Problem fixed:** Event retrieval, call history ordering/filtering, active-call checks, and cleanup queries scanned unindexed `call_events.session_id`, `call_sessions.status`, and `call_sessions.created_at` columns.
- **Solution implemented:** Declared the three indexes in SQLAlchemy metadata and added a reversible, idempotent Alembic migration after the current 0020 head. Preserved the existing telephony provider/event uniqueness constraint unchanged.
- **Tests executed:** metadata/constraint assertions plus call-history and telephony-idempotency regressions 8/8; real temporary SQLite upgrade to head, `PRAGMA index_list`, `EXPLAIN QUERY PLAN`, downgrade to 0020, and post-downgrade absence assertion all passed.
- **Result:** The documented high-frequency call/event lookup columns are indexed in fresh metadata-created databases and migrated deployments.
- **Remaining risks:** SQLite uses the status index for filtered history and a temporary B-tree for the separate `created_at` ordering. A future composite `(status, created_at)` index should be justified with production query metrics rather than added speculatively.

## 2026-08-01 — DB-4: SQLite backup and restore procedure

- **Task ID:** DB-4
- **Files modified:** new `scripts/backup_sqlite.sh`, new `deploy/digitalocean/systemd/ivr-backup.service`, new `deploy/digitalocean/systemd/ivr-backup.timer`, `deploy/digitalocean/deploy-remote.sh`, `deploy/digitalocean/README.md`, new `docs/runbooks/backup-restore.md`.
- **Problem fixed:** Production had no consistent online backup, integrity validation, retention schedule, off-box transfer contract, or tested restore instructions. Copying the live SQLite file directly could produce an inconsistent backup.
- **Solution implemented:** A hardened daily oneshot runs as `ivr`, uses Python's SQLite online backup API, validates the completed snapshot, atomically publishes private files, and prunes local backups after 14 days. An executable upload hook provides a failure-aware boundary for DO Spaces/rsync integration without committing provider credentials. The runbook covers operations and a controlled restore.
- **Tests executed:** Created a SQLite fixture, ran the actual shell script under Git Bash, independently reopened the generated snapshot, verified `PRAGMA integrity_check = ok` and the expected row, then removed test artifacts. `bash -n` passed for the backup and deploy scripts.
- **Result:** Deployments install and enable a daily, integrity-checked SQLite backup schedule with explicit local/off-box retention and restore instructions.
- **Remaining risks:** No systemd or staging droplet is available here. Operators must configure the real off-box upload hook/credentials and complete the documented staging restore/migration/test-call drill before considering disaster recovery proven.
