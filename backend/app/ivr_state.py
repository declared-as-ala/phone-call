"""
Strict IVR flow state machine: logical ``CallStep`` over persisted status + simulator step.

``SessionStatus`` in ``models`` is an alias of ``CallStatus`` (single canonical enum).
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Dict, FrozenSet, Optional

from .exceptions import InvalidIvrTransition

if TYPE_CHECKING:
    from .models import CallSession


class CallStatus(str, enum.Enum):
    PENDING = "pending"
    DIALING = "dialing"
    RINGING = "ringing"
    CONNECTED = "connected"
    COLLECTING = "collecting"
    PENDING_ADMIN_VERIFICATION = "pending_admin_verification"
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class CallStep(str, enum.Enum):
    CREATED = "created"
    DIALING = "dialing"
    CONSENT = "consent"
    WAITING_ADMIN_CODE_SEND = "waiting_admin_code_send"
    VERIFICATION_CODE = "verification_code"
    PENDING_ADMIN_VERIFICATION = "pending_admin_verification"
    DECLINED = "declined"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL_STEPS: FrozenSet[CallStep] = frozenset(
    {
        CallStep.DECLINED,
        CallStep.FINISHED,
        CallStep.FAILED,
        CallStep.CANCELLED,
    }
)

_DIALING_STATUS = frozenset(
    {
        CallStatus.DIALING.value,
        CallStatus.RINGING.value,
        CallStatus.CONNECTED.value,
        CallStatus.COLLECTING.value,
    }
)

ALLOWED_TRANSITIONS: Dict[CallStep, FrozenSet[CallStep]] = {
    CallStep.CREATED: frozenset({CallStep.DIALING, CallStep.FAILED}),
    CallStep.DIALING: frozenset({CallStep.DIALING, CallStep.CONSENT, CallStep.CANCELLED, CallStep.FAILED}),
    CallStep.CONSENT: frozenset(
        {
            CallStep.VERIFICATION_CODE,
            CallStep.WAITING_ADMIN_CODE_SEND,
            CallStep.DECLINED,
            CallStep.CANCELLED,
            CallStep.FAILED,
        }
    ),
    CallStep.WAITING_ADMIN_CODE_SEND: frozenset(
        {CallStep.VERIFICATION_CODE, CallStep.CANCELLED, CallStep.FAILED}
    ),
    CallStep.VERIFICATION_CODE: frozenset(
        {
            CallStep.VERIFICATION_CODE,
            CallStep.PENDING_ADMIN_VERIFICATION,
            CallStep.FINISHED,
            CallStep.FAILED,
            CallStep.CANCELLED,
        }
    ),
    CallStep.PENDING_ADMIN_VERIFICATION: frozenset(
        {
            CallStep.VERIFICATION_CODE,
            CallStep.FINISHED,
            CallStep.FAILED,
            CallStep.CANCELLED,
        }
    ),
    CallStep.DECLINED: frozenset(),
    CallStep.FINISHED: frozenset(),
    CallStep.FAILED: frozenset(),
    CallStep.CANCELLED: frozenset(),
}


class _SimStep:
    IDLE = "idle"
    CONSENT = "consent"
    WAITING_ADMIN_CODE_SEND = "waiting_admin_code_send"
    VERIFICATION_CODE = "verification_code"
    PENDING_ADMIN_VERIFICATION = "pending_admin_verification"
    FINISHED = "finished"


def validate_transition(current: CallStep, next_step: CallStep) -> None:
    if current == next_step:
        return
    allowed = ALLOWED_TRANSITIONS.get(current)
    if allowed is None or next_step not in allowed:
        raise InvalidIvrTransition(
            f"IVR transition not allowed: {current.value} -> {next_step.value}"
        )


def derive_call_step(session: CallSession) -> CallStep:
    st = session.status
    sp = session.simulator_step
    oc = session.ivr_outcome

    if st == CallStatus.FAILED.value:
        return CallStep.FAILED
    if st == CallStatus.CANCELLED.value:
        return CallStep.CANCELLED
    if st == CallStatus.VERIFIED.value:
        return CallStep.FINISHED
    if sp == _SimStep.FINISHED:
        if st == CallStatus.COMPLETED.value:
            if oc == "declined":
                return CallStep.DECLINED
            return CallStep.FINISHED
        return CallStep.FINISHED
    if sp == _SimStep.PENDING_ADMIN_VERIFICATION:
        return CallStep.PENDING_ADMIN_VERIFICATION
    if sp == _SimStep.VERIFICATION_CODE:
        return CallStep.VERIFICATION_CODE
    if sp == _SimStep.WAITING_ADMIN_CODE_SEND:
        return CallStep.WAITING_ADMIN_CODE_SEND
    if sp == _SimStep.CONSENT:
        return CallStep.CONSENT
    if st == CallStatus.PENDING.value and sp == _SimStep.IDLE:
        return CallStep.CREATED
    if st in _DIALING_STATUS and sp == _SimStep.IDLE:
        return CallStep.DIALING
    if st == CallStatus.DIALING.value and sp == _SimStep.IDLE:
        return CallStep.DIALING
    return CallStep.DIALING


def resolve_next_call_step(
    session: CallSession,
    *,
    new_status: Optional[CallStatus] = None,
    new_step: Optional[str] = None,
    ivr_terminal: Optional[str] = None,
) -> CallStep:
    cur = derive_call_step(session)
    st_val = new_status.value if new_status is not None else None
    sp_val = new_step

    if sp_val == _SimStep.FINISHED:
        if st_val == CallStatus.CANCELLED.value:
            return CallStep.CANCELLED
        if st_val == CallStatus.FAILED.value:
            return CallStep.FAILED
        if st_val == CallStatus.COMPLETED.value:
            if ivr_terminal == "declined":
                return CallStep.DECLINED
            if ivr_terminal == "verified":
                return CallStep.FINISHED
            raise ValueError(
                "COMPLETED status with finished step requires ivr_terminal "
                "'declined' or 'verified'"
            )
        if st_val == CallStatus.VERIFIED.value:
            return CallStep.FINISHED

    if sp_val == _SimStep.PENDING_ADMIN_VERIFICATION:
        return CallStep.PENDING_ADMIN_VERIFICATION
    if sp_val == _SimStep.VERIFICATION_CODE:
        return CallStep.VERIFICATION_CODE
    if sp_val == _SimStep.WAITING_ADMIN_CODE_SEND:
        return CallStep.WAITING_ADMIN_CODE_SEND
    if sp_val == _SimStep.CONSENT:
        return CallStep.CONSENT

    if st_val == CallStatus.DIALING.value and cur == CallStep.CREATED:
        return CallStep.DIALING
    if st_val in _DIALING_STATUS and cur in (CallStep.CREATED, CallStep.DIALING):
        return CallStep.DIALING
    if st_val == CallStatus.DIALING.value and cur == CallStep.DIALING:
        return CallStep.DIALING

    if st_val == CallStatus.FAILED.value:
        return CallStep.FAILED
    if st_val == CallStatus.CANCELLED.value:
        return CallStep.CANCELLED
    if st_val == CallStatus.VERIFIED.value and sp_val is None:
        return CallStep.FINISHED

    if new_status is None and new_step is None:
        return cur

    raise ValueError(
        f"Cannot resolve IVR transition from state {cur.value} with "
        f"new_status={st_val!r} new_step={sp_val!r} ivr_terminal={ivr_terminal!r}"
    )
