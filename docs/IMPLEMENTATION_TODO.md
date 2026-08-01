# IVR Platform Improvement Plan

## Progress Summary

- Total tasks: 34
- Completed: 10 (SEC-1, SEC-2, SEC-3, SEC-4 code-complete pending staging smoke test, SEC-5, SEC-6 code-complete pending credential rotation, BE-4, BE-5, DB-1, DB-4 code-complete pending staging restore drill)
- In progress: 0
- Blocked: 1 (DB-2, pending client answer)
- Remaining: 23

_Last updated: 2026-08-01_

## Baseline (recorded before any implementation)

- `backend/.venv` was created on a different machine (`C:\Users\dev\...`) and its Python launcher was broken; recreated locally with Python 3.10 (build artifact, not source — safe to regenerate).
- `PYTHONPATH=. pytest tests -q`: **249 passed, 10 failed** (pre-existing, unrelated to any change made so far — see SEC-7 below). Full backend test file count: 30.
- `npm run build`: **passes**, 59 modules, ~240KB JS / 44KB CSS gzipped, ~5-50s build time.
- **Incidental finding during baseline (not part of the original audit):** `backend/.local/sip_up_account.json` contains a real-looking, plaintext SIP UP account (username/password/caller ID) persisted on disk from prior manual testing. It is correctly `.gitignore`d and **not committed to git** (verified via `git ls-files` / `git check-ignore`), so this is a local-machine exposure, not a repo leak. However, a redaction command I ran had a regex bug and the password briefly appeared in this session's tool output/transcript. **Recommend rotating that SIP UP account password as a precaution.** Tracked as SEC-6/SEC-7 below.

---

## Phase 1 — Critical Security

### SEC-1 — Close public admin self-registration
- **Priority:** Critical
- **Status:** DONE
- **Files affected:** `backend/app/routers/auth.py`, `frontend/src/components/LoginScreen.jsx`, `frontend/src/api.js`, `backend/tests/test_admin_auth.py`
- **Dependencies:** none
- **Validation criteria:** ✅ `POST /api/auth/register` now requires `Depends(get_current_admin)` in every environment (no dev bypass — the existing `scripts/create_admin.py` CLI remains the sole first-admin bootstrap, already documented in README); an authenticated admin can create another admin without their own session being swapped to the new admin's token (register no longer issues a token/sets a cookie — it returns `AdminRead` only); public frontend has zero register affordance.
- **Tests required:** ✅ `test_register_rejects_anonymous_caller` (401), `test_authenticated_admin_can_create_new_admin` (201, no `access_token` in body, caller's `/auth/me` still shows original admin, new admin can log in independently), `test_register_rejects_duplicate_email` / `test_register_rejects_weak_password` (updated to use the authenticated fixture client).
- **Notes:** Confirmed in prior audit: endpoint had zero auth guard and the login screen exposed a public toggle. Chose CLI-only bootstrap over an API "zero-admins" bootstrap path to avoid a first-deploy registration race condition. `backend/tests/test_admin_auth.py`: 11/11 passing. `npm run build`: clean.

### SEC-2 — Authenticate/verify telephony webhook
- **Priority:** Critical
- **Status:** DONE
- **Files affected:** new `backend/app/webhook_security.py`, `backend/app/config.py`, `backend/app/routers/telephony.py`, `backend/app/services/sip_up_ari_bridge.py`, `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`, `deploy/digitalocean/env/sipup.env.template`, new `backend/tests/test_telephony_webhook_auth.py`
- **Dependencies:** none
- **Validation criteria:** ✅ `POST /api/telephony/events` requires `X-Webhook-Timestamp` + `X-Webhook-Signature` (HMAC-SHA256 over `"{timestamp}." + raw_body`, constant-time compare) whenever `TELEPHONY_WEBHOOK_SECRET` is configured; unsigned requests are still accepted when the secret is unset (dev/test default — zero changes needed to the ~15 existing webhook test files, which never set the secret); `config.validate_auth_configuration()` now fails startup in staging/production if the secret is missing; the ARI bridge (`sip_up_ari_bridge.py::_post_backend_event`) signs every outbound event when `TELEPHONY_WEBHOOK_SECRET` is set in its own env; existing `(provider, provider_event_id)` idempotency table untouched and still returns `duplicate_ignored` for legitimate provider retries.
- **Tests required:** ✅ valid signature accepted, missing headers rejected (401), invalid signature rejected (401), wrong secret rejected (401), stale timestamp rejected (401, replay protection), unsigned-when-unconfigured still works (regression guard). All in `test_telephony_webhook_auth.py`, verified stable across 3 repeated full-file runs.
- **Notes:** `CLIENT_PROVIDER_WEBHOOK_SECRET` (mentioned in README for the separate, not-yet-wired `client_api` provider mode) was documented but never checked anywhere — left as-is/out of scope, since no `client_api` outbound code path exists yet to attach it to. This task introduces a distinct `TELEPHONY_WEBHOOK_SECRET`, which is the one thing that's actually called today (our own ARI bridge → our own webhook). During verification, hit a **pre-existing, intermittent** `sqlite3.InterfaceError` in `test_telephony_webhook.py` when run under heavy combined-file load — reproduced with zero files of mine involved, tracked separately as BE-9 rather than fixed under this task (out of scope: core DB session/threading, not webhook auth).

### SEC-3 — Stop verification-digit leakage
- **Priority:** Critical
- **Status:** DONE
- **Files affected:** `backend/app/security.py`, `backend/app/event_types.py`, `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/routers/calls.py`, `frontend/src/components/LiveProviderPanel.jsx`, `backend/tests/test_security_mask.py`, `backend/tests/test_compliance_checklist.py`, `backend/tests/test_admin_verification.py`, `backend/tests/test_dtmf_buffering.py`, `backend/tests/test_ivr_state_machine.py`, `backend/tests/test_telephony_webhook.py`
- **Dependencies:** none
- **Validation criteria:** ✅ `mask_digits_in_text()` now masks every digit run to only its last 2 digits (e.g. `123456` → `****56`) — applied automatically to every persisted `CallEvent.message` and WS broadcast via the existing `call_service.add_event` call site, and as a side effect now also correctly masks phone numbers in the telephony provider log lines that were always written expecting this. ✅ `CallSessionRead` (the general list/detail schema returned by `GET /api/calls` and `GET /api/calls/{id}`) no longer includes `entered_code` at all — only the now-properly-masked `masked_entered_code`. ✅ `GET /api/calls/{id}/admin/entered-code` remains the sole plaintext source, and now writes a `ADMIN_ENTERED_CODE_VIEWED` audit `CallEvent` (naming the admin's email, no digits) on every access. ✅ Frontend's only real reveal UI (`LiveProviderPanel.jsx`'s "Submitted OTP" card — found to be reading the plaintext directly off the general session object with no audit trail) now fetches through the dedicated endpoint instead, so every reveal is logged.
- **Tests required:** ✅ `test_security_mask.py` rewritten for real masking behavior (was asserting the no-op passthrough). ✅ `test_compliance_checklist.py::test_digits_received_events_never_store_full_code_in_message` (renamed/inverted from a test that asserted the leak). ✅ `test_admin_verification.py::test_admin_reject_actor_and_code_masked_in_persisted_events` (renamed/inverted, same reason) + new assertions in `test_admin_can_fetch_full_entered_code_after_approval` proving the `ADMIN_ENTERED_CODE_VIEWED` audit event fires. ✅ Updated 4 more test files (`test_dtmf_buffering.py`, `test_ivr_state_machine.py`, `test_telephony_webhook.py`) whose `masked_entered_code`/`entered_code` assertions assumed the old unmasked/always-present behavior.
- **Notes:** Wider blast radius than the original audit flagged: beyond the `CallEvent.message` leak, `CallSessionRead.entered_code` was silently returning the full decrypted code on **every** `GET /api/calls` (history list) and `GET /api/calls/{id}` call — not just a deliberate reveal action. Also found `AdminVerificationPanel.jsx` (a component that already correctly used the dedicated audited-reveal pattern) is dead code, never imported anywhere — the actually-wired `LiveProviderPanel.jsx` was doing the insecure direct-field read instead. Full suite after this task: 257 passed; all 11 failures trace to the original 10 pre-existing baseline items or the already-documented BE-9 flake — zero deterministic regressions.

### SEC-4 — Remove root execution / systemd hardening
- **Priority:** High
- **Status:** DONE (code/config complete — **staging smoke test still required**, see Notes)
- **Files affected:** `deploy/digitalocean/systemd/ivr-backend.service`, `deploy/digitalocean/systemd/ivr-ari-bridge.service`, `deploy/digitalocean/install-server.sh`, `deploy/digitalocean/deploy-remote.sh`, `deploy/digitalocean/README.md`
- **Dependencies:** none (independent of app code)
- **Validation criteria:** ✅ Both services run as a dedicated unprivileged `ivr` system user (was `root`); ✅ `install-server.sh` creates the user and grants `docker` group membership (needed for the ARI bridge's `docker exec`/`docker cp` calls — verified by tracing every filesystem write in the backend and bridge code first, see Notes); ✅ `deploy-remote.sh` chowns exactly the directories the app writes to (`backend/` and repo-root `.local/`) to `ivr:ivr` and `chmod 600`s both `.env` files on every deploy; ✅ hardening directives added (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, narrowly-scoped `ReadWritePaths`).
- **Tests required:** Not unit-testable (systemd sandboxing is OS/root-level). Added an explicit smoke-test checklist to `deploy/digitalocean/README.md` (`systemctl status`, a write-permission probe as the `ivr` user, a `docker ps` probe as the `ivr` user, then one real end-to-end test call) — **this must be run once on a staging droplet before the next production deploy**; I have no droplet/root access in this environment to run it myself.
- **Notes:** Mapped every filesystem path the backend and ARI bridge actually write to by reading the code rather than guessing (`grep` for `tempfile`/`Path(__file__)`/cache-dir patterns across `backend/app/services/`): SQLite DB + `backend/.local/sip_up_account.json` (backend only), repo-root `.local/tts-cache` (both services — shared LuvVoice cache), repo-root `.local/asterisk-ivr/dyn` (bridge only — WAVs staged for `docker cp`). `tempfile.mkstemp()` calls elsewhere use the OS temp dir, which `PrivateTmp=true` already makes writable per-service without needing an explicit `ReadWritePaths` entry. `ProtectSystem=strict` deliberately leaves the venv and app code read-only (not read-write) since nothing writes there.

### SEC-5 — Login protection & session hardening
- **Priority:** High
- **Status:** DONE
- **Files affected:** `backend/app/routers/auth.py`, `backend/app/auth.py`, `backend/app/models.py`, `backend/app/config.py`, `backend/alembic/versions/0019_admin_login_attempts_and_token_version.py`, `backend/alembic/versions/0020_index_admin_login_attempt_ip.py`, `backend/tests/test_admin_auth.py`, `frontend/src/api.js`, `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`
- **Dependencies:** SEC-1 (shares auth.py)
- **Validation criteria:** ✅ Failed logins are counted independently by normalized email and client IP over a configurable window (`LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5`, `LOGIN_RATE_LIMIT_WINDOW_MINUTES=15` defaults); the next request receives a generic 429 plus `Retry-After`, and every accepted/rejected attempt is persisted in `admin_login_attempts`. ✅ A successful attempt resets the effective counters by acting as a timestamp boundary while preserving the audit history. ✅ Login failures use the same 401 body for known and unknown accounts. ✅ Logout increments `AdminUser.token_version`, commits it, clears the cookie, and invalidates every older JWT. ✅ Cookie remains `HttpOnly`, `SameSite=Lax`, and is `Secure` when `AUTH_COOKIE_SECURE=1`; default token/cookie lifetime reduced from 480 to 60 minutes. ✅ Cookie-authenticated mutating requests require `X-Requested-With: XMLHttpRequest`; Bearer requests remain exempt. Frontend sends the header centrally on all API fetches.
- **Tests required:** ✅ lockout after threshold + attempt audit count, generic error/no user enumeration, successful-login counter reset, CSRF rejected/accepted, old JWT rejected after logout, cookie flags with `AUTH_COOKIE_SECURE=1`, expired-token rejection. `test_admin_auth.py` + `test_cors_config.py` focused run: 22/22; broader auth/config run: 29/29.
- **Notes:** Confirmed the frontend's apparent Bearer path is normally inactive: the server sets `ivr_admin_access_token` as `HttpOnly`, so `document.cookie`/`getAuthToken()` cannot read it; deployed browser calls therefore rely on `credentials: "include"` cookie auth. This makes the CSRF header necessary on normal mutations, not an edge path. Added migration 0020 rather than modifying landed migration 0019 so the IP-based limiter has its declared database index; verified SQLite upgrade/downgrade/re-upgrade. Full backend suite after completion: 267 passed, 12 failed (the ten documented baseline failures plus two BE-9 `sqlite3.InterfaceError` flakes); no SEC-5/BE-5 focused failures. `npm run build`: clean.

### SEC-6 — Encrypt/rotate SIP UP account settings at rest
- **Priority:** High
- **Status:** DONE (code complete — **client credential rotation still required**, see Notes)
- **Files affected:** `backend/app/security.py`, `backend/app/config.py`, `backend/app/services/sip_up_settings_store.py`, `backend/tests/test_sip_up_settings_store.py`, `backend/tests/test_cors_config.py`, `backend/.env.example`, `deploy/digitalocean/env/backend.env.template`, new `docs/runbooks/sip-credential-storage.md`
- **Dependencies:** none
- **Validation criteria:** ✅ `backend/.local/sip_up_account.json` stores `sip_password` as purpose-derived Fernet ciphertext under a dedicated `SIP_UP_SETTINGS_SECRET`; legacy plaintext is automatically rewritten on first read; writes are atomic and restricted to mode `0600`; wrong/missing key behavior fails closed without overwriting recoverable ciphertext. ✅ Production startup requires an explicit encryption key. ✅ Runtime `env_lookup()` still returns the decrypted value to telephony code and public API responses expose only `password_present`. ⏳ The real credential found on this checkout must still be rotated by the client in the SIP UP control panel.
- **Tests required:** ✅ `test_sip_up_settings_store` asserts raw password absence, runtime round-trip, blank update preservation, legacy migration, and wrong-key failure. Focused credential/config/security suite: 15/15 passing.
- **Notes:** Discovered during baseline, not the original audit — a real-looking SIP UP username/password/caller-ID was found persisted in plaintext at `backend/.local/sip_up_account.json`. Confirmed **not committed to git** (`.gitignore`d, verified via `git ls-files`/`git check-ignore`), so this is a local-disk exposure, not a repo leak. Encryption prevents future plaintext JSON storage but cannot revoke a credential previously exposed; the client rotation remains mandatory. `infra/sipup/.env` necessarily remains an Asterisk-consumed secret file and is now forced to `0600`; handling is documented in `docs/runbooks/sip-credential-storage.md`.

### SEC-7 — Fix test isolation for SIP UP settings store
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/tests/conftest.py`, `backend/app/services/sip_up_settings_store.py`
- **Dependencies:** none
- **Validation criteria:** `pytest` no longer reads the real `backend/.local/sip_up_account.json` file — the `client`/`test_engine` fixtures should redirect the settings-store path to a temp file (or monkeypatch `env_lookup`) so test outcomes never depend on whatever was last saved on the developer's machine.
- **Tests required:** none new; this fixes the flakiness of `test_outbound_provider_selection.py`'s 4 failing caller-ID assertions.
- **Notes:** Root cause of 4 of the 10 baseline test failures: `env_lookup()` in `sip_up_settings_store.py` prefers a persisted local JSON settings file over `os.environ`, so a real caller ID (`491631115421`) saved during prior manual dry-runs overrides the `SIPUP_OUTBOUND_CALLER_ID=18006983228` value the test fixture monkeypatches. The other 6 baseline failures (`test_dtmf_buffering.py` x2, `test_luvvoice_tts.py`, `test_outbound_spacing.py`, `test_speech_volume.py`, `test_virtual_call_device.py`) look like separate pre-existing defaults/config drift (e.g. `DEFAULT_SPEECH_VOLUME_PERCENT` expected 88 in schema docs but is 70 in `speech_volume.py`) — will triage each individually under BE-7/BE-8 rather than lumping them here; none are related to Task 2's changes.

---

## Phase 2 — Backend Stability

### BE-9 — Investigate intermittent SQLite `InterfaceError` under concurrent test load
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/tests/conftest.py` (StaticPool engine setup), `backend/app/database.py`, `backend/app/services/call_service.py` (`add_event`'s `asyncio.gather` broadcast)
- **Dependencies:** none
- **Validation criteria:** Full `pytest tests -q` passes reliably across repeated runs with no `sqlite3.InterfaceError: Cursor needed to be reset because of commit/rollback...` failures.
- **Tests required:** none new — this is about eliminating flakiness in the existing suite, not adding coverage.
- **Notes:** Discovered while verifying SEC-2 in combination with other telephony test files — reproduces intermittently in `test_telephony_webhook.py` (a file untouched by SEC-2) purely from being run alongside enough other tests in the same process; does not reproduce reliably in isolation. Likely cause: SQLite `StaticPool` (single shared connection, `check_same_thread=False`) combined with `call_service.add_event`'s `asyncio.gather()` of multiple WebSocket broadcasts plus `asyncio.to_thread` calls elsewhere in the app creates cross-thread access to the same SQLite connection/cursor without serialization. Needs its own investigation (likely fix: serialize DB commits behind a lock in the test engine, or move the test suite off `StaticPool` to a per-request connection) — not attempted here to avoid scope creep into core session handling under a security task.

### BE-1 — Standardize API response envelope
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/app/main.py`, new `backend/app/response.py`, all routers
- **Dependencies:** SEC-1..SEC-3 land first (avoid churn on files being security-patched)
- **Validation criteria:** All new/touched endpoints return `{success, data|error, requestId}`; existing frontend consumers updated in the same commit; no breaking change to endpoints not yet touched (documented as a gradual migration, not a big-bang rewrite).
- **Tests required:** response-shape tests per touched endpoint.
- **Notes:** Given "do not change an API contract without updating all frontend consumers," this will be rolled out endpoint-by-endpoint alongside the pages that consume them (Phase 4), not as a single mass change.

### BE-2 — Centralized exception handling
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/app/main.py` (exception handlers), `backend/app/exceptions.py`
- **Dependencies:** BE-1
- **Validation criteria:** No stack traces leak in non-debug mode; every domain exception maps to a stable error code + correct HTTP status.
- **Tests required:** one test per exception → status/code mapping.

### BE-3 — Request IDs + structured logging
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/app/main.py` (middleware), all routers/services logging calls
- **Dependencies:** none
- **Validation criteria:** Every response has `X-Request-Id`; logs are structured (JSON or key=value) with no secrets/full phone/full code.
- **Tests required:** middleware test asserting header presence + propagation into logs.

### BE-4 — Startup environment validation
- **Priority:** High
- **Status:** DONE
- **Files affected:** `backend/app/config.py`, `backend/app/telephony_provider_config.py`, `backend/app/main.py`
- **Dependencies:** SEC-2 (webhook secret becomes a required var)
- **Validation criteria:** ✅ Staging/production startup rejects missing/blank `DATABASE_URL`, `JWT_SECRET_KEY`, `DTMF_BUFFER_SECRET`, `TELEPHONY_WEBHOOK_SECRET`, `CORS_ALLOWED_ORIGINS`, or `SIP_UP_SETTINGS_SECRET` in one clear error listing every missing name; requires `AUTH_COOKIE_SECURE=1`; parses CORS immediately so wildcard configuration also fails fast. ✅ Existing provider-specific startup validation remains the second stage and rejects missing Client API or Asterisk credentials. ✅ Development retains its local DB/JWT/DTMF defaults and explicit warnings for insecure webhook/JWT settings.
- **Tests required:** ✅ parameterized `test_startup_fails_without_required_prod_env` covers all seven production requirements, plus complete-production acceptance; combined startup/CORS/provider/auth suite 37/37 passing.
- **Notes:** Extended the existing `validate_auth_configuration()` + `validate_telephony_provider_configuration_on_startup()` lifespan sequence instead of adding a competing validation framework. Deployment template now includes the previously undocumented required DTMF encryption key.

### BE-5 — Environment-driven CORS
- **Priority:** High
- **Status:** DONE
- **Files affected:** `backend/app/main.py`, `backend/app/config.py`, `.env.example`, `deploy/digitalocean/env/backend.env.template`
- **Dependencies:** BE-4
- **Validation criteria:** ✅ `CORS_ALLOWED_ORIGINS` is parsed as a comma-separated, trimmed, de-duplicated list and drives `CORSMiddleware`; development keeps the localhost/127.0.0.1 ports 5173-5189 default; staging/production startup requires an explicit non-empty value; `*` is rejected because credentials are enabled.
- **Tests required:** ✅ `test_cors_origins_from_env`, development-default, wildcard-rejection, and production-required tests in `backend/tests/test_cors_config.py` (4/4 passing).
- **Notes:** Implemented with SEC-5 because cookie-only browser auth makes credentialed CORS configuration part of the same security boundary. Documented in both backend env examples/templates.

### BE-6 — Full endpoint review pass
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** all `backend/app/routers/*.py`
- **Dependencies:** BE-1, BE-2
- **Validation criteria:** Checklist (auth/authz/validation/status codes/error format/idempotency/logging) completed and signed off per endpoint in the changelog.
- **Tests required:** gap-filling tests wherever the review finds a missing case.

### BE-7 — IVR state machine review
- **Priority:** High
- **Status:** TODO
- **Files affected:** `backend/app/ivr_state.py`, `backend/app/services/call_service.py`, `backend/tests/test_ivr_state_machine.py`
- **Dependencies:** none
- **Validation criteria:** Confirm (with new tests, not behavior changes) that invalid transitions raise `InvalidIvrTransition`, duplicate webhook events are no-ops via `telephony_event_receipts`, max-3-attempts is enforced, consent gates code entry, terminal states reject further events. **No behavior change unless a defect is proven** — this is a verification pass, not a rewrite.
- **Tests required:** targeted regression tests for each guarantee above (some already exist and will be extended, not replaced).

---

## Phase 3 — Database

### DB-1 — Add missing indexes
- **Priority:** High
- **Status:** DONE
- **Files affected:** new `backend/alembic/versions/0021_add_call_query_indexes.py`, `backend/app/models.py`, new `backend/tests/test_database_indexes.py`
- **Dependencies:** none
- **Validation criteria:** ✅ Indexes exist on `call_events.session_id`, `call_sessions.status`, and `call_sessions.created_at` in both ORM metadata and migration 0021. ✅ Existing `uq_telephony_event_receipt_provider_event` uniqueness is unchanged and covered by a metadata regression assertion. ✅ Migration is idempotent for partially provisioned schemas and `downgrade()` removes only the three new indexes.
- **Tests required:** ✅ Real temporary SQLite upgrade to head, index inspection, query-plan smoke check, downgrade to 0020, and absence inspection all passed. Metadata/history/idempotency focused suite: 8/8 passing.
- **Notes:** The TODO's anticipated revision number 0019 was already consumed by SEC-5; this task correctly follows the current chain as 0021 after SEC-5's 0020 IP index. SQLite query plans confirmed `ix_call_events_session_id` for event lookup and `ix_call_sessions_status` for active/status filtering.

### DB-2 — Resolve `exam_date` dead field
- **Priority:** Low
- **Status:** TODO
- **Files affected:** `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/services/call_service.py`, docs
- **Dependencies:** client decision (see Questions for the client in prior audit) — **BLOCKED until client answers**
- **Validation criteria:** Field is either wired into `CallStartRequest`/consent prompt, or removed via a documented migration that doesn't touch unrelated columns.
- **Tests required:** whichever path is chosen gets a migration up/down test.
- **Notes:** Defaulting to "deprecate, do not remove yet" until client confirms — documented as a decision, not silently dropped.

### DB-3 — FK cascade / deletion integrity review
- **Priority:** Low
- **Status:** TODO
- **Files affected:** `backend/app/models.py`, `backend/app/routers/calls.py` (`delete_call`), new migration
- **Dependencies:** DB-1
- **Validation criteria:** `ondelete="CASCADE"` added to child FKs where safe; `delete_call` simplified or kept as an explicit safety net (both acceptable — decide during implementation and document choice).
- **Tests required:** deleting a session removes all child rows, no orphans.

### DB-4 — SQLite backup/restore procedure
- **Priority:** High
- **Status:** DONE (code/procedure complete — **staging restore drill still required**)
- **Files affected:** new `scripts/backup_sqlite.sh`, new `deploy/digitalocean/systemd/ivr-backup.timer` + `.service`, `deploy/digitalocean/deploy-remote.sh`, `deploy/digitalocean/README.md`, new `docs/runbooks/backup-restore.md`
- **Dependencies:** none
- **Validation criteria:** ✅ Uses Python's SQLite online `Connection.backup()` API against the live database, writes to a private temporary file, runs `PRAGMA integrity_check`, then atomically publishes the snapshot. ✅ Daily systemd timer, 14-day local retention, `0600` files, failure propagation, and executable `BACKUP_UPLOAD_SCRIPT` off-box hook are implemented. ✅ Restore procedure, off-box lifecycle guidance, monthly recovery checks, and staging validation evidence requirements are documented. ⏳ The full stop/restore/migrate/start/test-call drill still requires a staging droplet.
- **Tests required:** ✅ Git Bash dry run created a snapshot from a SQLite fixture; independent reopen returned `integrity: ok` and the expected row. `bash -n` passed for both the backup and modified deploy scripts.
- **Notes:** The deploy script now creates/chowns `.local/backups`, installs/enables the timer, and the hardened oneshot service writes only to that directory. No raw copy of a live database is used. This workstation has no systemd/staging droplet, so timer execution and the documented restore drill remain operational sign-off items.

### DB-5 — PostgreSQL migration readiness (planning doc only)
- **Priority:** Low
- **Status:** TODO
- **Files affected:** new `docs/runbooks/postgres-migration-plan.md`
- **Dependencies:** none
- **Validation criteria:** Document covers schema conversion, data export/import, validation, rollback, downtime strategy, env changes, perf testing. **No code migration performed now** — SQLite remains default for dev/tests/current prod scale.
- **Tests required:** none (documentation only).

---

## Phase 4 — Frontend Redesign

### FE-1 — Design tokens + Tailwind config
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `frontend/tailwind.config.js`, new `frontend/src/styles/tokens.css`, `frontend/index.html` (font loading)
- **Dependencies:** SEC-1 (auth UI changes land together)
- **Validation criteria:** Centralized color/spacing/radius/shadow/typography tokens; single font family (Inter or Plus Jakarta Sans) loaded once.

### FE-2 — Application shell (sidebar, header, mobile nav)
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new `frontend/src/components/layout/*`, `frontend/src/App.jsx`
- **Dependencies:** FE-1

### FE-3 — Shared UI primitives
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new `frontend/src/components/ui/*` (Badge, DataTable, Dialog, Pagination, PageHeader, Toast, Skeleton, FormField)
- **Dependencies:** FE-1

### FE-4 — Auth UI redesign (no public register in prod)
- **Priority:** Critical (tied to SEC-1)
- **Status:** TODO
- **Files affected:** `frontend/src/components/LoginScreen.jsx`
- **Dependencies:** SEC-1, FE-1, FE-3

### FE-5 — Dashboard page
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new `frontend/src/pages/DashboardPage.jsx`, backend: new `GET /api/system/stats` if no aggregate endpoint exists
- **Dependencies:** FE-2, FE-3
- **Notes:** Must use real backend data — will require a small new read-only stats endpoint (audited in Task 9 planning) rather than fabricated numbers.

### FE-6 — New verification flow
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** rework of existing `CallForm`-equivalent component
- **Dependencies:** FE-2, FE-3

### FE-7 — Active call workspace (state timeline, approve/reject, secure reveal)
- **Priority:** High
- **Status:** TODO
- **Files affected:** rework of `LiveProviderPanel.jsx` and related components
- **Dependencies:** SEC-3 (reveal endpoint semantics), FE-2, FE-3

### FE-8 — Call history + detail drawer
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new history page/components
- **Dependencies:** FE-2, FE-3

### FE-9 — Speech scripts + telephony settings pages
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** rework of existing speech-script editor and SIP account settings UI
- **Dependencies:** FE-2, FE-3

---

## Phase 5 — Testing

### TEST-1 — Backend regression + new security tests
- **Priority:** Critical
- **Status:** TODO
- **Files affected:** `backend/tests/*`
- **Dependencies:** all Phase 1-3 tasks
- **Validation criteria:** `pytest -q` green, including every new test listed under SEC-1..BE-7/DB-1..DB-5.

### TEST-2 — Frontend tests + CI
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new `frontend/src/**/*.test.jsx`, `frontend/vitest.config.js` (or equivalent), new `.github/workflows/ci.yml`
- **Dependencies:** Phase 4 complete
- **Validation criteria:** `npm run lint`, `npm run test`, `npm run build` all green in CI.

---

## Phase 6 — Deployment

### DEPLOY-1 — Health endpoints
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `backend/app/routers/system.py` (or new `health.py`), `backend/app/main.py`
- **Dependencies:** none
- **Validation criteria:** `GET /api/health/live` always 200 if process is up; `GET /api/health/ready` checks DB connectivity + required config, returns 503 if not ready, never leaks secrets.

### DEPLOY-2 — CI workflow
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** new `.github/workflows/ci.yml`
- **Dependencies:** TEST-1, TEST-2

### DEPLOY-3 — Deployment documentation refresh
- **Priority:** Medium
- **Status:** TODO
- **Files affected:** `deploy/digitalocean/README.md`, `docs/runbooks/*`
- **Dependencies:** SEC-4, DB-4, DEPLOY-1

---

## Legend
- **Status values:** TODO, IN PROGRESS, BLOCKED, DONE
- Update this file after every completed task; log the corresponding entry in `docs/CHANGELOG_IMPLEMENTATION.md`.
