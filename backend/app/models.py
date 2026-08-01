import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .ivr_state import CallStatus as SessionStatus


def utcnow():
    return datetime.now(timezone.utc)


class SimulatorStep(str, enum.Enum):
    IDLE = "idle"
    CONSENT = "consent"
    WAITING_ADMIN_CODE_SEND = "waiting_admin_code_send"
    VERIFICATION_CODE = "verification_code"
    PENDING_ADMIN_VERIFICATION = "pending_admin_verification"
    FINISHED = "finished"


class EventActor(str, enum.Enum):
    """Who triggered or originated an auditable call event."""

    SYSTEM = "system"
    USER = "user"
    TELEPHONY_PROVIDER = "telephony_provider"
    ADMIN = "admin"


class SpeechScriptTemplate(Base):
    """Admin-editable speech script fragments (validated on save).

    Rows are seeded by Alembic; missing keys fall back to in-code defaults on read.
    """

    __tablename__ = "speech_script_templates"

    script_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Bumped on logout to invalidate every previously issued JWT for this admin.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminLoginAttempt(Base):
    """Login audit trail + source data for rate limiting/lockout (see routers.auth.login)."""

    __tablename__ = "admin_login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CallSession(Base):
    __tablename__ = "call_sessions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    university: Mapped[str] = mapped_column(String(255), nullable=False)
    exam_date: Mapped[str] = mapped_column(
        String(32),
        default="",
        nullable=False,
        doc="Exam date shown in consent IVR (e.g. 13/05/2026).",
    )
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=SessionStatus.PENDING.value, nullable=False, index=True
    )
    simulator_step: Mapped[str] = mapped_column(
        String(32), default=SimulatorStep.IDLE.value, nullable=False
    )
    ivr_outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dtmf_buffer: Mapped[str] = mapped_column(
        String(512), default="", nullable=False
    )  # Fernet ciphertext; never plaintext
    expected_digits_count: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
        doc="Admin-configured OTP digit count (4, 6, 8, or 10).",
    )
    buffer_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wrong_code_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    outbound_trunk: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        default=None,
        doc="Outbound SIP trunk for this session (always sip_up).",
    )
    outbound_caller_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        default=None,
        doc="Per-call outbound caller ID (digits) chosen at start.",
    )
    speech_engine: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="luvvoice",
        doc="Callee TTS engine: luvvoice (premium) or free (local say/espeak).",
    )
    luvvoice_voice_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        doc="LuvVoice voice_id when speech_engine=luvvoice.",
    )
    speech_volume_percent: Mapped[int] = mapped_column(
        nullable=False,
        default=88,
        doc="Callee TTS loudness 40–150; ~70 = unity gain on WAV processing.",
    )
    language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="en",
        doc="Language code (e.g. 'en', 'es', 'fr', 'de', 'it', 'pt'). Auto-detected from phone country code.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list["CallEvent"]] = relationship(
        "CallEvent",
        back_populates="session",
        order_by="CallEvent.created_at",
    )
    verification_attempts: Mapped[list["VerificationAttempt"]] = relationship(
        "VerificationAttempt",
        back_populates="session",
        order_by="VerificationAttempt.created_at",
    )
    telephony_receipts: Mapped[list["TelephonyEventReceipt"]] = relationship(
        "TelephonyEventReceipt",
        back_populates="session",
        order_by="TelephonyEventReceipt.created_at",
    )

    @property
    def masked_entered_code(self) -> Optional[str]:
        """Masked keypad submission (last two digits visible) for general session views.

        Safe to include in list/detail API responses and the live WebSocket feed.
        The full digits are available only via ``entered_code`` (used exclusively by
        the dedicated, authenticated, audited admin reveal endpoint — never by the
        general session schema).
        """
        from .security import mask_digits_in_text

        plain = self.entered_code
        return mask_digits_in_text(plain) if plain else None

    @property
    def entered_code(self) -> Optional[str]:
        """Plain keypad submission for administrator comparison (decrypted from buffer).

        Not exposed by ``CallSessionRead`` — only returned by
        ``GET /api/calls/{id}/admin/entered-code``, which authorizes and audit-logs
        each access. Do not add this property to a general-purpose response schema.
        """
        from . import config as app_config
        from .security import decrypt_dtmf_buffer

        plain = decrypt_dtmf_buffer(
            self.dtmf_buffer,
            secret=app_config.DTMF_BUFFER_SECRET,
            session_id=self.id,
        )
        return plain if plain else None


class TelephonyEventReceipt(Base):
    """Idempotency ledger for ``POST /api/telephony/events`` (provider-supplied event id)."""

    __tablename__ = "telephony_event_receipts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_telephony_event_receipt_provider_event",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    call_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("call_sessions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["CallSession"] = relationship("CallSession", back_populates="telephony_receipts")


class CallEvent(Base):
    __tablename__ = "call_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("call_sessions.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), default=EventActor.SYSTEM.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["CallSession"] = relationship("CallSession", back_populates="events")


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("call_sessions.id"), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    digit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["CallSession"] = relationship("CallSession", back_populates="verification_attempts")
