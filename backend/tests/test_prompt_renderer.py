"""Prompt renderer: compliance-backed IVR copy."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.prompt_renderer import PromptRenderer
from app.services.telephony.mock_provider import MockTelephonyProvider


def test_consent_prompt_includes_organization_and_variables():
    p = PromptRenderer.consent_prompt("Jane Doe", "Example University")
    assert p["prompt_key"] == "consent"
    assert p["variables"]["name"] == "Jane Doe"
    assert p["variables"]["organization"] == "Example University"
    assert "Example University" in p["text"]
    assert "Jane Doe" in p["text"]


def test_consent_prompt_has_no_exam_date_copy():
    p = PromptRenderer.consent_prompt("A", "Org")
    assert "Hello A" in p["text"]
    assert "Org" in p["text"]
    assert "exam" not in p["text"].lower()
    assert "press 1" in p["text"].lower()
    assert "press 2" in p["text"].lower()


def test_consent_prompt_never_solicits_third_party_otps_or_cards():
    p = PromptRenderer.consent_prompt("User", "Uni")
    lowered = p["text"].lower()
    assert "enter your otp" not in lowered
    assert "provide your card" not in lowered
    assert "give us your bank" not in lowered


def test_consent_empty_name_and_org_use_fallbacks():
    p = PromptRenderer.consent_prompt("", "")
    assert "the person we are trying to reach" in p["text"]
    assert "the calling organization" in p["text"]


def test_verification_code_prompt_otp():
    p = PromptRenderer.verification_code_prompt()
    assert p["prompt_key"] == "verification_code"
    assert "verification" in p["text"].lower()
    assert "10-digit" in p["text"]


def test_verification_code_prompt_respects_code_length():
    p = PromptRenderer.verification_code_prompt(code_length=8)
    assert "8" in p["text"]


def test_retry_prompt_grammar():
    one = PromptRenderer.retry_prompt(1)
    assert "verification failed" in one["text"].lower()
    many = PromptRenderer.retry_prompt(3)
    assert "verification" in many["text"].lower()


@pytest.mark.parametrize(
    "method, key",
    [
        ("declined_prompt", "declined"),
        ("success_prompt", "success"),
        ("failed_prompt", "failed"),
        ("goodbye_prompt", "goodbye"),
        ("pending_admin_verification_prompt", "pending_admin_verification"),
        ("admin_rejected_prompt", "admin_rejected"),
    ],
)
def test_terminal_prompts_have_keys(method, key):
    p = getattr(PromptRenderer, method)()
    assert p["prompt_key"] == key
    assert len(p["text"]) > 0
    assert p["variables"] == {}


def test_mock_provider_ivr_prompt_uses_renderer_text():
    events: list[tuple[str, str]] = []

    class _Emitter:
        async def emit(self, session_id: str, event_type: str, message: str) -> None:
            events.append((event_type, message))

    async def _run():
        prov = MockTelephonyProvider()
        await prov.start_outbound(
            "sess-1",
            "+15550001111",
            _Emitter(),
            organization="State College",
            name="Alex Smith",
        )

    with patch("app.services.telephony.mock_provider.asyncio.sleep", new_callable=AsyncMock):
        asyncio.run(_run())

    from app.compliance import operator_consent_ivr_playing_message

    ivr = next(e for e in events if e[0] == "IVR_PROMPT")
    assert ivr[1] == operator_consent_ivr_playing_message()


def test_required_speech_prompts_match_manual_review_flow():
    assert "verification" in PromptRenderer.verification_code_prompt()["text"].lower()
    assert PromptRenderer.pending_admin_verification_prompt()["text"] == (
        "Please wait for the administrator verification."
    )
    assert PromptRenderer.success_prompt()["text"] == "Thank you for choosing our services."
    assert "verification failed" in PromptRenderer.admin_rejected_prompt()["text"].lower()
    assert PromptRenderer.failed_prompt()["text"] == (
        "Verification failed. Please contact the administration."
    )
    assert PromptRenderer.declined_prompt()["text"] == "Verification declined. Goodbye."


def test_no_prompt_solicits_sensitive_credentials():
    prompts = [
        PromptRenderer.consent_prompt("User", "Uni")["text"],
        PromptRenderer.verification_code_prompt()["text"],
        PromptRenderer.pending_admin_verification_prompt()["text"],
        PromptRenderer.success_prompt()["text"],
        PromptRenderer.admin_rejected_prompt()["text"],
        PromptRenderer.failed_prompt()["text"],
        PromptRenderer.declined_prompt()["text"],
        PromptRenderer.goodbye_prompt()["text"],
    ]
    lowered = "\n".join(prompts).lower()
    forbidden_requests = [
        "bank card",
        "password",
        "third-party otp",
        "enter your bank",
        "provide your bank",
        "enter your card",
        "provide your card",
        "enter your password",
        "provide your password",
        "enter your third-party otp",
        "provide your third-party otp",
    ]
    for phrase in forbidden_requests:
        assert phrase not in lowered
