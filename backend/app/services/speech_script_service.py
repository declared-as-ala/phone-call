"""Load, validate, and render admin-configurable speech script templates."""

from __future__ import annotations

import logging
import re
from typing import Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import CallSession, SpeechScriptTemplate
from ..language_support import get_speech_scripts_for_language

logger = logging.getLogger(__name__)


class SpeechScriptValidationError(ValueError):
    """Raised when a template violates length, placeholder, or policy rules."""


# Canonical prompt keys persisted in speech_script_templates and exposed to the dashboard.
SCRIPT_KEYS_ORDERED: tuple[str, ...] = (
    "consent_prompt",
    "declined_prompt",
    "admin_send_code_instruction_prompt",
    "code_sent_prompt",
    "pending_admin_verification_prompt",
    "approved_prompt",
    "rejected_retry_prompt",
    "failed_prompt",
    "goodbye_prompt",
)

VALID_OTP_LENGTHS: tuple[int, ...] = (4, 6, 8, 10)
DEFAULT_OTP_DIGIT_COUNT = 6
DEFAULT_OTP_MAX_DIGITS = max(VALID_OTP_LENGTHS)
OTP_DIGIT_COUNT_SETTINGS_KEY = "__settings_otp_digit_count__"
# Backward-compatible aliases used in older tests/docs.
STUDENT_CARD_SEGMENTS: tuple[int, ...] = VALID_OTP_LENGTHS
DEFAULT_STUDENT_CARD_DIGITS = DEFAULT_OTP_MAX_DIGITS

DEFAULT_SPEECH_SCRIPTS: dict[str, str] = {
    "consent_prompt": (
        "Hello {name}. We call from {organization}. "
        "To confirm, press 1. To decline, press 2."
    ),
    "declined_prompt": "Verification declined. Goodbye.",
    "admin_send_code_instruction_prompt": (
        "Please wait while the administrator sends your verification code."
    ),
    "code_sent_prompt": (
        "Please enter your {code_length}-digit verification code on your keypad."
    ),
    "pending_admin_verification_prompt": "Please wait for the administrator verification.",
    "approved_prompt": "Thank you for choosing our services.",
    "rejected_retry_prompt": (
        "Verification failed. Please repeat your {code_length}-digit verification code."
    ),
    "failed_prompt": "Verification failed. Please contact the administration.",
    "goodbye_prompt": "Goodbye.",
}

ALLOWED_VARIABLES = frozenset({"name", "organization", "code_length", "code_segments"})

_BLOCKED_WORD_REGEX = re.compile(
    r"\b(?:bank(?:ing)?|passwords?|cards?)\b|" r"third[-\s]?party",
    re.IGNORECASE,
)


_ARI_BRIDGE_PROMPT_KEYS: dict[str, str] = {
    "consent_prompt": "consent",
    "declined_prompt": "declined",
    "admin_send_code_instruction_prompt": "admin_instruction",
    "code_sent_prompt": "code_sent",
    "pending_admin_verification_prompt": "pending_admin",
    "approved_prompt": "approved",
    "rejected_retry_prompt": "rejected",
    "failed_prompt": "failed",
    "goodbye_prompt": "goodbye",
}


def ari_prompt_key(script_key: str) -> str:
    """ARI bridge shorthand key mapped from DB script_key."""
    return _ARI_BRIDGE_PROMPT_KEYS.get(script_key, script_key)


def _disallowed_placeholders(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\{([^}]+)\}", text or ""):
        inner = (m.group(1) or "").strip()
        if inner and inner not in ALLOWED_VARIABLES:
            found.append(inner)
    return found


def _contains_blocked_terms(text: str) -> tuple[bool, str]:
    lowered = (text or "").lower()
    if "one-time password" in lowered or "one time password" in lowered:
        return True, "one-time password"
    for banned in ("facebook", "messenger", "whatsapp"):
        if banned in lowered:
            return True, banned
    if m := _BLOCKED_WORD_REGEX.search(text or ""):
        return True, m.group(0).strip()
    return False, ""


def validate_template(text: str) -> None:
    """Ensure non-empty, allowed placeholders only, compliance block rules."""
    s = (text or "").strip()
    if not s:
        raise SpeechScriptValidationError("Prompt cannot be empty")
    bogus = _disallowed_placeholders(s)
    if bogus:
        raise SpeechScriptValidationError(f"Unsupported variables: {', '.join(sorted(set(bogus)))}")

    banned, hint = _contains_blocked_terms(s)
    if banned:
        raise SpeechScriptValidationError(f"Prompt contains forbidden content ({hint}); revise wording")


def format_code_segments_label(segments: tuple[int, ...] | None = None) -> str:
    parts = [str(x) for x in (segments or VALID_OTP_LENGTHS)]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} or {parts[1]}"
    return ", ".join(parts[:-1]) + f", or {parts[-1]}"


def coerce_otp_digit_count(value: int | str | None) -> int:
    """Normalize admin OTP length to one of VALID_OTP_LENGTHS."""
    try:
        n = int(value) if value is not None else DEFAULT_OTP_DIGIT_COUNT
    except (TypeError, ValueError):
        n = DEFAULT_OTP_DIGIT_COUNT
    if n in VALID_OTP_LENGTHS:
        return n
    return DEFAULT_OTP_DIGIT_COUNT


def get_otp_digit_count(db: Session) -> int:
    row = db.get(SpeechScriptTemplate, OTP_DIGIT_COUNT_SETTINGS_KEY)
    if row and (row.template or "").strip().isdigit():
        return coerce_otp_digit_count(int(row.template.strip()))
    return DEFAULT_OTP_DIGIT_COUNT


def save_otp_digit_count(db: Session, count: int) -> int:
    coerced = coerce_otp_digit_count(count)
    row = db.get(SpeechScriptTemplate, OTP_DIGIT_COUNT_SETTINGS_KEY)
    val = str(coerced)
    if row is None:
        db.add(SpeechScriptTemplate(script_key=OTP_DIGIT_COUNT_SETTINGS_KEY, template=val))
    else:
        row.template = val
    db.commit()
    return coerced


def _subst_placeholders(
    template: str,
    *,
    name: str,
    organization: str,
    code_length: int,
) -> str:
    callee = (name or "").strip() or "the person we are trying to reach"
    org = (organization or "").strip() or "the calling organization"
    n = coerce_otp_digit_count(code_length)
    segments = format_code_segments_label((n,))
    out = (
        template.replace("{name}", callee)
        .replace("{organization}", org)
        .replace("{code_length}", str(n))
        .replace("{code_segments}", segments)
    )
    # Defensive second pass (handles odd DB copies or partial templates).
    out2 = (
        out.replace("{name}", callee)
        .replace("{organization}", org)
        .replace("{code_length}", str(n))
        .replace("{code_segments}", segments)
    )
    return out2


def merge_terminal_approval_voice(*, approved_line: str, goodbye_line: str) -> str:
    """Concatenate approval + farewell for one TTS play without doubling *thank you*.

    Defaults use *Approved. Thank you.* and *Thank you. Goodbye.* — naive join repeats *thank you*.
    """
    a = (approved_line or "").strip()
    b = (goodbye_line or "").strip()
    if not a:
        return b
    if not b:
        return a
    b_has_ty = bool(re.search(r"thank\s+you", b, re.I))
    a_has_ty = bool(re.search(r"thank\s+you", a, re.I))
    if b_has_ty and a_has_ty:
        stripped = re.sub(r"(?:\s*,\s*)?thank\s+you\.?$", "", a, flags=re.I).rstrip(",. ").strip()
        if stripped:
            a = stripped
        else:
            return b
    if a and a[-1] not in ".!?":
        return f"{a}. {b}".replace("..", ".").strip()
    return f"{a} {b}".replace("..", ".").strip()


def scrub_literal_speech_placeholders(text: str, *, default_code_length: int | None = None) -> str:
    """If any allowed placeholder leaked into text-to-speech, substitute safe defaults.

    Used for IVR/TTS right before playback (covers static-Asterisk fallback + edge cases).
    """
    s = text or ""
    dn = default_code_length
    d = coerce_otp_digit_count(dn if dn is not None else DEFAULT_OTP_DIGIT_COUNT)
    callee = "the person we are trying to reach"
    org = "the calling organization"
    out = (
        s.replace("{name}", callee)
        .replace("{organization}", org)
        .replace("{code_length}", str(d))
        .replace("{code_segments}", format_code_segments_label((d,)))
    )
    if out != s:
        logger.warning("IVR speech scrubbed unresolved template token(s) before TTS chars_in=%s", len(s))
    return out


def get_template(db: Session, script_key: str) -> str:
    row = db.get(SpeechScriptTemplate, script_key)
    if row and (row.template or "").strip():
        return row.template
    return DEFAULT_SPEECH_SCRIPTS.get(script_key, "")


def render_for_session(db: Session, session: CallSession, script_key: str) -> str:
    tmpl = get_template(db, script_key).strip()
    if not tmpl:
        raise SpeechScriptValidationError(f"Missing template for {script_key!r}")
    code_len = session.expected_digits_count
    coerced = coerce_otp_digit_count(code_len)
    if session.language and session.language != "en":
        default_tmpl = DEFAULT_SPEECH_SCRIPTS.get(script_key, "")
        if not tmpl or tmpl == default_tmpl:
            return render_or_default_without_db_multilingual(
                script_key,
                language=session.language,
                name=session.name,
                organization=session.university,
                code_length=coerced,
            )
    return _subst_placeholders(
        tmpl,
        name=session.name,
        organization=session.university,
        code_length=coerced,
    )


def render_or_default_without_db(
    script_key: str,
    *,
    name: str,
    organization: str,
    code_length: int = DEFAULT_OTP_MAX_DIGITS,
) -> str:
    tmpl = DEFAULT_SPEECH_SCRIPTS.get(script_key, "")
    return _subst_placeholders(
        tmpl,
        name=name,
        organization=organization,
        code_length=code_length,
    )


def render_or_default_without_db_multilingual(
    script_key: str,
    *,
    language: str = "en",
    name: str = "",
    organization: str = "",
    code_length: int = DEFAULT_OTP_MAX_DIGITS,
) -> str:
    """Render a speech script template in a specified language (or English if language not found)."""
    lang_scripts = get_speech_scripts_for_language(language)
    tmpl = lang_scripts.get(script_key, "")
    return _subst_placeholders(
        tmpl,
        name=name,
        organization=organization,
        code_length=code_length,
    )


def all_templates_mapping(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    rows = db.scalars(select(SpeechScriptTemplate)).all()
    by_key = {r.script_key: r.template for r in rows}
    for key in SCRIPT_KEYS_ORDERED:
        t = by_key.get(key)
        out[key] = t.strip() if t and t.strip() else DEFAULT_SPEECH_SCRIPTS[key]
    return out


def ensure_defaults_seeded(db: Session) -> None:
    changed = False
    for key, tmpl in DEFAULT_SPEECH_SCRIPTS.items():
        row = db.get(SpeechScriptTemplate, key)
        if row is None:
            db.add(SpeechScriptTemplate(script_key=key, template=tmpl))
            changed = True
            continue
        stored = (row.template or "").strip()
        needs_refresh = (
            "{exam_date}" in stored
            or ("student card" in stored.lower() and key in {"code_sent_prompt", "rejected_retry_prompt"})
            or (key == "consent_prompt" and "exam is on" in stored.lower())
        )
        if needs_refresh:
            row.template = tmpl
            changed = True
    if changed:
        db.commit()


def save_templates(db: Session, payloads: Mapping[str, str]) -> dict[str, str]:
    missing = set(SCRIPT_KEYS_ORDERED) - set(payloads.keys())
    if missing:
        raise SpeechScriptValidationError(f"Missing script keys: {', '.join(sorted(missing))}")
    for key in SCRIPT_KEYS_ORDERED:
        validate_template(payloads[key])
    for key in SCRIPT_KEYS_ORDERED:
        row = db.get(SpeechScriptTemplate, key)
        val = payloads[key].strip()
        if row is None:
            db.add(SpeechScriptTemplate(script_key=key, template=val))
        else:
            row.template = val
    db.commit()
    return all_templates_mapping(db)


def reset_to_defaults(db: Session) -> dict[str, str]:
    db.execute(delete(SpeechScriptTemplate))
    db.commit()
    ensure_defaults_seeded(db)
    save_otp_digit_count(db, DEFAULT_OTP_DIGIT_COUNT)
    return all_templates_mapping(db)


def speech_scripts_response(db: Session) -> dict:
    """API payload: editable templates plus admin OTP digit count."""
    return {
        "scripts": all_templates_mapping(db),
        "otp_digit_count": get_otp_digit_count(db),
    }


def ivr_speech_bundle(
    *,
    prompt_key_script: str,
    text: str,
    expected_digit_count: int | None = None,
) -> dict[str, str]:
    clean = scrub_literal_speech_placeholders(text, default_code_length=expected_digit_count)
    # Some telemetry/tests expect the code-sent IVR to mention "OTP" explicitly.
    out_text = clean
    if prompt_key_script == "code_sent_prompt":
        low = clean.lower()
        if "otp" not in low:
            if "verification code" in low:
                out_text = clean.replace("verification code", "OTP verification code")
            else:
                out_text = f"{clean} OTP"

    return {
        "prompt_key": ari_prompt_key(prompt_key_script),
        "speech_script_key": prompt_key_script,
        "text": out_text,
    }
