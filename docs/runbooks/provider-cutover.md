# Runbook: Provider cutover (mock / local Asterisk → client telephony API)

Safe plan to move outbound verification from **`MockTelephonyProvider`** (and optional local Asterisk dry-runs) to the **real client telephony API**, while keeping **`POST /api/telephony/events`** as the single ingress for answer, DTMF, hangup, and failure signals.

This document is **operational**; implementation details live in `backend/app/services/telephony/`, `backend/app/routers/telephony.py`, and `backend/app/schemas.py` (`TelephonyProviderLiteral`: `mock` \| `asterisk` \| `client_api`).

---

## 1. Preconditions

Do not start cutover until all of the following are true.

| Gate | Verification |
|------|----------------|
| **All backend tests passing** | From repo root: `PYTHONPATH=backend python3 -m pytest backend/tests -q` (green). |
| **Alembic at head** | On every deployment target: `cd backend && alembic upgrade head` (includes **`telephony_event_receipts`** / idempotency). |
| **Local Asterisk dry-run completed** | Follow **`docs/runbooks/asterisk-local-dry-run.md`** (or equivalent); webhook JSON, SIP, and DTMF behavior understood. |
| **Dashboard masking verified** | Event stream shows **masked** digit runs (no full 6-digit code in **`call_events.message`**); **`demo_code`** only appears when **`APP_ENV`** is dev-like and API returns it. |
| **Provider webhook idempotency verified** | Replays with the same **`provider` + `provider_event_id`** return **`duplicate_ignored`** and do not double-apply DTMF, attempts, or state (see `tests/test_telephony_idempotency.py`). |
| **Rate limits configured** | **`MAX_CALLS_PER_PHONE_PER_DAY`** set appropriately per environment; document values in your env matrix. |

Optional but recommended: staging DB backup, runbook owner assigned, maintenance window communicated to client if they observe traffic.

---

## 2. Provider adapter checklist

Implement (or complete) the **outbound** adapter that replaces or sits beside **`MockTelephonyProvider`**, and the **inbound** mapping from the client API → **`POST /api/telephony/events`** (direct HTTP from their edge, or your BFF).

| Item | What “done” looks like |
|------|-------------------------|
| **`start_outbound` implementation** | Originate (or enqueue) a call via the client API; persist correlation **`call_session.id`** ↔ provider leg ID; handle async errors without leaking verification material. |
| **`provider_call_id` mapping** | Every webhook where useful includes **`provider_call_id`** (channel/session id from provider) for support and logs; optional in schema today—populate for production. |
| **`provider_event_id` mapping** | **Stable, unique per logical delivery** (e.g. provider message id, or deterministic hash of event + timestamp + call leg). Required for safe retries. |
| **Answer event mapping** | Callee answer → **`event_type`: `ANSWERED`**, **`call_id`**: session UUID. Triggers consent step (**`CALL_ANSWERED`**) in app. |
| **DTMF event mapping** | Each digit → **`event_type`: `DTMF`**, **`digit`**: single `0`–`9` during consent and verification; never batch six digits in one payload unless you add a separate contract (current API is per-digit). |
| **Hangup event mapping** | User or network hangup → **`event_type`: `HANGUP`**; maps to **`CALL_HANGUP`** and terminal state rules in **`telephony.py`**. |
| **Failed event mapping** | Unreachable, busy, provider error → **`event_type`: `FAILED`**; maps to **`CALL_FAILED`**. |
| **Retry behavior** | Idempotent POSTs: same **`provider_event_id`** must not re-run side effects (DB enforces per provider). Transient failures: retry **new** deliveries with **new** `provider_event_id` only when the operation did not commit (coordinate with provider semantics). |
| **Timeout behavior** | Define max time in **dialing / ringing / consent / verification**; on timeout, emit **`HANGUP`** or **`FAILED`** with clear **`raw_payload`** for audit (no secrets). |

Webhook **`provider`** field: use **`client_api`** (per schema) unless you extend **`TelephonyProviderLiteral`** with a dedicated value after code change.

---

## 3. Safety gates

Apply **all** before the first real PSTN/SIP traffic to non-test numbers.

| Gate | Practice |
|------|----------|
| **Test numbers allowlist** | Only **`phone_number`** values on an explicit allowlist may hit the real provider from staging; block or route others to mock in BFF. |
| **Low daily rate limit** | Set **`MAX_CALLS_PER_PHONE_PER_DAY`** to a small number (e.g. **1–5**) in staging; increase only after burn-in. |
| **`APP_ENV` staging** | Use a non-production **`APP_ENV`** (e.g. **`staging`**) so **`demo_code`** is **not** returned from **`POST /api/calls/start`**; operators use controlled test fixtures. |
| **No production traffic at first** | No production hostnames, credentials, or customer numbers until sign-off below. |
| **No raw DTMF logging** | Application logs and APM: never log full buffers or codes; rely on **masked** `CallEvent` messages and hashed verification storage. |
| **No third-party OTP wording** | IVR copy stays limited to the client’s **official verification system** only (see compliance / `PromptRenderer`); legal/compliance sign-off on any copy change. |
| **Consent prompt enabled** | **`ANSWERED`** → consent; **`DTMF` `1`/`2`** before verification; no shortcut to code entry without **RECIPIENT_ACCEPTED**. |

Secrets: **`DTMF_BUFFER_SECRET`**, provider API keys, and webhook HMAC/signing keys in a secret manager—never in repo or plain CI logs.

---

## 4. Rollout phases

Increase blast radius only after metrics and error budgets look healthy for the prior phase.

| Phase | Scope | Success criteria (minimum) |
|-------|--------|----------------------------|
| **1 — One internal number** | Single engineer-owned handset | Full happy path + one negative (decline or hangup); idempotency spot-check; no duplicate terminal states. |
| **2 — Five internal numbers** | Small team | Same as phase 1 across devices; consent + verification stats stable; no provider 4xx/5xx spikes. |
| **3 — Client test number** | Client-approved test DID | Client confirms audio, DTMF, and webhook latency; **`provider_event_id`** visible in their tooling. |
| **4 — Small batch** | Limited production cohort (feature flag / allowlist) | Monitoring section thresholds green for 24–48h. |
| **5 — Full production** | All eligible traffic | Go/no-go signed; rollback tested once in staging. |

Between phases, capture **run notes**: time range, volume, incidents, config diffs.

---

## 5. Rollback

If error rate, compliance risk, or provider outage demands it:

| Action | Detail |
|--------|--------|
| **Switch provider env back to mock** | In your deployment: point **`start_call`** / outbound scheduler to **`MockTelephonyProvider`** (or disable client originate) so new sessions do not hit the client API. Code path is typically **`outbound_simulation.schedule_mock_outbound`** vs a new flag (implement **`USE_CLIENT_TELEPHONY`** or similar if not present). |
| **Disable outbound calls** | Feature flag off, or API **`POST /api/calls/start`** returns **503**/maintenance with clear message; existing sessions drain via webhooks only. |
| **Dashboard read-only** | Optional: disable **Start call** / simulator actions in UI while keeping **`GET`** + **`WS`** for observation (product decision). |
| **Preserve audit logs** | Do **not** delete **`call_events`**, **`call_sessions`**, **`telephony_event_receipts`**, or **`verification_attempts`**; they support post-incident review and idempotency after cutover restore. |

After rollback, document root cause and re-entry criteria before retrying rollout.

---

## 6. Monitoring

Define dashboards/alerts on **staging first**, then production. Suggested signals (exact tooling: Datadog, Grafana, CloudWatch, etc.).

| Metric | Why it matters |
|--------|----------------|
| **Call completion rate** | Sessions reaching **completed** (verified or declined) ÷ starts; drops indicate originate or webhook failures. |
| **Consent decline rate** | **`RECIPIENT_DECLINED`** ÷ sessions that reached consent; sudden spikes may mean bad audio or wrong prompt. |
| **Verification success rate** | Verified completions ÷ sessions that entered verification; tracks DTMF and user success. |
| **Wrong attempts** | **`wrong_code_attempts`** distribution and **`VERIFICATION_FAILED`** / **`MAX_ATTEMPTS_EXCEEDED`** counts. |
| **Duplicate webhook count** | Responses with **`duplicate_ignored`** (or receipt table growth vs event count); high volume may mean provider retry storms—acceptable if idempotent, noisy if not. |
| **Provider failure count** | **`FAILED`** webhooks + HTTP errors on originate; alert on SLO breach. |
| **Average call duration** | Derived from **`created_at` → terminal event** timestamps; regressions may indicate routing or media issues. |

Log-based alerts: **never** alert on raw message bodies containing digit sequences; use event **types** and **session status** transitions.

---

## 7. Go / no-go checklist

**Go** only if every item is **Yes**.

| # | Question |
|---|----------|
| 1 | Backend tests green on the release commit? |
| 2 | Migrations applied on target DB (**`0006`**+)? |
| 3 | Dry-run runbook executed successfully in staging? |
| 4 | **`provider_event_id`** present on all provider deliveries in staging? |
| 5 | Masking verified on **`GET /api/calls/{id}/events`** and WebSocket feed? |
| 6 | Rate limits and allowlist enforced for staging? |
| 7 | Rollback procedure rehearsed (mock + disable start)? |
| 8 | On-call and comms path agreed with client? |
| 9 | Monitoring dashboards live for this release? |
| 10 | Compliance / consent copy unchanged or re-approved? |

If any item is **No** or **Unknown**, treat as **no-go** until resolved.

---

## Related documents

- **`docs/runbooks/asterisk-local-dry-run.md`** — Local SIP + webhook manual flow.  
- **`README.md`** — API overview, checklist, **`POST /api/telephony/events`**, **`WS /ws`**.  
- **`infra/sipup/README.md`** — Reference stack for lab testing (not production carrier).
