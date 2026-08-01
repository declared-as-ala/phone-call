from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

OutboundTrunk = Literal["sip_up"]
SpeechEngine = Literal["free", "luvvoice"]
LanguageCode = Literal["en", "es", "fr", "de", "it", "pt", "pl", "nl", "ja", "zh"]

from pydantic import BaseModel, Field, field_validator

from .models import EventActor, SessionStatus, SimulatorStep
from .language_support import detect_language_from_phone, normalize_language_code
from .speech_volume import (
    DEFAULT_SPEECH_VOLUME_PERCENT,
    MAX_SPEECH_VOLUME_PERCENT,
    MIN_SPEECH_VOLUME_PERCENT,
    clamp_speech_volume_percent,
)


class CallStartRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    university: str = Field(..., min_length=1, max_length=255)
    phone_number: str = Field(..., min_length=3, max_length=32)
    outbound_trunk: OutboundTrunk = Field(
        default="sip_up",
        description="SIP UP trunk via SipUpTelephonyProvider (SIPUP_* env vars; SIP UP media when configured).",
    )
    outbound_caller_id: Optional[str] = Field(
        default=None,
        description="Per-call outbound CLI (digits only). Overrides SIPUP_OUTBOUND_CALLER_ID for this session.",
        max_length=32,
    )
    speech_engine: SpeechEngine = Field(
        default="luvvoice",
        description='Callee speech: "luvvoice" (premium AI, default) or "free" (local system TTS).',
    )
    luvvoice_voice_id: Optional[str] = Field(
        default=None,
        description="LuvVoice voice_id (e.g. voice-001). Uses LUVVOICE_DEFAULT_VOICE_ID when omitted.",
        max_length=64,
    )
    speech_volume_percent: int = Field(
        default=DEFAULT_SPEECH_VOLUME_PERCENT,
        ge=MIN_SPEECH_VOLUME_PERCENT,
        le=MAX_SPEECH_VOLUME_PERCENT,
        description="Callee TTS loudness (40–150). Default 88 is a balanced test level.",
    )
    language: Optional[LanguageCode] = Field(
        default=None,
        description='Language for IVR prompts and voice (e.g. "en", "es", "fr", "de"). Auto-detects from phone country code if omitted.',
    )

    @field_validator("speech_volume_percent", mode="before")
    @classmethod
    def normalize_speech_volume_percent(cls, v):
        return clamp_speech_volume_percent(v)

    @field_validator("luvvoice_voice_id", mode="before")
    @classmethod
    def normalize_luvvoice_voice_id(cls, v):
        if v is None:
            return None
        raw = str(v).strip()
        return raw or None

    @field_validator("outbound_caller_id", mode="before")
    @classmethod
    def normalize_outbound_caller_id(cls, v):
        if v is None:
            return None
        raw = str(v).strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 3:
            raise ValueError("outbound_caller_id must be at least 3 digits")
        return digits

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, v):
        raw = str(v or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return raw
        if len(digits) > 15:
            raise ValueError(
                "phone_number must be at most 15 digits (E.164). "
                "Enter only the recipient number — do not paste caller ID or multiple numbers."
            )
        # Always canonicalize to +E.164 digits so downstream dial normalization sees explicit CC.
        return f"+{digits}"

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, v):
        if v is None:
            return None
        return normalize_language_code(v)


class CallStartResponse(BaseModel):
    call_id: str
    demo_code: Optional[str] = Field(
        default=None,
        description="Present only when APP_ENV is development/dev/local.",
    )


class AdminRead(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str = "admin"

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=12, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=255)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminRead


class CallSessionRead(BaseModel):
    id: str
    name: str
    university: str
    phone_number: str
    outbound_trunk: Optional[str] = Field(
        default=None,
        description="Always sip_up for outbound calls.",
    )
    outbound_caller_id: Optional[str] = Field(
        default=None,
        description="Caller ID used for this outbound leg when set at call start.",
    )
    speech_engine: SpeechEngine = "luvvoice"
    luvvoice_voice_id: Optional[str] = Field(
        default=None,
        description="LuvVoice voice used when speech_engine=luvvoice.",
    )
    status: SessionStatus
    simulator_step: str = SimulatorStep.IDLE.value
    ivr_outcome: Optional[str] = None
    wrong_code_attempts: int = 0
    masked_entered_code: Optional[str] = Field(
        default=None,
        description="Entered digits with only the last two visible (e.g. '****56'). "
        "The full code is available only via GET /api/calls/{id}/admin/entered-code.",
    )
    expected_digits_count: int = 10
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("status", mode="before")
    @classmethod
    def coerce_status(cls, v):
        if isinstance(v, SessionStatus):
            return v
        return SessionStatus(v)


class CallEventRead(BaseModel):
    id: int
    session_id: str
    event_type: str
    message: str
    actor_type: EventActor = EventActor.SYSTEM
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("actor_type", mode="before")
    @classmethod
    def coerce_actor(cls, v):
        if isinstance(v, EventActor):
            return v
        return EventActor(v)


class SimulatorDigitPress(BaseModel):
    digit: str = Field(..., min_length=1, max_length=1, pattern=r"^[12]$")


class SimulatorEnterCode(BaseModel):
    digits: str = Field(..., min_length=1, max_length=32)


class SimulatorAction(BaseModel):
    action: str = Field(
        ...,
        description="One of: start_call, hangup, submit_digits",
    )
    digits: Optional[str] = Field(
        default=None,
        description="For submit_digits only; numeric string.",
        max_length=32,
    )


TelephonyProviderLiteral = Literal["mock", "sip_up", "client_api"]
TelephonyWebhookEventLiteral = Literal["RINGING", "ANSWERED", "DTMF", "HANGUP", "FAILED"]


class TelephonyEventRequest(BaseModel):
    provider: TelephonyProviderLiteral
    provider_call_id: Optional[str] = Field(default=None, max_length=128)
    provider_event_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Provider-unique id for this webhook delivery; replays return duplicate_ignored.",
    )
    call_id: UUID
    event_type: TelephonyWebhookEventLiteral
    digit: Optional[str] = Field(default=None, max_length=8)
    raw_payload: Optional[dict[str, Any]] = None

    @field_validator("provider_event_id", mode="before")
    @classmethod
    def blank_provider_event_id_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v


WebhookStatusLiteral = Literal["duplicate_ignored"]



class IvrSpeechHint(BaseModel):
    """Consumed by SIP UP media bridge for callee playback."""

    prompt_key: str = Field(description="Short key used by Asterisk playback mapping / TTS cache.")
    text: str
    speech_script_key: Optional[str] = Field(default=None, description="Source row key in dashboard DB.")


class TelephonyEventResponse(BaseModel):
    ok: bool = True
    noop: bool = False
    detail: Optional[str] = None
    simulator_step: Optional[str] = None
    session_status: Optional[str] = Field(
        default=None,
        description="Value of call_sessions.status after handling (not the idempotency outcome).",
    )
    status: Optional[WebhookStatusLiteral] = Field(
        default=None,
        description="duplicate_ignored when provider_event_id was already processed.",
    )
    verified: Optional[bool] = None
    digits_collected: Optional[int] = None
    ivr_speech: Optional[IvrSpeechHint] = None


class SpeechScriptsPayload(BaseModel):
    scripts: dict[str, str]
    otp_digit_count: Optional[int] = Field(
        default=None,
        description="Admin-configured OTP length (4, 6, 8, or 10 digits).",
    )


class SipUpAccountSettingsRead(BaseModel):
    label: str = Field(default="SIP UP account (configured)")
    sip_username: str = ""
    sip_domain: str = "sip.sipup.org"
    sip_port: int = Field(default=5060, ge=1, le=65535)
    outbound_caller_id: str = ""
    password_present: bool = False
    source: str = Field(default="env", description="ui when edited from dashboard, else env")
    last_updated: Optional[str] = None


class SipUpAccountSettingsUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=64)
    sip_username: Optional[str] = Field(default=None, max_length=64)
    sip_password: Optional[str] = Field(
        default=None,
        description="Leave blank to keep the existing password.",
        max_length=255,
    )
    sip_domain: Optional[str] = Field(default=None, max_length=255)
    sip_port: Optional[int] = Field(default=None, ge=1, le=65535)
    outbound_caller_id: Optional[str] = Field(default=None, max_length=32)

    @field_validator("outbound_caller_id", mode="before")
    @classmethod
    def normalize_outbound_caller_id(cls, v):
        if v is None:
            return None
        raw = str(v).strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 3:
            raise ValueError("outbound_caller_id must be at least 3 digits")
        return digits
