import logging
import os
import sys
from pathlib import Path
from typing import Optional

_PRODUCTION_LIKE_ENV = frozenset({"staging", "production", "prod"})


def _should_merge_infra_sipup_dotenv(backend_dir: Path) -> bool:
    """Merge infra SIP/PJSIP vars into the process unless explicitly disabled."""
    raw = os.getenv("BACKEND_MERGE_INFRA_SIPUP_DOTENV", "").strip().lower()
    if raw in {"0", "false", "no"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True

    raw_mode = (os.getenv("APP_ENV") or "").strip().lower() or "development"
    if raw_mode in _PRODUCTION_LIKE_ENV:
        return False
    # Pytest imports the pytest package before app modules load; merging would leak SIPUP_* into suites.
    if "pytest" in sys.modules:
        return False

    infra_env = backend_dir.parent / "infra" / "sipup" / ".env"
    return infra_env.is_file()


def _load_backend_dotenv() -> None:
    """Load ``backend/.env`` if present (does not override existing OS env).

    Optionally merges ``infra/sipup/.env`` **after** ``backend/.env``:

    * **Default:** merge when ``APP_ENV`` is not staging/production-like, the infra file exists,
      and pytest is not running (``BACKEND_MERGE_INFRA_SIPUP_DOTENV`` unset).
    * **Explicit:** ``BACKEND_MERGE_INFRA_SIPUP_DOTENV=1`` or ``...=0``.
    Disabled when ``PYTHON_DOTENV_DISABLED`` is truthy or python-dotenv is missing.
    """
    if os.getenv("PYTHON_DOTENV_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    backend_dir = Path(__file__).resolve().parent.parent
    env_file = backend_dir / ".env"
    if env_file.is_file():
        # Do not override explicit OS/test env (e.g. APP_ENV=staging in pytest reload).
        load_dotenv(env_file, override=False)

    if _should_merge_infra_sipup_dotenv(backend_dir):
        infra_env = backend_dir.parent / "infra" / "sipup" / ".env"
        if infra_env.is_file():
            load_dotenv(infra_env, override=False)


_load_backend_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV: str = os.getenv("APP_ENV", "development").lower()
_PRODUCTION_ENVS = {"staging", "production", "prod"}

# SQLAlchemy / Alembic database URL (override for tests via monkeypatch on engine, not this value).
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./ivr_verification.db")

# When false, POST /api/calls/start omits demo_code from the response.
LOCAL_DEVELOPMENT: bool = APP_ENV in (
    "development",
    "dev",
    "local",
)

JWT_SECRET_KEY: Optional[str] = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
AUTH_COOKIE_NAME: str = os.getenv("AUTH_COOKIE_NAME", "ivr_admin_access_token")
LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = max(
    1, int(os.getenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "5"))
)
LOGIN_RATE_LIMIT_WINDOW_MINUTES: int = max(
    1, int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_MINUTES", "15"))
)


def get_cors_allowed_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    configured = list(dict.fromkeys(origin.strip() for origin in raw.split(",") if origin.strip()))
    if configured:
        if "*" in configured:
            raise RuntimeError(
                "CORS_ALLOWED_ORIGINS cannot contain '*' while credentialed requests are enabled"
            )
        return configured
    if LOCAL_DEVELOPMENT:
        return [
            origin
            for port in range(5173, 5190)
            for origin in (f"http://localhost:{port}", f"http://127.0.0.1:{port}")
        ]
    return []

if not JWT_SECRET_KEY and LOCAL_DEVELOPMENT:
    JWT_SECRET_KEY = "dev-admin-jwt-secret-change-in-production"


def validate_auth_configuration() -> None:
    if APP_ENV in _PRODUCTION_ENVS:
        required = (
            "DATABASE_URL",
            "JWT_SECRET_KEY",
            "DTMF_BUFFER_SECRET",
            "TELEPHONY_WEBHOOK_SECRET",
            "CORS_ALLOWED_ORIGINS",
            "SIP_UP_SETTINGS_SECRET",
        )
        missing = [name for name in required if not (os.getenv(name) or "").strip()]
        if missing:
            raise RuntimeError(
                "Missing required staging/production environment variables: "
                + ", ".join(missing)
            )
        if not _env_bool("AUTH_COOKIE_SECURE", False):
            raise RuntimeError("AUTH_COOKIE_SECURE=1 is required in staging/production")
        # Parse now so wildcard/format errors fail startup, not the first browser request.
        get_cors_allowed_origins()
    if LOCAL_DEVELOPMENT and JWT_SECRET_KEY == "dev-admin-jwt-secret-change-in-production":
        logging.getLogger(__name__).warning(
            "Using development JWT_SECRET_KEY. Set JWT_SECRET_KEY before staging/production."
        )
    if LOCAL_DEVELOPMENT and not TELEPHONY_WEBHOOK_SECRET:
        logging.getLogger(__name__).warning(
            "TELEPHONY_WEBHOOK_SECRET is not set — /api/telephony/events accepts unsigned "
            "requests in development. Set TELEPHONY_WEBHOOK_SECRET (and configure the ARI "
            "bridge with the same value) before staging/production."
        )

# Local-only console transcript (not a virtual/simulated call — real SIP UP calls still print this when enabled).
# Disabled by default when TELEPHONY_PROVIDER=sip_up; set VIRTUAL_CALL_DEVICE_ENABLED=1 to re-enable.
_default_virtual_device = LOCAL_DEVELOPMENT and os.getenv("TELEPHONY_PROVIDER", "mock").strip().lower() not in {
    "sip_up",
    "asterisk",
}
VIRTUAL_CALL_DEVICE_ENABLED: bool = _env_bool("VIRTUAL_CALL_DEVICE_ENABLED", _default_virtual_device)

# Max outbound sessions started per normalized phone number per UTC calendar day (0 = unlimited).
MAX_CALLS_PER_PHONE_PER_DAY: int = int(os.getenv("MAX_CALLS_PER_PHONE_PER_DAY", "100"))

# Minimum seconds after a SIP UP call ends before starting another (reduces SIP 403 overlap rejects).
SIPUP_MIN_SECONDS_BETWEEN_CALLS: int = max(
    0, int(os.getenv("SIPUP_MIN_SECONDS_BETWEEN_CALLS", "45"))
)

# Active calls with no updates for this many minutes are auto-closed (prevents stuck "dialing" blocking new calls).
SIPUP_ACTIVE_CALL_STALE_MINUTES: int = max(
    1, int(os.getenv("SIPUP_ACTIVE_CALL_STALE_MINUTES", "20"))
)

# Symmetric key material for encrypting persisted DTMF buffers (derive per-session Fernet keys).
DTMF_BUFFER_SECRET: str = os.getenv("DTMF_BUFFER_SECRET", "dev-dtmf-buffer-secret-change-in-production")

# Dedicated key material for the admin-edited SIP credential store. Production must
# provide this explicitly; development falls back to a local-only value.
SIP_UP_SETTINGS_SECRET: str = os.getenv(
    "SIP_UP_SETTINGS_SECRET", "dev-sip-up-settings-secret-change-in-production"
)

# Optional second auth for `/ws`: long-lived secret for the SIP UP media bridge (same value as BACKEND_WS_TOKEN).
# Prefer this over rotating admin JWTs for service connections.
_WS_BT_RAW = os.getenv("WS_BROADCAST_BRIDGE_TOKEN", "").strip()
WS_BROADCAST_BRIDGE_TOKEN: Optional[str] = _WS_BT_RAW if _WS_BT_RAW else None

# Shared HMAC secret for POST /api/telephony/events (see app.webhook_security). Must match the
# same value the ARI bridge (scripts/run_sip_up_ari_bridge.py) is configured with. Required in
# staging/production (see validate_auth_configuration); optional in development, where an unset
# value preserves the pre-existing unsigned-webhook behavior for local dry runs and tests.
_TELEPHONY_WEBHOOK_SECRET_RAW = os.getenv("TELEPHONY_WEBHOOK_SECRET", "").strip()
TELEPHONY_WEBHOOK_SECRET: Optional[str] = _TELEPHONY_WEBHOOK_SECRET_RAW or None

# Max allowed clock skew between the ARI bridge's signed timestamp and server time (replay guard).
TELEPHONY_WEBHOOK_TOLERANCE_SECONDS: int = max(
    5, int(os.getenv("TELEPHONY_WEBHOOK_TOLERANCE_SECONDS", "300"))
)
