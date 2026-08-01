# Asterisk dry-run — Session 001

**Purpose:** Pre-filled QA worksheet for a **local manual Asterisk IVR dry-run**. Derived from [`manual-ivr-test-report-template.md`](manual-ivr-test-report-template.md). Complete blank fields during the run; do not commit secrets or full phone numbers.

---

## Dry-run command checklist

Run in order (adjust paths to your clone):

- [ ] `cd backend && alembic upgrade head`
- [ ] From repo root: `PYTHONPATH=backend python3 -m pytest backend/tests -q` (all green before manual run)
- [ ] Start backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Start SIP UP stack Docker stack: `cd infra/sipup && docker compose up -d` (configs copied from `*.example` per [`infra/sipup/README.md`](../../infra/sipup/README.md))
- [ ] Register SIP softphone (RFC 4733 DTMF) against the stack
- [ ] Create call from dashboard (or `POST /api/calls/start`) and note `call_id` / `demo_code` if shown
- [ ] Follow step-by-step flow, webhooks, and negatives in [`docs/runbooks/asterisk-local-dry-run.md`](../runbooks/asterisk-local-dry-run.md)

---

## Pass criteria

The dry-run **passes** when all of the following hold:

- [ ] **Live dashboard:** All **expected** event types for each scenario appear in order (WebSocket / Live logs), consistent with [`asterisk-local-dry-run.md`](../runbooks/asterisk-local-dry-run.md).
- [ ] **Masking:** DTMF-related event **messages** show **masked** digit runs (no full raw 6-digit code in log text).
- [ ] **`demo_code`:** Appears only because **`APP_ENV=development`** (API start response + dashboard banner); not expected in staging/production-like configs.
- [ ] **Idempotency:** Replaying the same **`provider` + `provider_event_id`** returns **`duplicate_ignored`** and does **not** double-apply state, buffer, or verification attempts.
- [ ] **Admin review:** After 6 digits, the call enters **pending admin verification** and does not emit **`VERIFICATION_SUCCESS`** until the admin clicks **Approve**. **Reject** returns to retry or fails at the max attempt count.
- [ ] **Terminal DTMF:** After a **completed** (or otherwise terminal) call, an extra **`DTMF`** webhook returns **noop** (no new meaningful state).
- [ ] **Stability:** No unhandled backend errors / 500s during the scripted scenarios.
- [ ] **No plaintext code in normal logs:** **`GET /api/calls/{call_id}/events`** and dashboard log text must **not** contain the full official verification code. The pending DTMF buffer is encrypted at rest; events and UI review display masked digits only.

---

## Report metadata

| Field | Value |
|-------|-------|
| **Tester** | |
| **Date / time** | (timezone) |
| **Environment** | **local Asterisk** |
| **Git commit** | `git rev-parse HEAD` |
| **Backend version** | |
| **Frontend version** | |
| **Provider used** | **`asterisk`** (webhook `provider` field; see runbook) |
| **`APP_ENV`** | **development** (expect `demo_code` in start response when using default dev config) |
| **Test type** | **Local manual dry-run** |
| **Test phone number (masked)** | |
| **`call_id`** | |
| **`provider_call_id`** | |
| **`provider_event_id`s used** | |

---

## Session summary (per scenario)

Use one row per scenario, or copy the table for additional runs.

| # | Scenario | Expected result | Actual result | Pass / fail | Screenshots | Issues |
|---|----------|-----------------|---------------|-------------|-------------|--------|
| 1 | Happy path | | | | | |
| 2 | Decline at consent | | | | | |
| 3 | Admin reject ×3 | | | | | |
| 4 | Hangup during verification | | | | | |
| 5 | Duplicate `provider_event_id` | | | | | |
| 6 | DTMF after completed call | | | | | |

---

## Dashboard events observed

Paste or summarize from Live logs / `GET /api/calls/{call_id}/events` (order matters). Add rows as needed.

| # | Timestamp (approx.) | Event type | Actor | Masked payload (summary) |
|---|---------------------|------------|-------|---------------------------|
| 1 | | | | |
| 2 | | | | |
| … | | | | |

---

## Scenarios (Session 001 scope)

Complete **expected / actual / pass-fail / notes** for each run. Use a **fresh `call_id`** where the scenario requires a clean session.

### 1. Happy path

- **Description:** Answer (or post **`ANSWERED`** for `call_id`) → **`DTMF` `1`** (consent accept) → enter internal 6-digit code **one digit per** **`DTMF`** webhook → dashboard shows **Pending admin verification** with masked digits only → admin clicks **Approve** → verification success / completed.
- **Expected result:** **`DIGITS_RECEIVED`** then **`PENDING_ADMIN_VERIFICATION`**; no **`VERIFICATION_SUCCESS`** before approval; approval emits **`ADMIN_VERIFICATION_APPROVED`** then **`VERIFICATION_SUCCESS`**.
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

### 2. Negative path — consent declined

- **Description:** Answer → **`DTMF` `2`** (decline).
- **Expected result:** |
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

### 3. Negative path — admin rejects three times

- **Description:** Answer → **`1`** → enter a full 6-digit sequence → admin clicks **Reject**. Repeat until the third rejection reaches max attempts / failed terminal state.
- **Expected result:** Each review emits **`ADMIN_VERIFICATION_REJECTED`**; attempts remaining return to **`verification_code`**; third rejection fails the call.
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

### 4. Negative path — hangup during verification

- **Description:** Answer → **`1`** → partial or zero verification digits → **`HANGUP`** (or provider equivalent).
- **Expected result:** |
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

### 5. Idempotency — duplicate `provider_event_id`

- **Description:** Send a webhook with a given **`provider_event_id`**, then replay the **identical** payload (same `provider`, `provider_event_id`, and body).
- **Expected result:** Second response **`status`: `duplicate_ignored`**; no duplicate state.
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

### 6. Terminal event — DTMF after completed call

- **Description:** Complete **happy path** for a session until terminal **completed** (or **failed**). Then send another **`DTMF`**.
- **Expected result:** Response **noop** / ignored; no new verification-related events.
- **Actual result:** |
- **Pass / fail:** |
- **Notes:** |

---

## Optional follow-ups (not required for Session 001)

Additional cases from the master template (wrong-then-success, hangup at consent, rate limit, masking-only pass) may be logged in a separate session file if needed.

---

## Sign-off (optional)

| Role | Name | Date |
|------|------|------|
| Tester | | |
| Reviewer | | |
