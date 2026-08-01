import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import InvalidRequestError as SAInvalidRequestError
from sqlalchemy.orm import Session

from .. import config as app_config
from ..event_types import CallEventType
from ..exceptions import InvalidIvrTransition, OutboundCallBlocked, RateLimitExceeded
from ..ivr_state import (
    CallStep,
    derive_call_step,
    resolve_next_call_step,
    validate_transition,
)
from ..speech_volume import clamp_speech_volume_percent
from ..models import (
    CallEvent,
    CallSession,
    EventActor,
    SessionStatus,
    SimulatorStep,
    VerificationAttempt,
)
from ..schemas import CallEventRead, CallSessionRead
from ..security import decrypt_dtmf_buffer, encrypt_dtmf_buffer, mask_digits_in_text
from ..language_support import detect_language_from_phone, normalize_language_code
from ..websocket_manager import manager
from . import speech_script_service
from .speech_script_service import coerce_otp_digit_count, get_otp_digit_count
from .verification_service import generate_student_card_demo_code, hash_code_for_storage
from .virtual_call_device import virtual_call_device

logger = logging.getLogger(__name__)

MAX_VERIFICATION_ATTEMPTS = 3
OTP_SUBMIT_DIGITS = frozenset({"#", "*"})


def utcnow():
    return datetime.now(timezone.utc)


def _utc_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def count_sessions_today_for_phone(db: Session, phone: str) -> int:
    target = normalize_phone_digits(phone)
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(select(CallSession).where(CallSession.created_at >= start)).all()
    return sum(1 for r in rows if normalize_phone_digits(r.phone_number) == target)


def _plain_dtmf_buffer(sess: CallSession) -> str:
    return decrypt_dtmf_buffer(
        sess.dtmf_buffer,
        secret=app_config.DTMF_BUFFER_SECRET,
        session_id=sess.id,
    )


def _set_dtmf_buffer_cipher(sess: CallSession, plain: str) -> None:
    sess.dtmf_buffer = encrypt_dtmf_buffer(
        plain,
        secret=app_config.DTMF_BUFFER_SECRET,
        session_id=sess.id,
    )
    sess.buffer_updated_at = utcnow() if plain else None
    sess.updated_at = utcnow()


def wipe_dtmf_buffer(db: Session, sess: CallSession) -> None:
    """Clear persisted DTMF ciphertext and buffer timestamp."""
    sess.dtmf_buffer = ""
    sess.buffer_updated_at = None
    sess.updated_at = utcnow()
    db.add(sess)
    db.commit()


def enforce_phone_daily_limit(db: Session, phone: str) -> None:
    limit = app_config.MAX_CALLS_PER_PHONE_PER_DAY
    if limit <= 0:
        return
    n = count_sessions_today_for_phone(db, phone)
    if n >= limit:
        raise RateLimitExceeded(
            f"Maximum {limit} calls per phone number per day (UTC) exceeded"
        )


_OUTBOUND_ACTIVE_STATUSES = frozenset(
    {
        SessionStatus.PENDING.value,
        SessionStatus.DIALING.value,
        SessionStatus.RINGING.value,
        SessionStatus.CONNECTED.value,
        SessionStatus.COLLECTING.value,
        SessionStatus.PENDING_ADMIN_VERIFICATION.value,
    }
)

_OUTBOUND_TERMINAL_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED.value,
        SessionStatus.FAILED.value,
        SessionStatus.CANCELLED.value,
        SessionStatus.VERIFIED.value,
    }
)


def reconcile_stale_outbound_sessions(db: Session) -> int:
    """Mark long-idle active sessions as failed so they no longer block new outbound calls."""
    stale_minutes = app_config.SIPUP_ACTIVE_CALL_STALE_MINUTES
    cutoff = _utc_dt(utcnow()) - timedelta(minutes=stale_minutes)
    rows = db.scalars(
        select(CallSession).where(CallSession.status.in_(_OUTBOUND_ACTIVE_STATUSES))
    ).all()
    closed = 0
    for sess in rows:
        last_touch = _utc_dt(sess.updated_at or sess.created_at or utcnow())
        if last_touch >= cutoff:
            continue
        preserved_updated = last_touch.replace(tzinfo=None)
        db.execute(
            update(CallSession)
            .where(CallSession.id == sess.id)
            .values(
                status=SessionStatus.FAILED.value,
                simulator_step=SimulatorStep.FINISHED.value,
                ivr_outcome="failed",
                updated_at=preserved_updated,
            )
        )
        db.add(
            CallEvent(
                session_id=sess.id,
                event_type=CallEventType.CALL_FAILED.value,
                message=(
                    f"Stale outbound session auto-closed after {stale_minutes}+ minutes with no "
                    "activity (unblocks new SIP UP calls)."
                ),
                actor_type=EventActor.SYSTEM.value,
            )
        )
        closed += 1
    if closed:
        db.commit()
    return closed


def outbound_spacing_status(db: Session) -> dict[str, object]:
    """Return whether a new SIP UP outbound call is allowed and optional cooldown seconds."""
    reconcile_stale_outbound_sessions(db)
    min_gap = app_config.SIPUP_MIN_SECONDS_BETWEEN_CALLS
    active = db.scalars(
        select(CallSession)
        .where(CallSession.status.in_(_OUTBOUND_ACTIVE_STATUSES))
        .order_by(CallSession.created_at.desc())
        .limit(1)
    ).first()
    if active is not None:
        return {
            "allowed": False,
            "wait_seconds": 0,
            "reason": "active_call",
            "message": (
                "Another call is still in progress. Wait until it finishes before starting a new one."
            ),
            "active_call_id": active.id,
            "min_seconds_between_calls": min_gap,
        }

    if min_gap <= 0:
        return {
            "allowed": True,
            "wait_seconds": 0,
            "reason": None,
            "message": None,
            "active_call_id": None,
            "min_seconds_between_calls": min_gap,
        }

    last_terminal = db.scalars(
        select(CallSession)
        .where(CallSession.status.in_(_OUTBOUND_TERMINAL_STATUSES))
        .order_by(CallSession.updated_at.desc())
        .limit(1)
    ).first()
    if last_terminal is None:
        return {
            "allowed": True,
            "wait_seconds": 0,
            "reason": None,
            "message": None,
            "active_call_id": None,
            "min_seconds_between_calls": min_gap,
        }

    terminal_at = last_terminal.updated_at or last_terminal.created_at
    if terminal_at is None:
        return {
            "allowed": True,
            "wait_seconds": 0,
            "reason": None,
            "message": None,
            "active_call_id": None,
            "min_seconds_between_calls": min_gap,
        }

    elapsed = (_utc_dt(utcnow()) - _utc_dt(terminal_at)).total_seconds()
    remaining = int(min_gap - elapsed)
    if remaining > 0:
        return {
            "allowed": False,
            "wait_seconds": remaining,
            "reason": "cooldown",
            "message": (
                f"Wait {remaining}s before the next SIP UP call so the carrier can release the "
                f"previous channel (avoids intermittent SIP 403 rejects)."
            ),
            "active_call_id": None,
            "min_seconds_between_calls": min_gap,
        }

    return {
        "allowed": True,
        "wait_seconds": 0,
        "reason": None,
        "message": None,
        "active_call_id": None,
        "min_seconds_between_calls": min_gap,
    }


def enforce_outbound_call_spacing(db: Session) -> None:
    status = outbound_spacing_status(db)
    if status.get("allowed"):
        return
    wait = int(status.get("wait_seconds") or 0)
    message = str(status.get("message") or "Outbound call blocked by spacing rules.")
    raise OutboundCallBlocked(message, wait_seconds=wait)


class CallService:
    def outbound_spacing_status(self, db: Session) -> dict[str, object]:
        return outbound_spacing_status(db)

    def enforce_outbound_call_spacing(self, db: Session) -> None:
        enforce_outbound_call_spacing(db)

    def reconcile_stale_outbound_sessions(self, db: Session) -> int:
        return reconcile_stale_outbound_sessions(db)

    def create_call_session(
        self,
        db: Session,
        *,
        name: str,
        university: str,
        phone_number: str,
        outbound_trunk: Optional[str] = None,
        outbound_caller_id: Optional[str] = None,
        speech_engine: str = "luvvoice",
        luvvoice_voice_id: Optional[str] = None,
        speech_volume_percent: int = 88,
        language: Optional[str] = None,
    ) -> tuple[CallSession, str]:
        """Persist a new session with hashed verification code. Returns (session, plaintext_code) for one-time response only."""
        enforce_phone_daily_limit(db, phone_number)
        otp_count = get_otp_digit_count(db)
        plain = generate_student_card_demo_code(otp_count)
        code_hash = hash_code_for_storage(plain)
        stored_trunk = "sip_up"
        stored_caller_id = (outbound_caller_id or "").strip() or None
        engine = (speech_engine or "luvvoice").strip().lower() or "luvvoice"
        if engine not in {"free", "luvvoice"}:
            engine = "luvvoice"
        stored_voice = (luvvoice_voice_id or "").strip() or None
        stored_volume = clamp_speech_volume_percent(speech_volume_percent)
        # Auto-detect language from phone number if not explicitly provided
        stored_language = normalize_language_code(language) if language else detect_language_from_phone(phone_number.strip())
        row = CallSession(
            name=name.strip(),
            university=university.strip(),
            exam_date="",
            phone_number=phone_number.strip(),
            verification_code_hash=code_hash,
            expected_digits_count=otp_count,
            outbound_trunk=stored_trunk,
            outbound_caller_id=stored_caller_id,
            speech_engine=engine,
            luvvoice_voice_id=stored_voice,
            speech_volume_percent=stored_volume,
            language=stored_language,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, plain

    async def add_event(
        self,
        db: Session,
        session_id: str,
        event_type: str,
        message: str,
        *,
        new_status: Optional[SessionStatus] = None,
        new_step: Optional[str] = None,
        ivr_terminal: Optional[str] = None,
        ws_type: str = "call_event",
        actor: EventActor = EventActor.SYSTEM,
        ivr_speech: Optional[dict[str, str]] = None,
        broadcast_session_update: bool = True,
    ) -> CallEvent:
        """Persist events, optional audit row for status/step transitions, broadcast."""
        sess = db.get(CallSession, session_id)
        prev_status = sess.status if sess else None
        prev_step = sess.simulator_step if sess else None

        masked_message = mask_digits_in_text(message)
        main_event = CallEvent(
            session_id=session_id,
            event_type=event_type,
            message=masked_message,
            actor_type=actor.value,
        )
        db.add(main_event)

        if sess:
            current_step = derive_call_step(sess)
            try:
                resolved = resolve_next_call_step(
                    sess,
                    new_status=new_status,
                    new_step=new_step,
                    ivr_terminal=ivr_terminal,
                )
            except ValueError as e:
                raise InvalidIvrTransition(str(e)) from e
            validate_transition(current_step, resolved)

            sess.updated_at = utcnow()
            if new_status is not None:
                sess.status = new_status.value
            if new_step is not None:
                sess.simulator_step = new_step
            if ivr_terminal is not None:
                sess.ivr_outcome = ivr_terminal

        audit_event: Optional[CallEvent] = None
        audit_parts = []
        if sess and new_status is not None and prev_status != sess.status:
            audit_parts.append(f"status {prev_status}->{sess.status}")
        if sess and new_step is not None and prev_step != new_step:
            audit_parts.append(f"step {prev_step}->{new_step}")
        if audit_parts:
            audit_event = CallEvent(
                session_id=session_id,
                event_type=CallEventType.AUDIT_STATE_CHANGE.value,
                message="; ".join(audit_parts),
                actor_type=EventActor.SYSTEM.value,
            )
            db.add(audit_event)

        db.commit()
        try:
            db.refresh(main_event)
        except SAInvalidRequestError:
            if getattr(main_event, "id", None) is not None:
                main_event = db.get(CallEvent, main_event.id)
        if sess:
            try:
                db.refresh(sess)
            except SAInvalidRequestError:
                if getattr(sess, "id", None) is not None:
                    sess = db.get(CallSession, sess.id)
        if audit_event is not None:
            try:
                db.refresh(audit_event)
            except SAInvalidRequestError:
                if getattr(audit_event, "id", None) is not None:
                    audit_event = db.get(CallEvent, audit_event.id)

        ws_payload: dict[str, object] = {
            "type": ws_type,
            "event": CallEventRead.model_validate(main_event).model_dump(mode="json"),
        }
        if ivr_speech:
            ws_payload["ivr_speech"] = ivr_speech
        broadcasts = [manager.broadcast_json(ws_payload)]
        if audit_event is not None:
            broadcasts.append(
                manager.broadcast_json(
                    {
                        "type": "call_event",
                        "event": CallEventRead.model_validate(audit_event).model_dump(mode="json"),
                    }
                )
            )
        if sess and broadcast_session_update:
            broadcasts.append(
                manager.broadcast_json(
                    {
                        "type": "session_update",
                        "session": CallSessionRead.model_validate(sess).model_dump(mode="json"),
                    }
                )
            )
        await asyncio.gather(*broadcasts)
        virtual_call_device.handle_event(sess, main_event)
        return main_event

    def update_status(self, db: Session, session_id: str, status: SessionStatus) -> Optional[CallSession]:
        sess = db.get(CallSession, session_id)
        if not sess:
            return None
        current_step = derive_call_step(sess)
        resolved = resolve_next_call_step(sess, new_status=status, new_step=None)
        validate_transition(current_step, resolved)
        sess.status = status.value
        sess.updated_at = utcnow()
        db.commit()
        db.refresh(sess)
        return sess

    async def handle_consent_digit(
        self,
        db: Session,
        session_id: str,
        digit: str,
        *,
        actor: EventActor,
        include_ivr_on_events: bool = False,
    ) -> dict:
        """Keypad at consent: record 1 or 2, then always proceed to OTP entry."""
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        if derive_call_step(sess) != CallStep.CONSENT:
            raise ValueError("Not at consent step")
        if digit not in ("1", "2"):
            raise ValueError("Consent step expects digit 1 or 2")

        wipe_dtmf_buffer(db, sess)
        db.refresh(sess)

        if digit == "1":
            choice_event = CallEventType.RECIPIENT_ACCEPTED.value
            choice_message = "Recipient pressed 1 (confirm) at consent"
        else:
            choice_event = CallEventType.RECIPIENT_DECLINED.value
            choice_message = "Recipient pressed 2 (decline) at consent"

        code_sent_txt = speech_script_service.render_for_session(db, sess, "code_sent_prompt")
        code_sent_ivr = speech_script_service.ivr_speech_bundle(
            prompt_key_script="code_sent_prompt",
            text=code_sent_txt,
            expected_digit_count=sess.expected_digits_count,
        )
        await self.add_event(
            db,
            session_id,
            choice_event,
            choice_message,
            new_status=SessionStatus.COLLECTING,
            new_step=SimulatorStep.VERIFICATION_CODE.value,
            ws_type=choice_event,
            actor=actor,
            ivr_speech=code_sent_ivr if include_ivr_on_events else None,
        )
        db.refresh(sess)
        return {
            "ok": True,
            "step": sess.simulator_step,
            "consent_digit": digit,
            "ivr_speech": code_sent_ivr,
        }

    async def submit_digits_for_admin_verification(
        self,
        db: Session,
        session_id: str,
        digits: str,
        *,
        actor: EventActor = EventActor.USER,
    ) -> dict:
        """Store entered DTMF encrypted and wait for an admin approve/reject decision."""
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        raw = digits.strip()
        if not raw.isdigit():
            raise ValueError("Digits must be numeric only")
        if len(raw) != coerce_otp_digit_count(sess.expected_digits_count):
            required = coerce_otp_digit_count(sess.expected_digits_count)
            raise ValueError(f"OTP code must be exactly {required} digits")
        if derive_call_step(sess) != CallStep.VERIFICATION_CODE:
            raise ValueError("Session is not accepting keypad input")
        if sess.wrong_code_attempts >= MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("Maximum verification attempts exceeded")

        _set_dtmf_buffer_cipher(sess, raw)
        db.commit()
        db.refresh(sess)

        await self.add_event(
            db,
            session_id,
            CallEventType.DIGITS_RECEIVED.value,
            f"Keypad entry complete ({len(raw)} digits): {raw}",
            ws_type=CallEventType.DIGITS_RECEIVED.value,
            actor=actor,
            broadcast_session_update=False,
        )
        await self.add_event(
            db,
            session_id,
            CallEventType.PENDING_ADMIN_VERIFICATION.value,
            f"Entered code pending admin verification: {raw}",
            new_status=SessionStatus.PENDING_ADMIN_VERIFICATION,
            new_step=SimulatorStep.PENDING_ADMIN_VERIFICATION.value,
            ws_type=CallEventType.PENDING_ADMIN_VERIFICATION.value,
            actor=actor,
            # Omit ivr_speech here — the callee hears this line only via the telephony webhook response
            # (`/api/telephony/events` DTMF). Including it also on this WS fan-out risks duplicate cues if
            # any client replays payloads; SIP UP bridge already skips WS for this type when ivr existed.
        )
        db.refresh(sess)
        return {
            "verified": None,
            "pending_admin_verification": True,
            "digits_collected": len(raw),
            "masked_entered_code": sess.masked_entered_code,
        }

    async def confirm_admin_external_code_sent(self, db: Session, session_id: str) -> dict:
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        if derive_call_step(sess) == CallStep.VERIFICATION_CODE:
            logger.info(
                "admin_external_code_sent_idempotent noop session_prefix=%s step=%s",
                session_id[:8],
                sess.simulator_step,
            )
            return {
                "ok": True,
                "idempotent": True,
                "step": sess.simulator_step,
                "session_status": sess.status,
            }
        if derive_call_step(sess) != CallStep.WAITING_ADMIN_CODE_SEND:
            raise ValueError("Call is not waiting for administrator Done — code sent confirmation")
        wipe_dtmf_buffer(db, sess)
        db.refresh(sess)
        rendered = speech_script_service.render_for_session(db, sess, "code_sent_prompt")
        ivr = speech_script_service.ivr_speech_bundle(
            prompt_key_script="code_sent_prompt",
            text=rendered,
            expected_digit_count=sess.expected_digits_count,
        )
        await self.add_event(
            db,
            session_id,
            CallEventType.ADMIN_CODE_SENT_CONFIRMED.value,
            "Administrator confirmed code was sent via the client's official external platform; keypad entry unlocked.",
            new_step=SimulatorStep.VERIFICATION_CODE.value,
            ws_type=CallEventType.ADMIN_CODE_SENT_CONFIRMED.value,
            actor=EventActor.ADMIN,
            ivr_speech=ivr,
        )
        logger.info(
            "admin_external_code_sent_event_emitted session_prefix=%s emitted=%s step=%s",
            session_id[:8],
            CallEventType.ADMIN_CODE_SENT_CONFIRMED.value,
            SimulatorStep.VERIFICATION_CODE.value,
        )
        db.refresh(sess)
        return {"ok": True, "step": sess.simulator_step, "session_status": sess.status}

    async def approve_admin_verification(self, db: Session, session_id: str) -> dict:
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        if derive_call_step(sess) != CallStep.PENDING_ADMIN_VERIFICATION:
            raise ValueError("Session is not pending admin verification")

        plain = _plain_dtmf_buffer(sess)
        db.add(
            VerificationAttempt(
                session_id=session_id,
                success=True,
                digit_count=len(plain),
            )
        )
        approved_txt = speech_script_service.render_for_session(db, sess, "approved_prompt")
        bye_txt = speech_script_service.render_for_session(db, sess, "goodbye_prompt")
        callee_farewell = speech_script_service.merge_terminal_approval_voice(
            approved_line=approved_txt,
            goodbye_line=bye_txt,
        )
        await self.add_event(
            db,
            session_id,
            CallEventType.ADMIN_VERIFICATION_APPROVED.value,
            "Admin approved the official verification code entry",
            ws_type=CallEventType.ADMIN_VERIFICATION_APPROVED.value,
            actor=EventActor.ADMIN,
            ivr_speech=speech_script_service.ivr_speech_bundle(
                prompt_key_script="approved_prompt",
                text=callee_farewell,
                expected_digit_count=sess.expected_digits_count,
            ),
        )
        await self.add_event(
            db,
            session_id,
            CallEventType.VERIFICATION_SUCCESS.value,
            "Internal verification approved by admin",
            new_status=SessionStatus.COMPLETED,
            new_step=SimulatorStep.FINISHED.value,
            ivr_terminal="verified",
            ws_type=CallEventType.VERIFICATION_SUCCESS.value,
            actor=EventActor.ADMIN,
        )
        return {"ok": True, "status": SessionStatus.COMPLETED.value, "step": SimulatorStep.FINISHED.value}

    async def reject_admin_verification(self, db: Session, session_id: str) -> dict:
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        if derive_call_step(sess) != CallStep.PENDING_ADMIN_VERIFICATION:
            raise ValueError("Session is not pending admin verification")
        if sess.wrong_code_attempts >= MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("Maximum verification attempts exceeded")

        plain = _plain_dtmf_buffer(sess)
        sess.wrong_code_attempts += 1
        n = sess.wrong_code_attempts
        db.add(
            VerificationAttempt(
                session_id=session_id,
                success=False,
                digit_count=len(plain),
            )
        )
        _set_dtmf_buffer_cipher(sess, "")
        db.commit()
        db.refresh(sess)

        if n >= MAX_VERIFICATION_ATTEMPTS:
            # Terminal wording matches consent-decline cue: single goodbye before hangup.
            rendered_terminal = speech_script_service.render_for_session(db, sess, "declined_prompt")
            await self.add_event(
                db,
                session_id,
                CallEventType.ADMIN_VERIFICATION_REJECTED.value,
                f"Admin rejected internal verification entry; maximum attempts reached ({MAX_VERIFICATION_ATTEMPTS})",
                new_status=SessionStatus.FAILED,
                new_step=SimulatorStep.FINISHED.value,
                ivr_terminal="failed",
                ws_type=CallEventType.ADMIN_VERIFICATION_REJECTED.value,
                actor=EventActor.ADMIN,
                ivr_speech=speech_script_service.ivr_speech_bundle(
                    prompt_key_script="declined_prompt",
                    text=rendered_terminal,
                    expected_digit_count=sess.expected_digits_count,
                ),
            )
            return {
                "ok": True,
                "rejected": True,
                "attempt": n,
                "attempts_exhausted": True,
                "status": SessionStatus.FAILED.value,
            }

        rendered_retry = speech_script_service.render_for_session(db, sess, "rejected_retry_prompt")
        await self.add_event(
            db,
            session_id,
            CallEventType.ADMIN_VERIFICATION_REJECTED.value,
            f"Admin rejected internal verification entry (attempt {n} of {MAX_VERIFICATION_ATTEMPTS})",
            new_status=SessionStatus.COLLECTING,
            new_step=SimulatorStep.VERIFICATION_CODE.value,
            ws_type=CallEventType.ADMIN_VERIFICATION_REJECTED.value,
            actor=EventActor.ADMIN,
            ivr_speech=speech_script_service.ivr_speech_bundle(
                prompt_key_script="rejected_retry_prompt",
                text=rendered_retry,
                expected_digit_count=sess.expected_digits_count,
            ),
        )
        return {
            "ok": True,
            "rejected": True,
            "attempt": n,
            "remaining_attempts": MAX_VERIFICATION_ATTEMPTS - n,
            "status": SessionStatus.COLLECTING.value,
            "step": SimulatorStep.VERIFICATION_CODE.value,
        }

    async def admin_end_active_call(self, db: Session, session_id: str) -> dict:
        """Mark a non-terminal session cancelled so outbound spacing allows a new call."""
        from .outbound_simulation import cancel_mock_task

        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        if sess.status in _OUTBOUND_TERMINAL_STATUSES:
            raise ValueError("Session is already finished")

        await cancel_mock_task(session_id)
        await self.add_event(
            db,
            session_id,
            CallEventType.CALL_HANGUP.value,
            "Call ended by operator",
            new_status=SessionStatus.CANCELLED,
            new_step=SimulatorStep.FINISHED.value,
            ivr_terminal="cancelled",
            ws_type=CallEventType.CALL_HANGUP.value,
            actor=EventActor.ADMIN,
        )
        return {
            "ok": True,
            "call_id": session_id,
            "status": SessionStatus.CANCELLED.value,
            "step": SimulatorStep.FINISHED.value,
        }

    async def verify_digits(
        self,
        db: Session,
        session_id: str,
        digits: str,
        *,
        actor: EventActor = EventActor.USER,
    ) -> bool:
        """Compatibility wrapper: code entry now waits for admin verification."""
        result = await self.submit_digits_for_admin_verification(
            db,
            session_id,
            digits,
            actor=actor,
        )
        return bool(result.get("verified"))

    async def append_dtmf_for_verification(
        self,
        db: Session,
        session_id: str,
        digit: str,
        *,
        actor: EventActor = EventActor.USER,
    ) -> dict:
        """Append one DTMF digit (encrypted at rest); auto-submit when the configured digit count is reached."""
        sess = db.get(CallSession, session_id)
        if not sess:
            raise ValueError("Session not found")
        d = (digit or "").strip()
        if derive_call_step(sess) != CallStep.VERIFICATION_CODE:
            raise ValueError("Session is not accepting verification DTMF")
        if sess.wrong_code_attempts >= MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("Maximum verification attempts exceeded")

        max_digits = coerce_otp_digit_count(sess.expected_digits_count)
        plain = _plain_dtmf_buffer(sess)

        if d in OTP_SUBMIT_DIGITS:
            if len(plain) != max_digits:
                raise ValueError(
                    f"Enter exactly {max_digits} digits before submitting "
                    f"(current length {len(plain)})"
                )
            return await self.submit_digits_for_admin_verification(
                db,
                session_id,
                plain,
                actor=actor,
            )

        if len(d) != 1 or not d.isdigit():
            raise ValueError("DTMF digit must be a single 0-9 character")

        if len(plain) >= max_digits:
            raise ValueError(f"Maximum {max_digits} digits allowed")

        plain = plain + d

        if len(plain) == max_digits:
            return await self.submit_digits_for_admin_verification(
                db,
                session_id,
                plain,
                actor=actor,
            )

        _set_dtmf_buffer_cipher(sess, plain)
        db.commit()
        db.refresh(sess)
        await self.add_event(
            db,
            session_id,
            CallEventType.DIGIT_RECEIVED.value,
            f"DTMF digit received during verification (buffer length {len(plain)} of up to {max_digits})",
            ws_type=CallEventType.DIGIT_RECEIVED.value,
            actor=EventActor.TELEPHONY_PROVIDER,
            broadcast_session_update=False,
        )
        return {"verified": None, "digits_collected": len(plain)}


call_service = CallService()

# Re-export for routers that gate on the same cap as enter-code
MAX_CODE_ATTEMPTS = MAX_VERIFICATION_ATTEMPTS
