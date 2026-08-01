# Manual IVR test report

**Instructions:** Copy this file to a new document per test run (e.g. `manual-ivr-YYYY-MM-DD-<tester>.md`). Fill all **Report metadata** fields. For each **scenario**, record results in the scenario section or duplicate the per-scenario table if you run multiple variants.

---

## Report metadata

| Field | Value |
|-------|-------|
| **Tester** | |
| **Date / time** | (timezone) |
| **Environment** | e.g. local / staging / preprod |
| **Git commit** | `git rev-parse HEAD` |
| **Backend version** | e.g. image tag, `pip freeze` subset, or `uvicorn` app version note |
| **Frontend version** | e.g. npm build id, commit, or `package.json` version |
| **Provider used** | `mock` / `local Asterisk` / `client API` |
| **Test phone number (masked)** | e.g. `+1******901` (never full E.164 in shared reports) |
| **`call_id`** | UUID from `POST /api/calls/start` |
| **`provider_call_id`** | (if applicable) |
| **`provider_event_id`s used** | List or “N/A”; note if duplicates were intentional for idempotency test |

---

## Session summary

| Field | Value |
|-------|-------|
| **Scenario tested** | Short name (see sections below) |
| **Expected result** | |
| **Actual result** | |
| **Pass / fail** | PASS / FAIL |
| **Screenshots attached** | Yes / No — filenames or link |
| **Issues found** | Ticket IDs / brief description |
| **Notes** | |

---

## Dashboard events observed

Paste or summarize from Live logs / `GET /api/calls/{call_id}/events` (order matters).

| # | Timestamp (approx.) | Event type | Actor | Masked payload (summary) |
|---|---------------------|------------|-------|---------------------------|
| 1 | | | | |
| 2 | | | | |
| … | | | | |

---

## Scenarios

Run the scenarios relevant to your cutover phase. For each: fill **expected**, **actual**, **pass/fail**, **notes**, and extend the events table above or add a subsection table.

### 1. Happy path

- **Description:** Start call → answer (or `ANSWERED` webhook) → consent **1** → enter internal 6-digit code one digit at a time (`DTMF`) → confirm **Pending admin verification** with masked digits only → admin **Approve** → verification success / completed.
- **Expected result:** `DIGITS_RECEIVED` then `PENDING_ADMIN_VERIFICATION`; no `VERIFICATION_SUCCESS` before approval; approval emits `ADMIN_VERIFICATION_APPROVED` then `VERIFICATION_SUCCESS`.
- **Actual result:** |
- **Pass / fail:** |

### 2. Consent declined

- **Description:** After consent prompt, send **`DTMF` `2`** (or press 2 on phone).
- **Expected result:** |
- **Actual result:** |
- **Pass / fail:** |

### 3. Admin reject then success

- **Description:** Accept consent → enter one full 6-digit attempt → admin **Reject** → enter another full 6-digit attempt → admin **Approve**.
- **Expected result:** Rejection emits `ADMIN_VERIFICATION_REJECTED` and returns to `verification_code`; approval emits `ADMIN_VERIFICATION_APPROVED` then `VERIFICATION_SUCCESS`.
- **Actual result:** |
- **Pass / fail:** |

### 4. Three admin rejections

- **Description:** Accept consent → enter a full 6-digit sequence and admin **Reject** three times.
- **Expected result:** Each review emits `ADMIN_VERIFICATION_REJECTED`; attempts remaining return to `verification_code`; third rejection fails the session.
- **Actual result:** |
- **Pass / fail:** |

### 5. Hangup during consent

- **Description:** After `CALL_ANSWERED` / consent step, **`HANGUP`** (or user hangs up) before **1**/**2**.
- **Expected result:** |
- **Actual result:** |
- **Pass / fail:** |

### 6. Hangup during verification

- **Description:** After **1**, partial or zero verification digits, then **`HANGUP`**.
- **Expected result:** |
- **Actual result:** |
- **Pass / fail:** |

### 7. Duplicate webhook event

- **Description:** Replay the same payload with the same **`provider_event_id`** (and same **`provider`**) as a prior successful delivery.
- **Expected result:** HTTP 200, **`status`: `duplicate_ignored`**, no duplicate state/DTMF/attempts.
- **Actual result:** |
- **Pass / fail:** |

### 8. DTMF after terminal state

- **Description:** After terminal success or failure, send another **`DTMF`**.
- **Expected result:** No-op / ignored (e.g. **`noop`: true** in response); no new verification events.
- **Actual result:** |
- **Pass / fail:** |

### 9. Rate limit

- **Description:** Exceed **`MAX_CALLS_PER_PHONE_PER_DAY`** for the same normalized number (UTC day).
- **Expected result:** New **`POST /api/calls/start`** rejected (e.g. 429) with clear message.
- **Actual result:** |
- **Pass / fail:** |

### 10. Masking verification

- **Description:** Complete a path that emits **`DIGIT_RECEIVED`** / **`DIGITS_RECEIVED`** (and any consent message with digits if applicable). Inspect dashboard and **`GET /api/calls/{id}/events`**.
- **Expected result:** No full raw 6-digit code in event **`message`** text; digit runs masked per product rules (e.g. only last 2 of longer runs visible).
- **Actual result:** |
- **Pass / fail:** |

---

## Sign-off (optional)

| Role | Name | Date |
|------|------|------|
| Tester | | |
| Reviewer | | |
