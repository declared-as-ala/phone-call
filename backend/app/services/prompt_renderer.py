"""
Backward-compatible prompt assembly; defaults match ``speech_script_service`` DB seed.
Supports multilingual rendering via language parameter.
"""

from __future__ import annotations

from typing import Any, TypedDict

from .speech_script_service import render_or_default_without_db, render_or_default_without_db_multilingual


class PromptPayload(TypedDict):
    prompt_key: str
    text: str
    variables: dict[str, Any]


class PromptRenderer:
    """Renders IVR copy aligned with admin-configurable templates (defaults shown)."""

    @staticmethod
    def consent_prompt(name: str, organization: str) -> PromptPayload:
        callee = (name or "").strip() or "the person we are trying to reach"
        org = (organization or "").strip() or "the calling organization"
        text = render_or_default_without_db(
            "consent_prompt",
            name=callee,
            organization=org,
        )
        return {
            "prompt_key": "consent",
            "text": text,
            "variables": {"name": callee, "organization": org},
        }

    @staticmethod
    def verification_code_prompt(*, code_length: int = 10) -> PromptPayload:
        text = render_or_default_without_db(
            "code_sent_prompt",
            name="",
            organization="",
            code_length=code_length,
        )
        return {"prompt_key": "verification_code", "text": text, "variables": {}}

    @staticmethod
    def admin_wait_code_send_prompt() -> PromptPayload:
        text = render_or_default_without_db(
            "admin_send_code_instruction_prompt",
            name="",
            organization="",
        )
        return {"prompt_key": "admin_instruction", "text": text, "variables": {}}

    @staticmethod
    def retry_prompt(attempts_left: int) -> PromptPayload:
        n = max(0, int(attempts_left))
        text = render_or_default_without_db("rejected_retry_prompt", name="", organization="")
        return {"prompt_key": "retry", "text": text, "variables": {"attempts_left": n}}

    @staticmethod
    def declined_prompt() -> PromptPayload:
        text = render_or_default_without_db("declined_prompt", name="", organization="")
        return {"prompt_key": "declined", "text": text, "variables": {}}

    @staticmethod
    def success_prompt() -> PromptPayload:
        text = render_or_default_without_db("approved_prompt", name="", organization="")
        return {"prompt_key": "success", "text": text, "variables": {}}

    @staticmethod
    def failed_prompt() -> PromptPayload:
        text = render_or_default_without_db("failed_prompt", name="", organization="")
        return {"prompt_key": "failed", "text": text, "variables": {}}

    @staticmethod
    def goodbye_prompt() -> PromptPayload:
        text = render_or_default_without_db("goodbye_prompt", name="", organization="")
        return {"prompt_key": "goodbye", "text": text, "variables": {}}

    @staticmethod
    def pending_admin_verification_prompt() -> PromptPayload:
        text = render_or_default_without_db(
            "pending_admin_verification_prompt", name="", organization=""
        )
        return {
            "prompt_key": "pending_admin_verification",
            "text": text,
            "variables": {},
        }

    @staticmethod
    def admin_rejected_prompt() -> PromptPayload:
        text = render_or_default_without_db("rejected_retry_prompt", name="", organization="")
        return {"prompt_key": "admin_rejected", "text": text, "variables": {}}

    # Multilingual versions
    @staticmethod
    def consent_prompt_multilingual(
        name: str, organization: str, language: str = "en"
    ) -> PromptPayload:
        callee = (name or "").strip() or "the person we are trying to reach"
        org = (organization or "").strip() or "the calling organization"
        text = render_or_default_without_db_multilingual(
            "consent_prompt",
            language=language,
            name=callee,
            organization=org,
        )
        return {
            "prompt_key": "consent",
            "text": text,
            "variables": {"name": callee, "organization": org},
        }

    @staticmethod
    def verification_code_prompt_multilingual(
        *, code_length: int = 10, language: str = "en"
    ) -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "code_sent_prompt",
            language=language,
            name="",
            organization="",
            code_length=code_length,
        )
        return {"prompt_key": "verification_code", "text": text, "variables": {}}

    @staticmethod
    def admin_wait_code_send_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "admin_send_code_instruction_prompt",
            language=language,
            name="",
            organization="",
        )
        return {"prompt_key": "admin_instruction", "text": text, "variables": {}}

    @staticmethod
    def retry_prompt_multilingual(
        attempts_left: int, language: str = "en"
    ) -> PromptPayload:
        n = max(0, int(attempts_left))
        text = render_or_default_without_db_multilingual(
            "rejected_retry_prompt",
            language=language,
            name="",
            organization="",
        )
        return {"prompt_key": "retry", "text": text, "variables": {"attempts_left": n}}

    @staticmethod
    def declined_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "declined_prompt", language=language, name="", organization=""
        )
        return {"prompt_key": "declined", "text": text, "variables": {}}

    @staticmethod
    def success_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "approved_prompt", language=language, name="", organization=""
        )
        return {"prompt_key": "success", "text": text, "variables": {}}

    @staticmethod
    def failed_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "failed_prompt", language=language, name="", organization=""
        )
        return {"prompt_key": "failed", "text": text, "variables": {}}

    @staticmethod
    def goodbye_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "goodbye_prompt", language=language, name="", organization=""
        )
        return {"prompt_key": "goodbye", "text": text, "variables": {}}

    @staticmethod
    def pending_admin_verification_prompt_multilingual(
        language: str = "en",
    ) -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "pending_admin_verification_prompt",
            language=language,
            name="",
            organization="",
        )
        return {
            "prompt_key": "pending_admin_verification",
            "text": text,
            "variables": {},
        }

    @staticmethod
    def admin_rejected_prompt_multilingual(language: str = "en") -> PromptPayload:
        text = render_or_default_without_db_multilingual(
            "rejected_retry_prompt", language=language, name="", organization=""
        )
        return {"prompt_key": "admin_rejected", "text": text, "variables": {}}
