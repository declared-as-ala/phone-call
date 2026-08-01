import base64
import hashlib
import re

import bcrypt
from cryptography.fernet import Fernet

_ENCRYPTED_SECRET_PREFIX = "fernet:v1:"


def hash_verification_code(plain_code: str) -> str:
    return bcrypt.hashpw(plain_code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_verification_code(plain_code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(plain_code.encode("utf-8"), code_hash.encode("utf-8"))


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if not any(ch.islower() for ch in password):
        raise ValueError("Password must include a lowercase letter")
    if not any(ch.isupper() for ch in password):
        raise ValueError("Password must include an uppercase letter")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Password must include a number")
    if not any(not ch.isalnum() for ch in password):
        raise ValueError("Password must include a symbol")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _fernet_for_session(secret: str, session_id: str) -> Fernet:
    """Deterministic Fernet key per call session (not stored)."""
    raw = hashlib.sha256(f"{secret}:{session_id}".encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_dtmf_buffer(plain: str, *, secret: str, session_id: str) -> str:
    """Persisted ciphertext for partial DTMF; empty input stores as ''."""
    if not plain:
        return ""
    f = _fernet_for_session(secret, session_id)
    token = f.encrypt(plain.encode("utf-8"))
    return base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_dtmf_buffer(stored: str, *, secret: str, session_id: str) -> str:
    if not stored:
        return ""
    try:
        f = _fernet_for_session(secret, session_id)
        raw = base64.urlsafe_b64decode(stored.encode("ascii"))
        return f.decrypt(raw).decode("utf-8")
    except Exception:
        return ""


def encrypt_secret(plain: str, *, secret: str, purpose: str) -> str:
    """Encrypt a configuration secret with a purpose-derived Fernet key."""
    if not plain:
        return ""
    raw_key = hashlib.sha256(f"ivr-secret:v1:{purpose}:{secret}".encode("utf-8")).digest()
    token = Fernet(base64.urlsafe_b64encode(raw_key)).encrypt(plain.encode("utf-8"))
    return f"{_ENCRYPTED_SECRET_PREFIX}{token.decode('ascii')}"


def decrypt_secret(stored: str, *, secret: str, purpose: str) -> str:
    """Decrypt a value produced by :func:`encrypt_secret`; reject unknown formats."""
    if not stored:
        return ""
    if not stored.startswith(_ENCRYPTED_SECRET_PREFIX):
        raise ValueError("Secret is not in the supported encrypted format")
    raw_key = hashlib.sha256(f"ivr-secret:v1:{purpose}:{secret}".encode("utf-8")).digest()
    token = stored.removeprefix(_ENCRYPTED_SECRET_PREFIX).encode("ascii")
    try:
        return Fernet(base64.urlsafe_b64encode(raw_key)).decrypt(token).decode("utf-8")
    except Exception as exc:
        raise ValueError("Could not decrypt stored secret") from exc


def is_encrypted_secret(value: str) -> bool:
    return str(value or "").startswith(_ENCRYPTED_SECRET_PREFIX)


_DIGIT_RUN_RE = re.compile(r"\d+")


def _mask_run(match: "re.Match[str]") -> str:
    run = match.group(0)
    if len(run) <= 2:
        return run
    return "*" * (len(run) - 2) + run[-2:]


def mask_digits_in_text(text: str) -> str:
    """Mask contiguous digit runs, keeping only the last two digits visible.

    Applied to every persisted ``CallEvent.message`` and WebSocket broadcast (see
    ``call_service.add_event``), and to phone numbers logged by the telephony
    providers. Verification codes and full phone numbers must never appear in full
    in audit logs, the live event feed, or application logs — plaintext access is
    restricted to the dedicated, authenticated, audited
    ``GET /api/calls/{id}/admin/entered-code`` endpoint.
    """
    return _DIGIT_RUN_RE.sub(_mask_run, str(text or ""))
