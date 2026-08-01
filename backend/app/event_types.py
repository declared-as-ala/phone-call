"""Canonical string values for persisted :class:`~app.models.CallEvent` ``event_type``."""

from __future__ import annotations

import enum

__all__ = [
    "CallEventType",
    "LEGACY_CALL_EVENT_TYPES",
    "LEGACY_CHANNEL_CONNECTED_EVENT",
    "allowed_persisted_call_event_types",
]


class CallEventType(str, enum.Enum):
    """Domain events written to ``call_events.event_type`` and mirrored in WebSocket ``type`` where applicable."""

    CALL_CREATED = "CALL_CREATED"
    CALL_INITIATED = "CALL_INITIATED"
    DIAL_STARTED = "DIAL_STARTED"
    CALL_RINGING = "CALL_RINGING"
    CALL_ANSWERED = "CALL_ANSWERED"
    IVR_PROMPT = "IVR_PROMPT"
    DTMF_RECEIVED = "DTMF_RECEIVED"
    DIGIT_RECEIVED = "DIGIT_RECEIVED"
    DIGITS_RECEIVED = "DIGITS_RECEIVED"
    RECIPIENT_ACCEPTED = "RECIPIENT_ACCEPTED"
    ADMIN_CODE_SENT_CONFIRMED = "ADMIN_CODE_SENT_CONFIRMED"
    RECIPIENT_DECLINED = "RECIPIENT_DECLINED"
    PENDING_ADMIN_VERIFICATION = "PENDING_ADMIN_VERIFICATION"
    ADMIN_VERIFICATION_APPROVED = "ADMIN_VERIFICATION_APPROVED"
    ADMIN_VERIFICATION_REJECTED = "ADMIN_VERIFICATION_REJECTED"
    VERIFICATION_SUCCESS = "VERIFICATION_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    MAX_ATTEMPTS_EXCEEDED = "MAX_ATTEMPTS_EXCEEDED"
    CALL_COMPLETED = "CALL_COMPLETED"
    CALL_FAILED = "CALL_FAILED"
    CALL_HANGUP = "CALL_HANGUP"
    AUDIT_STATE_CHANGE = "AUDIT_STATE_CHANGE"
    NOOP_TERMINAL_EVENT = "NOOP_TERMINAL_EVENT"
    ADMIN_ENTERED_CODE_VIEWED = "ADMIN_ENTERED_CODE_VIEWED"


# PSTN / pre-consent "answered" in outbound mock flows — distinct from ``CALL_ANSWERED`` (consent step).
LEGACY_CHANNEL_CONNECTED_EVENT = "ANSWERED"

# Values that may still appear from older deployments, tests that inject synthetic rows, or alternate code paths.
LEGACY_CALL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "VERIFICATION_OK",
        "VERIFICATION_FAIL",
        "INVALID_CONSENT_INPUT",
        # Pre-rename terminal / lifecycle strings
        "HANGUP",
        "FAILED",
        "RINGING",
        LEGACY_CHANNEL_CONNECTED_EVENT,
    }
)


def allowed_persisted_call_event_types() -> frozenset[str]:
    return frozenset(e.value for e in CallEventType) | LEGACY_CALL_EVENT_TYPES
