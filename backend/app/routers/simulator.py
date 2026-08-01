from fastapi import APIRouter, Depends, HTTPException
from ..auth import get_current_admin
from sqlalchemy.orm import Session

from ..compliance import operator_consent_answered_message
from ..event_types import CallEventType
from ..database import SessionLocal, get_db
from ..exceptions import InvalidIvrTransition
from ..models import CallSession, EventActor, SessionStatus, SimulatorStep
from ..schemas import SimulatorAction, SimulatorDigitPress, SimulatorEnterCode
from ..services.call_service import MAX_CODE_ATTEMPTS, call_service
from ..services.outbound_simulation import cancel_mock_task, get_mock_task, schedule_mock_outbound

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.post("/{call_id}/answered", response_model=dict)
async def simulator_answered(call_id: str, db: Session = Depends(get_db)):
    sess = db.get(CallSession, call_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.simulator_step != SimulatorStep.IDLE.value:
        raise HTTPException(
            status_code=400,
            detail="Simulator must be at idle step (only one answered transition allowed)",
        )
    if sess.status in (
        SessionStatus.COMPLETED.value,
        SessionStatus.FAILED.value,
        SessionStatus.CANCELLED.value,
    ):
        raise HTTPException(status_code=400, detail="Session is closed")

    consent_msg = operator_consent_answered_message(sess.university)
    try:
        await call_service.add_event(
            db,
            call_id,
            CallEventType.CALL_ANSWERED.value,
            consent_msg,
            new_step=SimulatorStep.CONSENT.value,
            ws_type=CallEventType.CALL_ANSWERED.value,
            actor=EventActor.USER,
        )
    except InvalidIvrTransition as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "step": SimulatorStep.CONSENT.value}


@router.post("/{call_id}/press", response_model=dict)
async def simulator_press(call_id: str, body: SimulatorDigitPress, db: Session = Depends(get_db)):
    sess = db.get(CallSession, call_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.simulator_step != SimulatorStep.CONSENT.value:
        raise HTTPException(status_code=400, detail="Not at consent step (press 1 or 2 after /answered)")

    if body.digit not in ("1", "2"):
        raise HTTPException(status_code=400, detail="Consent step expects digit 1 or 2")

    try:
        result = await call_service.handle_consent_digit(
            db,
            call_id,
            body.digit,
            actor=EventActor.USER,
        )
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "step": result["step"], "consent_digit": result.get("consent_digit")}


@router.post("/{call_id}/enter-code", response_model=dict)
async def simulator_enter_code(call_id: str, body: SimulatorEnterCode, db: Session = Depends(get_db)):
    sess = db.get(CallSession, call_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.simulator_step != SimulatorStep.VERIFICATION_CODE.value:
        raise HTTPException(status_code=400, detail="Not at verification code step")
    if sess.wrong_code_attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded")

    raw = body.digits.strip()
    from ..services.speech_script_service import coerce_otp_digit_count

    required = coerce_otp_digit_count(sess.expected_digits_count)
    if not raw.isdigit() or len(raw) != required:
        raise HTTPException(status_code=400, detail=f"OTP code must be exactly {required} digits")

    try:
        result = await call_service.submit_digits_for_admin_verification(
            db,
            call_id,
            raw,
            actor=EventActor.USER,
        )
    except (InvalidIvrTransition, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **result, "step": SimulatorStep.PENDING_ADMIN_VERIFICATION.value}


@router.post("/{call_id}/action", response_model=dict)
async def simulator_action(call_id: str, body: SimulatorAction, db: Session = Depends(get_db)):
    sess = db.get(CallSession, call_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    action = body.action.strip().lower()

    if action == "start_call":
        if sess.status in (
            SessionStatus.VERIFIED.value,
            SessionStatus.COMPLETED.value,
            SessionStatus.FAILED.value,
            SessionStatus.CANCELLED.value,
        ):
            raise HTTPException(status_code=400, detail="Session already finished")
        t = get_mock_task(call_id)
        if t is not None and not t.done():
            raise HTTPException(status_code=409, detail="Simulation already running")
        schedule_mock_outbound(call_id)
        return {"ok": True, "message": "Mock outbound started"}

    if action == "hangup":
        await cancel_mock_task(call_id)
        db_session = SessionLocal()
        try:
            if sess.status not in (
                SessionStatus.VERIFIED.value,
                SessionStatus.COMPLETED.value,
                SessionStatus.FAILED.value,
                SessionStatus.CANCELLED.value,
            ):
                try:
                    await call_service.add_event(
                        db_session,
                        call_id,
                        CallEventType.CALL_HANGUP.value,
                        "Call ended by operator (simulator)",
                        new_status=SessionStatus.CANCELLED,
                        new_step=SimulatorStep.FINISHED.value,
                        ivr_terminal="cancelled",
                        ws_type=CallEventType.CALL_HANGUP.value,
                        actor=EventActor.ADMIN,
                    )
                except InvalidIvrTransition as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            db_session.close()
        return {"ok": True, "message": "Hangup simulated"}

    if action == "submit_digits":
        raw = (body.digits or "").strip()
        db_session = SessionLocal()
        try:
            try:
                result = await call_service.submit_digits_for_admin_verification(
                    db_session,
                    call_id,
                    raw,
                    actor=EventActor.USER,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
        finally:
            db_session.close()
        return {"ok": True, **result}

    raise HTTPException(status_code=400, detail="Unknown action")
