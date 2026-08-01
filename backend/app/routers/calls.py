import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import LOCAL_DEVELOPMENT
from ..auth import get_current_admin
from ..event_types import CallEventType
from ..database import get_db
from ..exceptions import InvalidIvrTransition, OutboundCallBlocked, RateLimitExceeded, SipUpConfigurationError
from ..models import AdminUser, CallEvent, CallSession, EventActor, SessionStatus, TelephonyEventReceipt, VerificationAttempt
from ..schemas import CallEventRead, CallSessionRead, CallStartRequest, CallStartResponse
from ..security import mask_digits_in_text
from ..services import call_service as call_service_module
from ..services.call_service import call_service
from ..services.luvvoice_tts import api_token_configured
from ..services.outbound_simulation import cancel_mock_task, schedule_outbound_call
from ..services.speech_wav_cache import schedule_luvvoice_prefetch
from ..services.telephony.sip_up_provider import SipUpTelephonyConfig
from ..telephony_provider_config import (
    call_initiated_message_for_start,
    provider_class_name,
    telephony_provider_mode,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.post("/start", response_model=CallStartResponse, response_model_exclude_none=True)
async def start_call(payload: CallStartRequest, db: Session = Depends(get_db)):
    mode = telephony_provider_mode()
    if payload.outbound_trunk == "sip_up" and mode == "sip_up":
        try:
            SipUpTelephonyConfig.from_env().validate()
        except SipUpConfigurationError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        try:
            call_service.enforce_outbound_call_spacing(db)
        except OutboundCallBlocked as e:
            headers = {"Retry-After": str(e.wait_seconds)} if e.wait_seconds > 0 else None
            raise HTTPException(status_code=429, detail=str(e), headers=headers) from e

    if payload.speech_engine == "luvvoice" and not api_token_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Premium LuvVoice speech is selected but LUVVOICE_API_TOKEN is not set on the backend. "
                "Add your API token to backend/.env or choose Free system speech."
            ),
        )

    dest_digits = "".join(ch for ch in payload.phone_number if ch.isdigit())
    cid_digits = "".join(ch for ch in (payload.outbound_caller_id or "") if ch.isdigit())
    if (
        dest_digits
        and cid_digits
        and len(dest_digits) >= 8
        and len(cid_digits) >= 8
        and (dest_digits == cid_digits or dest_digits.endswith(cid_digits) or cid_digits.endswith(dest_digits))
    ):
        raise HTTPException(
            status_code=400,
            detail="Recipient phone number must not be the same as the outbound caller ID.",
        )

    try:
        trunk_to_store = "sip_up"
        session, plain_code = call_service.create_call_session(
            db,
            name=payload.name,
            university=payload.university,
            phone_number=payload.phone_number,
            outbound_trunk=trunk_to_store,
            outbound_caller_id=payload.outbound_caller_id,
            speech_engine=payload.speech_engine,
            luvvoice_voice_id=payload.luvvoice_voice_id,
            speech_volume_percent=payload.speech_volume_percent,
            language=payload.language,
        )
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e)) from e

    logger.info(
        "POST /api/calls/start session_id=%s telephony_provider=%s provider_class=%s "
        "phone=%s outbound_trunk=%s mock_scheduling=%s",
        session.id,
        mode,
        provider_class_name(mode),
        mask_digits_in_text(session.phone_number),
        payload.outbound_trunk,
        "enabled" if mode == "mock" else "depends",
    )

    await call_service.add_event(
        db,
        session.id,
        CallEventType.CALL_CREATED.value,
        f"Call session created for {session.name} ({session.university})",
        ws_type=CallEventType.CALL_CREATED.value,
        actor=EventActor.ADMIN,
    )

    await call_service.add_event(
        db,
        session.id,
        CallEventType.CALL_INITIATED.value,
        call_initiated_message_for_start(mode, payload.outbound_trunk),
        new_status=SessionStatus.DIALING,
        ws_type=CallEventType.CALL_INITIATED.value,
        actor=EventActor.SYSTEM,
    )

    schedule_outbound_call(session.id, trunk_preference=payload.outbound_trunk)
    if payload.speech_engine == "luvvoice":
        schedule_luvvoice_prefetch(session.id)

    if LOCAL_DEVELOPMENT:
        return CallStartResponse(call_id=session.id, demo_code=plain_code)
    return CallStartResponse(call_id=session.id)


@router.get("/outbound-spacing", response_model=dict)
def outbound_spacing(db: Session = Depends(get_db)):
    """Whether a new SIP UP outbound call is allowed (active-call guard + post-call cooldown)."""
    return call_service.outbound_spacing_status(db)


@router.get("", response_model=list[CallSessionRead])
def list_calls(db: Session = Depends(get_db)):
    rows = db.scalars(select(CallSession).order_by(CallSession.created_at.desc())).all()
    return [CallSessionRead.model_validate(r) for r in rows]


@router.get("/{call_id}", response_model=CallSessionRead)
def get_call(call_id: str, db: Session = Depends(get_db)):
    row = db.get(CallSession, call_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return CallSessionRead.model_validate(row)


@router.get("/{call_id}/events", response_model=list[CallEventRead])
def list_events(call_id: str, db: Session = Depends(get_db)):
    if db.get(CallSession, call_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    rows = db.scalars(
        select(CallEvent)
        .where(CallEvent.session_id == call_id)
        .order_by(CallEvent.created_at.asc())
    ).all()
    return [CallEventRead.model_validate(r) for r in rows]


@router.get("/{call_id}/admin/entered-code", response_model=dict)
async def get_admin_entered_code(
    call_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
):
    """Reveal the full entered verification code. The only endpoint that ever
    returns it in plaintext — every access is audit-logged against the calling
    admin (see ``ADMIN_ENTERED_CODE_VIEWED``)."""
    row = db.get(CallSession, call_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    plain = call_service_module._plain_dtmf_buffer(row)
    if not plain:
        raise HTTPException(status_code=404, detail="Entered code not available")

    await call_service.add_event(
        db,
        call_id,
        CallEventType.ADMIN_ENTERED_CODE_VIEWED.value,
        f"Administrator {admin.email} viewed the full entered verification code",
        ws_type=CallEventType.ADMIN_ENTERED_CODE_VIEWED.value,
        actor=EventActor.ADMIN,
        broadcast_session_update=False,
    )
    return {
        "call_id": call_id,
        "entered_code": plain,
        "masked_entered_code": row.masked_entered_code,
    }


@router.delete("/{call_id}", response_model=dict)
async def delete_call(call_id: str, db: Session = Depends(get_db)):
    if not LOCAL_DEVELOPMENT:
        raise HTTPException(status_code=403, detail="Call deletion is only available for local/demo cleanup")
    row = db.get(CallSession, call_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await cancel_mock_task(call_id)
    db.execute(delete(TelephonyEventReceipt).where(TelephonyEventReceipt.call_id == call_id))
    db.execute(delete(VerificationAttempt).where(VerificationAttempt.session_id == call_id))
    db.execute(delete(CallEvent).where(CallEvent.session_id == call_id))
    db.delete(row)
    db.commit()
    return {"ok": True, "deleted": True, "call_id": call_id}


@router.post("/{call_id}/admin/code-sent", response_model=dict)
async def admin_confirm_code_sent_externally(call_id: str, db: Session = Depends(get_db)):
    row = db.get(CallSession, call_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    prev_step = row.simulator_step
    phone = (row.phone_number or "").strip()
    try:
        out = await call_service.confirm_admin_external_code_sent(db, call_id)
        if out.get("idempotent"):
            logger.info(
                "admin_code_sent_idempotent_router call_prefix=%s step=%s phone=%s",
                call_id[:8],
                out.get("step"),
                phone or "(unset)",
            )
        else:
            logger.info(
                "admin_code_sent_ok call_prefix=%s old_step=%s new_step=%s phone=%s",
                call_id[:8],
                prev_step,
                out.get("step"),
                phone or "(unset)",
            )
        return out
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{call_id}/admin/approve-verification", response_model=dict)
async def approve_verification(call_id: str, db: Session = Depends(get_db)):
    if db.get(CallSession, call_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return await call_service.approve_admin_verification(db, call_id)
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{call_id}/admin/reject-verification", response_model=dict)
async def reject_verification(call_id: str, db: Session = Depends(get_db)):
    if db.get(CallSession, call_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return await call_service.reject_admin_verification(db, call_id)
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{call_id}/admin/end-call", response_model=dict)
async def admin_end_call(call_id: str, db: Session = Depends(get_db)):
    if db.get(CallSession, call_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return await call_service.admin_end_active_call(db, call_id)
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
