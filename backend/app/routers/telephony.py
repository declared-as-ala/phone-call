"""Inbound webhook for telephony provider call events (mock, SIP UP, client API)."""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..compliance import operator_consent_answered_message
from ..event_types import CallEventType
from ..database import get_db
from ..exceptions import InvalidIvrTransition
from ..ivr_state import FINAL_STEPS, CallStep, derive_call_step
from ..models import CallEvent, CallSession, EventActor, SessionStatus, SimulatorStep, TelephonyEventReceipt
from ..schemas import IvrSpeechHint, TelephonyEventRequest, TelephonyEventResponse
from ..services.call_service import _plain_dtmf_buffer, call_service, wipe_dtmf_buffer
from ..services import speech_script_service
from ..services.speech_script_service import coerce_otp_digit_count
from ..webhook_security import verify_telephony_webhook_signature

router = APIRouter(dependencies=[Depends(verify_telephony_webhook_signature)])


def _is_recipient_busy_failure(raw_payload: dict | None) -> bool:
    """True when the callee line is busy (already on another call)."""
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    if raw.get("failure_kind") == "recipient_busy":
        return True
    cause = raw.get("cause")
    if cause in {17, "17"}:
        return True
    dialstatus = str(raw.get("dialstatus") or raw.get("dial_status") or "").upper()
    if dialstatus == "BUSY":
        return True
    cause_txt = str(raw.get("cause_txt") or "").lower()
    if "busy" in cause_txt:
        return True
    sip_code = str(raw.get("sip_code") or raw.get("sip_response") or "").strip()
    if sip_code in {"486", "600"}:
        return True
    return False


def _recipient_busy_hint(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    provider = _provider_label(raw_payload, outbound_trunk)
    return (
        f"The recipient is already on another call ({provider}). "
        "The outbound call was declined — try again later."
    )


def _is_recipient_unavailable_failure(raw_payload: dict | None) -> bool:
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    cause = raw.get("cause")
    cause_txt = str(raw.get("cause_txt") or "").lower()
    dialstatus = str(raw.get("dialstatus") or raw.get("dial_status") or "").upper()
    state = str(raw.get("channel_state") or "").strip().lower()
    if cause in {18, "18", 19, "19", 20, "20", 34, "34"}:
        return True
    if dialstatus in {"CHANUNAVAIL", "NOANSWER", "CONGESTION"}:
        return True
    if any(
        token in cause_txt
        for token in ("unavailable", "no user", "subscriber absent", "not reachable", "no answer")
    ):
        return True
    return state in {"ringing", "ring", "early", "progress"} and cause not in {16, "16", 17, "17", None}


def _recipient_unavailable_hint(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    provider = _provider_label(raw_payload, outbound_trunk)
    return (
        f"Call reached {provider} and started toward the recipient, but ended before answer "
        "(carrier SIP 480 Temporarily Unavailable). The number may be off, out of coverage, "
        "busy, or not accepting calls right now. Confirm the destination number is correct "
        "and the phone can receive calls, then try again."
    )


def _is_invalid_destination_failure(raw_payload: dict | None) -> bool:
    """True when the dialed destination is malformed or not routable (not a trunk auth issue)."""
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    cause = raw.get("cause")
    if cause in {1, "1", 22, "22", 28, "28"}:
        return True
    cause_txt = str(raw.get("cause_txt") or "").lower()
    return any(
        token in cause_txt
        for token in ("unallocated", "invalid number", "invalid number format", "not valid")
    )


def _invalid_destination_hint(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    provider = _provider_label(raw_payload, outbound_trunk)
    return (
        f"Call ended before answer ({provider}). The destination number looks invalid or too long "
        "(carrier hangup cause 1 — unallocated number). Enter only the recipient mobile in E.164 "
        "format (e.g. +17373946144 for US: country +1, then 10 digits). Do not paste the caller ID "
        "into the phone field or concatenate multiple numbers."
    )


def _pre_answer_hangup_hint(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    """Actionable hint when the call ends before answer."""
    if _is_recipient_busy_failure(raw_payload):
        return _recipient_busy_hint(raw_payload, outbound_trunk)
    if _is_ring_timeout_failure(raw_payload):
        return _ring_timeout_failure_hint(raw_payload, outbound_trunk)
    if _is_invalid_destination_failure(raw_payload):
        return _invalid_destination_hint(raw_payload, outbound_trunk)
    if _is_recipient_unavailable_failure(raw_payload):
        return _recipient_unavailable_hint(raw_payload, outbound_trunk)
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    channel = str(raw.get("channel_name") or raw.get("channel") or "").lower()
    cause = raw.get("cause")
    trunk = (outbound_trunk or "").strip().lower()
    if "sip-up" in channel or trunk in ("sip_up", "", "default", "none"):
        provider = "SIP UP"
    else:
        provider = "the SIP trunk"
    base = (
        f"Call ended before answer ({provider}). The carrier rejected the outbound INVITE "
        "(often SIP 403 Forbidden or 503 Service Unavailable)."
    )
    hints = [
        "Confirm device username/password in infra/sipup/.env",
        "Whitelist your public IP in the provider dashboard",
        "Verify outbound caller ID is authorized for your account",
        "Check pjsip show registrations on the SIP UP stack",
    ]
    if cause in (21, "21"):
        hints.insert(0, "Hangup cause 21 (call rejected) — provider blocked the call")
    return base + " Tips: " + "; ".join(hints) + "."


def _provider_label(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    channel = str(raw.get("channel_name") or raw.get("channel") or "").lower()
    trunk = (outbound_trunk or "").strip().lower()
    if "sip-up" in channel or trunk in ("sip_up", "", "default", "none"):
        return "SIP UP"
    return "the SIP trunk"


def _is_ring_timeout_failure(raw_payload: dict | None) -> bool:
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    if raw.get("failure_kind") == "ring_timeout":
        return True
    state = str(raw.get("channel_state") or "").strip().lower()
    cause = raw.get("cause")
    dialstatus = str(raw.get("dialstatus") or raw.get("dial_status") or "").upper()
    if dialstatus in {"NOANSWER", "CANCEL"}:
        return True
    if state in {"ringing", "ring", "early", "progress"} and cause in {0, "0", 19, "19", None}:
        return True
    return False


def _ring_timeout_failure_hint(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    provider = _provider_label(raw_payload, outbound_trunk)
    timeout = os.getenv("ASTERISK_ORIGINATE_TIMEOUT_SECONDS", "25").strip() or "25"
    return (
        f"Call timed out while ringing ({provider}). The outbound call reached the carrier and "
        f"was ringing, but nobody answered within {timeout} seconds. "
        "This is not a SIP trunk rejection — try again when the recipient can answer, "
        "or raise ASTERISK_ORIGINATE_TIMEOUT_SECONDS in infra/sipup/.env."
    )


def _telephony_failure_message(raw_payload: dict | None, outbound_trunk: str | None) -> str:
    if _is_recipient_busy_failure(raw_payload):
        return _recipient_busy_hint(raw_payload, outbound_trunk)
    if _is_ring_timeout_failure(raw_payload):
        return _ring_timeout_failure_hint(raw_payload, outbound_trunk)
    if _is_recipient_unavailable_failure(raw_payload):
        return _recipient_unavailable_hint(raw_payload, outbound_trunk)
    return _pre_answer_hangup_hint(raw_payload, outbound_trunk)


def _response(sess: CallSession, ivr_speech: Optional[IvrSpeechHint] = None, **kwargs) -> TelephonyEventResponse:
    return TelephonyEventResponse(
        simulator_step=sess.simulator_step,
        session_status=sess.status,
        ivr_speech=ivr_speech,
        **kwargs,
    )


def _duplicate_response(sess: CallSession) -> TelephonyEventResponse:
    return TelephonyEventResponse(
        ok=True,
        status="duplicate_ignored",
        session_status=sess.status,
        simulator_step=sess.simulator_step,
        detail="duplicate provider_event_id",
    )


@router.post("/events", response_model=TelephonyEventResponse)
async def telephony_events(body: TelephonyEventRequest, db: Session = Depends(get_db)):
    call_id = str(body.call_id)
    sess = db.get(CallSession, call_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    peid: Optional[str] = None
    if body.provider_event_id is not None:
        s = body.provider_event_id.strip()
        if s:
            peid = s

    if peid:
        existing = db.scalar(
            select(TelephonyEventReceipt.id).where(
                TelephonyEventReceipt.provider == body.provider,
                TelephonyEventReceipt.provider_event_id == peid,
            )
        )
        if existing is not None:
            db.refresh(sess)
            return _duplicate_response(sess)

    def finalize(build: Callable[[], TelephonyEventResponse]) -> TelephonyEventResponse:
        resp = build()
        if peid:
            db.add(
                TelephonyEventReceipt(
                    provider=body.provider,
                    provider_event_id=peid,
                    call_id=call_id,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                db.refresh(sess)
                # Rare race: another worker inserted the same receipt after we processed.
                return resp.model_copy(
                    update={
                        "simulator_step": sess.simulator_step,
                        "session_status": sess.status,
                    }
                )
        db.refresh(sess)
        return resp.model_copy(
            update={
                "simulator_step": sess.simulator_step,
                "session_status": sess.status,
            }
        )

    raw_note = ""
    if body.raw_payload is not None:
        raw_note = f" raw={json.dumps(body.raw_payload, default=str)[:500]}"

    et = body.event_type
    cur = derive_call_step(sess)

    if et == "RINGING":
        if cur in FINAL_STEPS:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="session already terminal"))
        if cur != CallStep.DIALING:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="ringing ignored"))
        await call_service.add_event(
            db,
            call_id,
            CallEventType.CALL_RINGING.value,
            "Recipient line ringing via SIP UP (183/180 from carrier).",
            new_status=SessionStatus.RINGING,
            ws_type=CallEventType.CALL_RINGING.value,
            actor=EventActor.TELEPHONY_PROVIDER,
        )
        return finalize(lambda: _response(sess, noop=True, detail="ringing"))

    if et == "ANSWERED":
        if cur in FINAL_STEPS:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="session already terminal"))
        if cur == CallStep.CONSENT or sess.simulator_step == SimulatorStep.CONSENT.value:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="already at consent"))
        if cur != CallStep.DIALING:
            raise HTTPException(status_code=400, detail="ANSWERED is only valid while the call is dialing")
        if sess.simulator_step != SimulatorStep.IDLE.value:
            raise HTTPException(status_code=400, detail="Call is not at the pre-IVR idle step")

        consent_msg = operator_consent_answered_message(sess.university)
        ringing_seen = db.scalar(
            select(CallEvent.id)
            .where(
                CallEvent.session_id == call_id,
                CallEvent.event_type == CallEventType.CALL_RINGING.value,
            )
            .limit(1)
        )
        if not ringing_seen:
            consent_msg += (
                " No carrier ringing signal (183/180) was logged — the mobile may not have rung; "
                "confirm caller ID is authorized in SIP UP."
            )
        consent_ivr = speech_script_service.ivr_speech_bundle(
            prompt_key_script="consent_prompt",
            text=speech_script_service.render_for_session(db, sess, "consent_prompt"),
            expected_digit_count=sess.expected_digits_count,
        )
        try:
            await call_service.add_event(
                db,
                call_id,
                CallEventType.CALL_ANSWERED.value,
                consent_msg,
                new_step=SimulatorStep.CONSENT.value,
                ws_type=CallEventType.CALL_ANSWERED.value,
                actor=EventActor.TELEPHONY_PROVIDER,
                # Omit ivr_speech on WS — callee hears consent only via this HTTP response body
                # (duplicate ivr elsewhere can replay audio with the webhook cue).
            )
        except InvalidIvrTransition as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        db.refresh(sess)
        wipe_dtmf_buffer(db, sess)
        db.refresh(sess)
        hint = IvrSpeechHint(
            prompt_key=consent_ivr["prompt_key"],
            text=consent_ivr["text"],
            speech_script_key=consent_ivr.get("speech_script_key"),
        )
        return finalize(lambda: _response(sess, detail="consent", ivr_speech=hint))

    if et == "DTMF":
        digit = (body.digit or "").strip()
        if not digit:
            raise HTTPException(status_code=400, detail="digit is required for DTMF events")
        if cur in FINAL_STEPS:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="session closed; DTMF ignored"))

        if cur == CallStep.CONSENT:
            if digit in ("1", "2"):
                try:
                    result = await call_service.handle_consent_digit(
                        db,
                        call_id,
                        digit,
                        actor=EventActor.USER,
                    )
                except InvalidIvrTransition as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
                db.refresh(sess)
                ivr = result.get("ivr_speech") or {}
                hin = IvrSpeechHint(
                    prompt_key=ivr.get("prompt_key", ""),
                    text=ivr.get("text", ""),
                    speech_script_key=ivr.get("speech_script_key"),
                )
                detail = "otp_entry"
                return finalize(lambda: _response(sess, ivr_speech=hin, detail=detail))
            await call_service.add_event(
                db,
                call_id,
                "INVALID_CONSENT_INPUT",
                f"DTMF '{digit}' is not valid during consent (expect 1 or 2){raw_note}",
                ws_type="INVALID_CONSENT_INPUT",
                actor=EventActor.TELEPHONY_PROVIDER,
            )
            db.refresh(sess)
            return finalize(lambda: _response(sess, detail="invalid_consent_digit"))

        if cur == CallStep.WAITING_ADMIN_CODE_SEND:
            if digit in ("1", "2"):
                db.refresh(sess)
                return finalize(
                    lambda: _response(
                        sess,
                        noop=True,
                        detail="duplicate_consent_digit_ignored",
                    )
                )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Keypad is locked until administrator confirms Done — code sent "
                    "(external delivery via client's official verification platform)."
                ),
            )

        if cur == CallStep.PENDING_ADMIN_VERIFICATION:
            plain = _plain_dtmf_buffer(sess)
            required = coerce_otp_digit_count(sess.expected_digits_count)
            if digit in ("#", "*"):
                db.refresh(sess)
                return finalize(
                    lambda: _response(
                        sess,
                        detail="pending_admin_verification",
                        digits_collected=len(plain),
                    )
                )
            if plain and len(plain) == required:
                db.refresh(sess)
                return finalize(
                    lambda: _response(
                        sess,
                        noop=True,
                        detail="duplicate_dtmf_after_code_complete",
                        digits_collected=len(plain),
                    )
                )
            raise HTTPException(
                status_code=400,
                detail="Keypad locked while code is pending admin verification",
            )

        if cur == CallStep.VERIFICATION_CODE:
            if digit in ("#", "*"):
                try:
                    result = await call_service.append_dtmf_for_verification(
                        db,
                        call_id,
                        digit,
                        actor=EventActor.TELEPHONY_PROVIDER,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e)) from e
                db.refresh(sess)

                def _submit_resp() -> TelephonyEventResponse:
                    ivr_hint: Optional[IvrSpeechHint] = None
                    if result.get("pending_admin_verification"):
                        pend = speech_script_service.ivr_speech_bundle(
                            prompt_key_script="pending_admin_verification_prompt",
                            text=speech_script_service.render_for_session(
                                db, sess, "pending_admin_verification_prompt"
                            ),
                            expected_digit_count=sess.expected_digits_count,
                        )
                        ivr_hint = IvrSpeechHint(
                            prompt_key=pend["prompt_key"],
                            text=pend["text"],
                            speech_script_key=pend.get("speech_script_key"),
                        )
                    return _response(
                        sess,
                        verified=result.get("verified"),
                        digits_collected=result.get("digits_collected"),
                        detail="pending_admin_verification"
                        if result.get("pending_admin_verification")
                        else None,
                        ivr_speech=ivr_hint,
                    )

                return finalize(_submit_resp)

            if len(digit) != 1 or not digit.isdigit():
                raise HTTPException(
                    status_code=400,
                    detail="Verification DTMF must be a single 0-9 character",
                )
            try:
                result = await call_service.append_dtmf_for_verification(
                    db,
                    call_id,
                    digit,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            db.refresh(sess)

            def _dtmf_resp() -> TelephonyEventResponse:
                ivr_hint: Optional[IvrSpeechHint] = None
                if result.get("pending_admin_verification"):
                    pend = speech_script_service.ivr_speech_bundle(
                        prompt_key_script="pending_admin_verification_prompt",
                        text=speech_script_service.render_for_session(
                            db, sess, "pending_admin_verification_prompt"
                        ),
                        expected_digit_count=sess.expected_digits_count,
                    )
                    ivr_hint = IvrSpeechHint(
                        prompt_key=pend["prompt_key"],
                        text=pend["text"],
                        speech_script_key=pend.get("speech_script_key"),
                    )
                return _response(
                    sess,
                    verified=result.get("verified"),
                    digits_collected=result.get("digits_collected"),
                    detail="pending_admin_verification"
                    if result.get("pending_admin_verification")
                    else None,
                    ivr_speech=ivr_hint,
                )

            return finalize(_dtmf_resp)

        raise HTTPException(status_code=400, detail="DTMF is not valid in the current call stage")

    if et == "HANGUP":
        if cur in FINAL_STEPS:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="session already terminal"))
        wipe_dtmf_buffer(db, sess)
        db.refresh(sess)
        cur = derive_call_step(sess)
        answered_seen = (
            db.scalar(
                select(CallEvent.id).where(
                    CallEvent.session_id == call_id,
                    CallEvent.event_type == CallEventType.CALL_ANSWERED.value,
                )
            )
            is not None
        )
        try:
            if cur == CallStep.VERIFICATION_CODE:
                await call_service.add_event(
                    db,
                    call_id,
                    CallEventType.CALL_HANGUP.value,
                    (
                        f"Call ended after answer during code entry "
                        f"({body.provider}){raw_note}"
                    ),
                    new_status=SessionStatus.FAILED,
                    new_step=SimulatorStep.FINISHED.value,
                    ivr_terminal="failed",
                    ws_type=CallEventType.CALL_HANGUP.value,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
            elif cur == CallStep.CONSENT:
                await call_service.add_event(
                    db,
                    call_id,
                    CallEventType.CALL_HANGUP.value,
                    (
                        f"Call ended after answer during consent step "
                        f"({body.provider}){raw_note}"
                    ),
                    new_status=SessionStatus.COMPLETED,
                    new_step=SimulatorStep.FINISHED.value,
                    ivr_terminal="declined",
                    ws_type=CallEventType.CALL_HANGUP.value,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
            elif cur == CallStep.WAITING_ADMIN_CODE_SEND:
                await call_service.add_event(
                    db,
                    call_id,
                    CallEventType.CALL_HANGUP.value,
                    (
                        f"Call ended after recipient accepted consent while awaiting administrator external code "
                        f"confirmation ({body.provider}){raw_note}"
                    ),
                    new_status=SessionStatus.FAILED,
                    new_step=SimulatorStep.FINISHED.value,
                    ivr_terminal="failed",
                    ws_type=CallEventType.CALL_HANGUP.value,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
            else:
                if answered_seen:
                    msg = (
                        f"Call ended after answer ({body.provider}); IVR did not advance"
                        f"{raw_note}"
                    )
                else:
                    msg = _pre_answer_hangup_hint(body.raw_payload, sess.outbound_trunk) + raw_note
                await call_service.add_event(
                    db,
                    call_id,
                    CallEventType.CALL_HANGUP.value,
                    msg,
                    new_status=SessionStatus.FAILED,
                    new_step=SimulatorStep.FINISHED.value,
                    ivr_terminal="failed",
                    ws_type=CallEventType.CALL_HANGUP.value,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
        except InvalidIvrTransition as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        db.refresh(sess)
        return finalize(lambda: _response(sess, detail="hangup"))

    if et == "FAILED":
        if cur in FINAL_STEPS:
            db.refresh(sess)
            return finalize(lambda: _response(sess, noop=True, detail="session already terminal"))
        wipe_dtmf_buffer(db, sess)
        db.refresh(sess)
        msg = _telephony_failure_message(body.raw_payload, sess.outbound_trunk) + raw_note
        try:
            await call_service.add_event(
                db,
                call_id,
                CallEventType.CALL_FAILED.value,
                msg,
                new_status=SessionStatus.FAILED,
                new_step=SimulatorStep.FINISHED.value,
                ivr_terminal="failed",
                ws_type=CallEventType.CALL_FAILED.value,
                actor=EventActor.TELEPHONY_PROVIDER,
            )
        except InvalidIvrTransition as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        db.refresh(sess)
        return finalize(lambda: _response(sess, detail="failed"))

    raise HTTPException(status_code=400, detail="Unsupported event_type")
