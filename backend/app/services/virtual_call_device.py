"""Local console transcript for testing IVR speech before real telephony audio."""

from __future__ import annotations

import re
from typing import Callable, Optional

from .. import config
from ..event_types import CallEventType, LEGACY_CHANNEL_CONNECTED_EVENT
from ..models import CallEvent, CallSession
from .prompt_renderer import PromptRenderer

Printer = Callable[[str], None]

_ENABLED_EVENTS = {
    CallEventType.CALL_ANSWERED.value,
    CallEventType.IVR_PROMPT.value,
    CallEventType.RECIPIENT_ACCEPTED.value,
    CallEventType.DIGITS_RECEIVED.value,
    CallEventType.PENDING_ADMIN_VERIFICATION.value,
    CallEventType.ADMIN_VERIFICATION_APPROVED.value,
    CallEventType.ADMIN_VERIFICATION_REJECTED.value,
    CallEventType.VERIFICATION_SUCCESS.value,
    CallEventType.VERIFICATION_FAILED.value,
    CallEventType.MAX_ATTEMPTS_EXCEEDED.value,
    CallEventType.CALL_HANGUP.value,
    CallEventType.CALL_COMPLETED.value,
    CallEventType.RECIPIENT_DECLINED.value,
    CallEventType.ADMIN_CODE_SENT_CONFIRMED.value,
    LEGACY_CHANNEL_CONNECTED_EVENT,
}


def _phone_display(phone: str) -> str:
    return phone or ""


def _extract_digits_from_message(message: str) -> Optional[str]:
    text = message or ""
    trailing = re.search(r":\s*(\d+)\s*$", text)
    if trailing:
        return trailing.group(1)
    runs = re.findall(r"\d+", text)
    return runs[-1] if runs else None


def _format_block(lines: list[str]) -> str:
    return "\n".join(["[IVR TRANSCRIPT]", *lines])


class VirtualCallDevice:
    """Prints what a callee would hear; no state changes, network calls, or TTS APIs."""

    def __init__(self, *, printer: Printer = print) -> None:
        self._printer = printer

    def handle_event(self, session: Optional[CallSession], event: CallEvent) -> None:
        if not config.VIRTUAL_CALL_DEVICE_ENABLED:
            return
        if event.event_type not in _ENABLED_EVENTS:
            return

        lines = self._lines_for_event(session, event)
        if lines:
            self._printer(_format_block(lines))

    def _lines_for_event(self, session: Optional[CallSession], event: CallEvent) -> list[str]:
        base = []
        if session is not None:
            base.extend(
                [
                    f"Call ID: {session.id}",
                    f"Phone: {_phone_display(session.phone_number)}",
                    f"Step: {session.simulator_step}",
                ]
            )

        event_type = event.event_type
        if event_type in {CallEventType.CALL_ANSWERED.value, CallEventType.IVR_PROMPT.value}:
            if session is None:
                return base
            prompt = PromptRenderer.consent_prompt(session.name, session.university)
            return [
                *base,
                f"SAY: {prompt['text']}",
                "WAITING FOR DTMF: press 1 to confirm, 2 to decline",
            ]

        if event_type == CallEventType.RECIPIENT_ACCEPTED.value:
            cl = int(getattr(session, "expected_digits_count", None) or 12)
            prompt = PromptRenderer.verification_code_prompt(code_length=cl)
            return [*base, "DTMF RECEIVED: 1", f"SAY: {prompt['text']}"]

        if event_type == CallEventType.ADMIN_CODE_SENT_CONFIRMED.value:
            cl = int(getattr(session, "expected_digits_count", None) or 6)
            prompt = PromptRenderer.verification_code_prompt(code_length=cl)
            return [*base, "ADMIN CONFIRMED CODE SENT EXTERNALLY", f"SAY: {prompt['text']}"]

        if event_type == CallEventType.RECIPIENT_DECLINED.value:
            prompt = PromptRenderer.declined_prompt()
            return [*base, "DTMF RECEIVED: 2", f"SAY: {prompt['text']}"]

        if event_type == CallEventType.DIGITS_RECEIVED.value:
            digits = _extract_digits_from_message(event.message)
            return [*base, f"DTMF RECEIVED: {digits or '—'}"]

        if event_type == CallEventType.PENDING_ADMIN_VERIFICATION.value:
            prompt = PromptRenderer.pending_admin_verification_prompt()
            return [*base, f"SAY: {prompt['text']}"]

        if event_type == CallEventType.ADMIN_VERIFICATION_APPROVED.value:
            prompt = PromptRenderer.success_prompt()
            return [*base, "ADMIN APPROVED", f"SAY: {prompt['text']}"]

        if event_type == CallEventType.VERIFICATION_SUCCESS.value:
            return [*base, "CALL RESULT: verification approved"]

        if event_type == CallEventType.ADMIN_VERIFICATION_REJECTED.value:
            if session is not None and session.status == "failed":
                prompt = PromptRenderer.failed_prompt()
            else:
                prompt = PromptRenderer.admin_rejected_prompt()
            return [*base, "ADMIN REJECTED", f"SAY: {prompt['text']}"]

        if event_type in {CallEventType.VERIFICATION_FAILED.value, CallEventType.MAX_ATTEMPTS_EXCEEDED.value}:
            prompt = PromptRenderer.failed_prompt()
            return [*base, f"SAY: {prompt['text']}"]

        if event_type in {CallEventType.CALL_HANGUP.value, CallEventType.CALL_COMPLETED.value}:
            prompt = PromptRenderer.goodbye_prompt()
            return [*base, f"SAY: {prompt['text']}"]

        if event_type == LEGACY_CHANNEL_CONNECTED_EVENT:
            return [*base, "CALL CONNECTED"]

        return []


virtual_call_device = VirtualCallDevice()
