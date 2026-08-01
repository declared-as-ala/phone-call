import asyncio
from typing import Optional

from ...compliance import operator_consent_ivr_playing_message
from ...event_types import LEGACY_CHANNEL_CONNECTED_EVENT, CallEventType
from .base import CallEventEmitter, TelephonyProvider


class MockTelephonyProvider(TelephonyProvider):
    """Local simulator: emits lifecycle events without external telephony."""

    async def start_outbound(
        self,
        session_id: str,
        phone_number: str,
        emitter: CallEventEmitter,
        *,
        organization: str = "",
        name: str = "",
        outbound_caller_id: Optional[str] = None,
    ) -> None:
        await emitter.emit(
            session_id,
            CallEventType.DIAL_STARTED.value,
            f"Outbound dial started to {phone_number}",
        )
        await asyncio.sleep(0.4)
        await emitter.emit(session_id, CallEventType.CALL_RINGING.value, "Remote party ringing")
        await asyncio.sleep(0.5)
        await emitter.emit(session_id, LEGACY_CHANNEL_CONNECTED_EVENT, "Call answered")
        await asyncio.sleep(0.3)
        await emitter.emit(session_id, CallEventType.IVR_PROMPT.value, operator_consent_ivr_playing_message())
