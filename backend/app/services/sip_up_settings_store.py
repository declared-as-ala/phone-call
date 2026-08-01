"""Persist SIP UP account settings edited from the admin UI (overrides env at runtime)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..security import decrypt_secret, encrypt_secret, is_encrypted_secret

logger = logging.getLogger(__name__)

_SETTINGS_FILENAME = "sip_up_account.json"
_PASSWORD_PURPOSE = "sip-up-account-password"
_ENV_KEY_MAP: dict[str, str] = {
    "SIPUP_SIP_USERNAME": "sip_username",
    "SIPUP_SIP_PASSWORD": "sip_password",
    "SIPUP_OUTBOUND_CALLER_ID": "outbound_caller_id",
    "SIPUP_SIP_DOMAIN": "sip_domain",
    "SIPUP_SIP_PORT": "sip_port",
    "ASTERISK_CALLER_ID": "outbound_caller_id",
}


def _settings_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    local_dir = root / ".local"
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir / _SETTINGS_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digits_only(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _load_raw() -> dict[str, Any]:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read SIP UP settings store %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}

    stored_password = str(data.get("sip_password") or "")
    if not stored_password:
        return data
    if is_encrypted_secret(stored_password):
        try:
            data["sip_password"] = decrypt_secret(
                stored_password,
                secret=config.SIP_UP_SETTINGS_SECRET,
                purpose=_PASSWORD_PURPOSE,
            )
        except ValueError as exc:
            logger.error(
                "Could not decrypt SIP UP password in %s; check SIP_UP_SETTINGS_SECRET",
                path,
            )
            raise RuntimeError(
                "Stored SIP UP password cannot be decrypted; check SIP_UP_SETTINGS_SECRET"
            ) from exc
        return data

    # One-time migration for stores written before SEC-6. Never log the value.
    _save_raw(data)
    return data


def _save_raw(data: dict[str, Any]) -> None:
    path = _settings_path()
    persisted = dict(data)
    password = str(persisted.get("sip_password") or "")
    if password and not is_encrypted_secret(password):
        persisted["sip_password"] = encrypt_secret(
            password,
            secret=config.SIP_UP_SETTINGS_SECRET,
            purpose=_PASSWORD_PURPOSE,
        )
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(persisted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.chmod(0o600)
    temp_path.replace(path)
    path.chmod(0o600)


def has_ui_settings() -> bool:
    return bool(_load_raw())


def env_lookup(name: str, default: str = "") -> str:
    """Return stored UI value for ``name`` when set, else ``os.environ``."""
    field = _ENV_KEY_MAP.get(name)
    if field:
        stored = _load_raw().get(field)
        if stored is not None and str(stored).strip():
            return str(stored).strip()
    return (os.getenv(name, "") or default).strip()


def get_public_settings() -> dict[str, Any]:
    """Settings safe for API responses (no password)."""
    raw = _load_raw()
    env_caller_id = (
        os.getenv("SIPUP_OUTBOUND_CALLER_ID", "").strip()
        or os.getenv("ASTERISK_CALLER_ID", "").strip()
    )
    env_username = os.getenv("SIPUP_SIP_USERNAME", "").strip()
    env_domain = os.getenv("SIPUP_SIP_DOMAIN", "").strip() or "sip.sipup.org"
    raw_port = os.getenv("SIPUP_SIP_PORT", "").strip()
    env_port = int(raw_port) if raw_port.isdigit() else 5060

    label = str(raw.get("label") or "").strip() or "SIP UP account (configured)"
    outbound_caller_id = str(raw.get("outbound_caller_id") or "").strip() or env_caller_id
    sip_username = str(raw.get("sip_username") or "").strip() or env_username
    sip_domain = str(raw.get("sip_domain") or "").strip() or env_domain
    sip_port_raw = raw.get("sip_port")
    if isinstance(sip_port_raw, int) and 1 <= sip_port_raw <= 65535:
        sip_port = sip_port_raw
    elif isinstance(sip_port_raw, str) and sip_port_raw.isdigit():
        sip_port = int(sip_port_raw)
    else:
        sip_port = env_port

    password_present = bool(str(raw.get("sip_password") or "").strip()) or bool(
        os.getenv("SIPUP_SIP_PASSWORD", "").strip()
    )

    return {
        "label": label,
        "sip_username": sip_username,
        "sip_domain": sip_domain,
        "sip_port": sip_port,
        "outbound_caller_id": outbound_caller_id,
        "password_present": password_present,
        "source": "ui" if has_ui_settings() else "env",
        "last_updated": raw.get("updated_at"),
    }


def update_settings(
    *,
    label: Optional[str] = None,
    sip_username: Optional[str] = None,
    sip_password: Optional[str] = None,
    sip_domain: Optional[str] = None,
    sip_port: Optional[int] = None,
    outbound_caller_id: Optional[str] = None,
) -> dict[str, Any]:
    """Merge updates into the UI settings store and sync infra when possible."""
    current = _load_raw()
    merged = dict(current)

    if label is not None:
        clean_label = str(label).strip()
        if not clean_label:
            raise ValueError("label must not be empty")
        merged["label"] = clean_label[:64]

    if sip_username is not None:
        clean_user = str(sip_username).strip()
        if not clean_user:
            raise ValueError("sip_username must not be empty")
        merged["sip_username"] = clean_user[:64]

    if sip_password is not None:
        clean_pw = str(sip_password)
        if clean_pw.strip():
            merged["sip_password"] = clean_pw

    if sip_domain is not None:
        clean_domain = str(sip_domain).strip()
        if not clean_domain:
            raise ValueError("sip_domain must not be empty")
        merged["sip_domain"] = clean_domain[:255]

    if sip_port is not None:
        if not (1 <= int(sip_port) <= 65535):
            raise ValueError("sip_port must be between 1 and 65535")
        merged["sip_port"] = int(sip_port)

    if outbound_caller_id is not None:
        digits = _digits_only(outbound_caller_id)
        if len(digits) < 3:
            raise ValueError("outbound_caller_id must be at least 3 digits")
        merged["outbound_caller_id"] = digits

    if not merged.get("sip_username") and not env_lookup("SIPUP_SIP_USERNAME"):
        raise ValueError("sip_username is required")
    if not merged.get("outbound_caller_id") and not env_lookup("SIPUP_OUTBOUND_CALLER_ID"):
        raise ValueError("outbound_caller_id is required")

    merged["updated_at"] = _utc_now_iso()
    _save_raw(merged)

    sync_result = _sync_infra_env(merged)
    public = get_public_settings()
    public["infra_sync"] = sync_result
    return public


def _sync_infra_env(settings: dict[str, Any]) -> dict[str, Any]:
    """Best-effort update of infra/sipup/.env and pjsip.conf render."""
    backend_root = Path(__file__).resolve().parents[2]
    infra_env = backend_root.parent / "infra" / "sipup" / ".env"
    if not infra_env.is_file():
        return {
            "ok": False,
            "message": "infra/sipup/.env not found — backend runtime updated; restart Asterisk manually if needed.",
        }

    updates = {
        "SIPUP_SIP_USERNAME": str(settings.get("sip_username") or env_lookup("SIPUP_SIP_USERNAME")),
        "SIPUP_OUTBOUND_CALLER_ID": str(
            settings.get("outbound_caller_id") or env_lookup("SIPUP_OUTBOUND_CALLER_ID")
        ),
        "ASTERISK_CALLER_ID": str(
            settings.get("outbound_caller_id") or env_lookup("SIPUP_OUTBOUND_CALLER_ID")
        ),
        "SIPUP_SIP_DOMAIN": str(settings.get("sip_domain") or env_lookup("SIPUP_SIP_DOMAIN") or "sip.sipup.org"),
    }
    if settings.get("sip_port") is not None:
        updates["SIPUP_SIP_PORT"] = str(int(settings["sip_port"]))
    if settings.get("sip_password"):
        updates["SIPUP_SIP_PASSWORD"] = str(settings["sip_password"])

    try:
        text = infra_env.read_text(encoding="utf-8")
        for key, value in updates.items():
            pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
            line = f"{key}={value}"
            if pattern.search(text):
                text = pattern.sub(line, text)
            else:
                text = text.rstrip() + "\n" + line + "\n"
        infra_env.write_text(text, encoding="utf-8")
        infra_env.chmod(0o600)
    except OSError as e:
        return {"ok": False, "message": f"Could not update infra/sipup/.env: {e}"}

    render_script = backend_root.parent / "infra" / "sipup" / "scripts" / "render_pjsip_from_env.py"
    if not render_script.is_file():
        return {
            "ok": True,
            "message": "Saved. infra/sipup/.env updated; render script not found — run docker compose restart asterisk.",
        }

    try:
        proc = subprocess.run(
            [os.environ.get("PYTHON", "python"), str(render_script)],
            cwd=str(render_script.parents[1]),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:300]
            return {
                "ok": True,
                "message": (
                    "Saved to UI store and infra/sipup/.env. pjsip render failed — "
                    f"restart Asterisk after fixing: {err}"
                ),
            }
    except (OSError, subprocess.TimeoutExpired) as e:
        return {
            "ok": True,
            "message": f"Saved. infra/sipup/.env updated; pjsip render skipped ({e}). Restart Asterisk.",
        }

    return {
        "ok": True,
        "message": "Saved. infra/sipup/.env and pjsip.conf updated — restart Asterisk (docker compose restart asterisk) if registration does not refresh.",
    }
