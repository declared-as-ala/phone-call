"""Compliance scope for outbound IVR verification (reference for prompts and audits).

- Official verification system codes only: never collect or store third-party codes from
  messaging, email, banking, or other external services.
- Consent: the callee must hear which organization is calling before proceeding; keypad 1 confirms
  and continues to student-card entry; keypad 2 declines and ends the call.
- Verification codes are stored exclusively as bcrypt hashes.
- DTMF logging: digit runs are masked in persisted and broadcast event text, keeping only the
  last two digits of each contiguous digit sequence visible.
"""

from typing import Optional

# Fixed wording for IVR / audit (no dynamic secrets).
CONSENT_ACCEPT_OPTION = "To confirm, press 1."
CONSENT_DECLINE_OPTION = "To decline, press 2."
CONSENT_CONTINUE_OPTION = f"{CONSENT_ACCEPT_OPTION} {CONSENT_DECLINE_OPTION}"
NO_SENSITIVE_DATA_NOTICE = (
    "We will not ask for bank card numbers, passwords, or codes from external services."
)


def operator_consent_answered_message(organization: Optional[str] = None) -> str:
    """Audit / admin UI copy when the SIP leg is up and consent IVR starts (not spoken to the operator)."""
    org = (organization or "organization").strip() or "organization"
    return (
        f"SIP UP connected — consent IVR playing ({org}). "
        "This means the carrier accepted the call on our side; it does not guarantee the mobile rang. "
        "If the phone stayed silent, authorize the outbound caller ID in the SIP UP dashboard."
    )


def operator_consent_ivr_playing_message() -> str:
    return "Consent prompt playing on callee line."
