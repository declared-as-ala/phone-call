import asyncio
import contextlib
import logging
import os
from typing import Any, Optional

from ..database import SessionLocal
from ..event_types import LEGACY_CHANNEL_CONNECTED_EVENT, CallEventType
from ..models import CallSession, EventActor, SessionStatus, SimulatorStep
from ..telephony_provider_config import telephony_provider_mode
from .call_service import call_service
from .telephony.sip_up_ari_provider import SipUpAriProvider
from .telephony.base import TelephonyProvider
from .telephony.mock_provider import MockTelephonyProvider
from .telephony.sip_up_provider import (
    SipUpTelephonyConfig,
    SipUpTelephonyProvider,
    build_sip_up_ari_config,
)

logger = logging.getLogger(__name__)

_outbound_tasks: dict[str, asyncio.Task[Any]] = {}

_EVENT_STATUS: dict[str, SessionStatus] = {
    CallEventType.DIAL_STARTED.value: SessionStatus.DIALING,
    CallEventType.CALL_RINGING.value: SessionStatus.RINGING,
    LEGACY_CHANNEL_CONNECTED_EVENT: SessionStatus.CONNECTED,
    CallEventType.IVR_PROMPT.value: SessionStatus.COLLECTING,
}


class _SessionEmitter:
    async def emit(self, session_id: str, event_type: str, message: str) -> None:
        db = SessionLocal()
        try:
            new_status = _EVENT_STATUS.get(event_type)
            await call_service.add_event(
                db,
                session_id,
                event_type,
                message,
                new_status=new_status,
                actor=EventActor.TELEPHONY_PROVIDER,
            )
        finally:
            db.close()


def _normalize_trunk(trunk_preference: str) -> str:
    """Legacy ``default`` trunk values map to SIP UP."""
    t = (trunk_preference or "").strip().lower()
    return "sip_up" if t in ("", "default", "none") else t


def _provider_for_current_mode() -> TelephonyProvider:
    mode = telephony_provider_mode()
    if mode == "sip_up":
        sip = SipUpTelephonyConfig.from_env()
        cfg = build_sip_up_ari_config(sip)
        logger.info(
            "Outbound provider resolved class=SipUpAriProvider mode=sip_up "
            "host=%s port=%s ari_app=%s context=%s endpoint=%s",
            cfg.host or "(unset)",
            cfg.port,
            cfg.ari_app,
            cfg.context or "(unset)",
            cfg.endpoint or "(unset)",
        )
        return SipUpAriProvider(cfg)
    logger.info(
        "Outbound provider resolved class=MockTelephonyProvider mode=%s", mode
    )
    return MockTelephonyProvider()


def resolve_outbound_provider(
    *,
    trunk_preference: str,
    force_mock: bool,
    phone_number: str = "",
    outbound_caller_id: Optional[str] = None,
) -> TelephonyProvider:
    """All real outbound calls use SIP UP (``SipUpTelephonyProvider``)."""
    if force_mock:
        return MockTelephonyProvider()
    trunk = _normalize_trunk(trunk_preference)
    if trunk != "sip_up":
        logger.warning("Unknown outbound_trunk=%r; using sip_up", trunk_preference)
    cfg = SipUpTelephonyConfig.for_call(
        phone_number,
        outbound_caller_id=outbound_caller_id,
    )
    logger.info(
        "Outbound provider resolved class=SipUpTelephonyProvider trunk=sip_up "
        "dial_format=%s caller_id_tail=%s",
        cfg.dial_format,
        (cfg.outbound_caller_id or "") or "(unset)",
    )
    return SipUpTelephonyProvider(cfg)


async def run_outbound(
    session_id: str,
    *,
    force_mock: bool = False,
    trunk_preference: str = "sip_up",
) -> None:
    db = SessionLocal()
    try:
        sess = db.get(CallSession, session_id)
        if not sess:
            return
        provider = resolve_outbound_provider(
            trunk_preference=trunk_preference,
            force_mock=force_mock,
            phone_number=sess.phone_number,
            outbound_caller_id=sess.outbound_caller_id,
        )
        emitter = _SessionEmitter()
        try:
            await provider.start_outbound(
                session_id,
                sess.phone_number,
                emitter,
                organization=sess.university,
                name=sess.name,
                outbound_caller_id=sess.outbound_caller_id,
            )
        except Exception as e:
            await call_service.add_event(
                db,
                session_id,
                CallEventType.CALL_FAILED.value,
                f"Outbound provider failed to start call: {e}",
                new_status=SessionStatus.FAILED,
                new_step=SimulatorStep.FINISHED.value,
                ivr_terminal="failed",
                actor=EventActor.TELEPHONY_PROVIDER,
            )
    finally:
        db.close()
        _outbound_tasks.pop(session_id, None)


async def run_mock_outbound(session_id: str) -> None:
    await run_outbound(session_id, force_mock=True, trunk_preference="sip_up")


def schedule_outbound_call(
    session_id: str, *, trunk_preference: str = "sip_up"
) -> None:
    force_mock = telephony_provider_mode() == "mock"
    task = asyncio.create_task(
        run_outbound(
            session_id,
            force_mock=force_mock,
            trunk_preference=trunk_preference,
        )
    )
    _outbound_tasks[session_id] = task


def schedule_mock_outbound(session_id: str) -> None:
    task = asyncio.create_task(run_mock_outbound(session_id))
    _outbound_tasks[session_id] = task


def pop_mock_task(session_id: str) -> Optional[asyncio.Task[Any]]:
    return _outbound_tasks.pop(session_id, None)


def get_mock_task(session_id: str) -> Optional[asyncio.Task[Any]]:
    return _outbound_tasks.get(session_id)


async def cancel_mock_task(session_id: str) -> None:
    t = pop_mock_task(session_id)
    if t and not t.done():
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
