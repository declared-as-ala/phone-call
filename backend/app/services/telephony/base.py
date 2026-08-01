from abc import ABC, abstractmethod
from typing import Optional, Protocol


class CallEventEmitter(Protocol):
    async def emit(self, session_id: str, event_type: str, message: str) -> None: ...


class TelephonyProvider(ABC):
    """Pluggable outbound IVR provider. Real PSTN/SIP implementations would subclass this."""

    @abstractmethod
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
        """Initiate an outbound verification call to the given number.

        ``organization`` is the callee-facing institution name for consent prompts (e.g. university).
        ``name`` is the callee-facing name for consent prompts (e.g. session subject name).
        """
