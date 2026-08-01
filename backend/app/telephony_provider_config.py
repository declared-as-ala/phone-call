"""Telephony provider mode and cutover guard (env validation only — no outbound wiring)."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Literal, Optional
from urllib import error, request

logger = logging.getLogger("app.startup")

TelephonyProviderMode = Literal["mock", "client_api", "sip_up"]

PROVIDER_LABELS: dict[TelephonyProviderMode, str] = {
    "mock": "Mock",
    "sip_up": "SIP UP",
    "client_api": "Client API",
}

SIP_UP_PROVIDER_LABEL = "SIP UP"


def default_outbound_provider_label() -> str:
    """Label for global runtime banner when SIP UP trunk is the configured default."""
    mode = telephony_provider_mode()
    if mode == "mock":
        return PROVIDER_LABELS["mock"]
    endpoint = (os.getenv("ASTERISK_ENDPOINT", "") or "").strip().lower()
    sip_trunk = (os.getenv("SIPUP_PJSIP_ENDPOINT", "") or "sip-up-trunk").strip().lower()
    if endpoint == sip_trunk or endpoint == "sip-up-trunk":
        return SIP_UP_PROVIDER_LABEL
    if os.getenv("SIPUP_SIP_USERNAME", "").strip() and os.getenv("SIPUP_SIP_PASSWORD", "").strip():
        return SIP_UP_PROVIDER_LABEL
    return PROVIDER_LABELS[telephony_provider_mode()]

# User-facing CALL_INITIATED message per provider mode (no internal jargon).
CALL_INITIATED_MESSAGES: dict[TelephonyProviderMode, str] = {
    "mock": "Local mock telephony simulation initiated",
    "sip_up": "Real outbound call requested through SIP UP",
    "client_api": "Outbound call request submitted to client telephony API",
}

SIP_UP_CALL_INITIATED_MESSAGE = "Real outbound call requested through SIP UP"

PROVIDER_CLASS_NAMES: dict[TelephonyProviderMode, str] = {
    "mock": "MockTelephonyProvider",
    "sip_up": "SipUpAriProvider",
    "client_api": "ClientApiTelephonyProvider",
}


def _raw_telephony_provider_env() -> str:
    return os.getenv("TELEPHONY_PROVIDER", "mock").strip().lower() or "mock"


def telephony_provider_mode() -> TelephonyProviderMode:
    """Canonical provider mode from ``TELEPHONY_PROVIDER`` (default ``mock``)."""
    raw = _raw_telephony_provider_env()
    if raw in ("mock", "local", "simulator"):
        return "mock"
    if raw in ("client_api", "client", "real"):
        return "client_api"
    if raw in ("sip_up", "asterisk"):
        return "sip_up"
    raise RuntimeError(
        f"Unknown TELEPHONY_PROVIDER={raw!r}; use mock, client_api, or sip_up"
    )


def provider_label(mode: Optional[TelephonyProviderMode] = None) -> str:
    return PROVIDER_LABELS[mode or telephony_provider_mode()]


def call_initiated_message(mode: Optional[TelephonyProviderMode] = None) -> str:
    return CALL_INITIATED_MESSAGES[mode or telephony_provider_mode()]


def call_initiated_message_for_start(
    mode: TelephonyProviderMode, outbound_trunk: str
) -> str:
    """User-facing CALL_INITIATED copy; sip_up overrides global TELEPHONY_PROVIDER label."""
    if mode == "mock":
        return CALL_INITIATED_MESSAGES["mock"]
    if outbound_trunk == "sip_up" or (outbound_trunk or "").strip().lower() in ("", "default"):
        return SIP_UP_CALL_INITIATED_MESSAGE
    return CALL_INITIATED_MESSAGES[mode]


def provider_class_name(mode: Optional[TelephonyProviderMode] = None) -> str:
    return PROVIDER_CLASS_NAMES[mode or telephony_provider_mode()]


def validate_telephony_provider_configuration_on_startup() -> TelephonyProviderMode:
    """
    Fail fast on startup if a non-mock provider is selected without required credentials.

    Does not log secrets.
    """
    mode = telephony_provider_mode()
    if mode == "mock":
        return mode
    if mode == "client_api":
        base = os.getenv("CLIENT_PROVIDER_BASE_URL", "").strip()
        key = os.getenv("CLIENT_PROVIDER_API_KEY", "").strip()
        if not base:
            raise RuntimeError(
                "TELEPHONY_PROVIDER=client_api requires CLIENT_PROVIDER_BASE_URL to be set and non-empty"
            )
        if not key:
            raise RuntimeError(
                "TELEPHONY_PROVIDER=client_api requires CLIENT_PROVIDER_API_KEY to be set and non-empty"
            )
        return mode
    if mode == "sip_up":
        host = os.getenv("ASTERISK_HOST", "").strip()
        user = os.getenv("ASTERISK_USERNAME", "").strip()
        password = os.getenv("ASTERISK_PASSWORD", "").strip()
        context = os.getenv("ASTERISK_CONTEXT", "").strip()
        endpoint = os.getenv("ASTERISK_ENDPOINT", "").strip()
        missing = [
            name
            for name, val in (
                ("ASTERISK_HOST", host),
                ("ASTERISK_USERNAME", user),
                ("ASTERISK_PASSWORD", password),
                ("ASTERISK_CONTEXT", context),
                ("ASTERISK_ENDPOINT", endpoint),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "TELEPHONY_PROVIDER=sip_up requires: "
                + ", ".join(missing)
            )
        return mode
    raise RuntimeError(f"Unhandled telephony mode: {mode!r}")


def log_startup_configuration(*, provider_mode: TelephonyProviderMode) -> None:
    """Log non-secret startup flags (APP_ENV, provider, demo_code, rate limits)."""
    from . import config as app_config

    app_env = os.getenv("APP_ENV", "development")
    demo = app_config.LOCAL_DEVELOPMENT
    cap = app_config.MAX_CALLS_PER_PHONE_PER_DAY
    if cap > 0:
        rate_msg = f"enabled (max {cap} starts per phone per UTC day)"
    else:
        rate_msg = "disabled (unlimited)"
    logger.info(
        "Startup: APP_ENV=%s TELEPHONY_PROVIDER=%s provider_class=%s "
        "demo_code_in_start_response=%s rate_limit=%s",
        app_env,
        provider_mode,
        provider_class_name(provider_mode),
        demo,
        rate_msg,
    )
    if provider_mode == "sip_up":
        logger.info(
            "Asterisk runtime: host=%s port=%s ari_prefix=%s ari_app=%s context=%s endpoint=%s "
            "originate_timeout=%ss caller_id=%s dial_format=%s dial_prefix=%s "
            "default_country_code=%s mock_scheduling=disabled",
            os.getenv("ASTERISK_HOST") or "(unset)",
            os.getenv("ASTERISK_PORT") or "(default 8088)",
            os.getenv("ASTERISK_ARI_PREFIX", "/asterisk/ari"),
            os.getenv("ASTERISK_ARI_APP", "ivr-bridge"),
            os.getenv("ASTERISK_CONTEXT") or "(unset)",
            os.getenv("ASTERISK_ENDPOINT") or "(unset)",
            os.getenv("ASTERISK_ORIGINATE_TIMEOUT_SECONDS", "25"),
            os.getenv("ASTERISK_CALLER_ID")
            or os.getenv("SIPUP_OUTBOUND_CALLER_ID")
            or "(unset)",
            os.getenv("SIPUP_DIAL_FORMAT") or "national (default)",
            os.getenv("SIPUP_DIAL_PREFIX") or "(none)",
            os.getenv("SIPUP_DEFAULT_COUNTRY_CODE") or "216",
        )


def _ari_basic_auth_header() -> Optional[str]:
    user = os.getenv("ASTERISK_USERNAME", "").strip()
    pw = os.getenv("ASTERISK_PASSWORD", "").strip()
    if not user or not pw:
        return None
    token = base64.b64encode(f"{user}:{pw}".encode()).decode("ascii")
    return f"Basic {token}"


def sip_up_operator_liveness() -> dict[str, Optional[bool]]:
    """Best-effort ARI HTTP probes for operator UI hints; never raises."""
    out: dict[str, Optional[bool]] = {
        "ari_unreachable": None,
        "sip_trunk_endpoint_online": None,
    }
    if os.getenv("ASTERISK_SKIP_LIVENESS", "").strip().lower() in {"1", "true", "yes"}:
        return out
    if telephony_provider_mode() != "sip_up":
        return out
    host = os.getenv("ASTERISK_HOST", "").strip()
    raw_port = os.getenv("ASTERISK_PORT", "").strip()
    port = int(raw_port) if raw_port.isdigit() else 8088
    raw_prefix = os.getenv("ASTERISK_ARI_PREFIX", "/asterisk/ari").strip()
    prefix = raw_prefix if raw_prefix.startswith("/") else f"/{raw_prefix}"
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    auth = _ari_basic_auth_header()
    trunk = (os.getenv("ASTERISK_ENDPOINT", "").strip()).lower()
    if not host or not auth:
        return out

    base = f"http://{host}:{port}{prefix}"

    def http_get(rel: str) -> tuple[Optional[int], bytes]:
        url = f"{base}{rel.lstrip('/')}"
        req = request.Request(url, headers={"Authorization": auth})
        try:
            with request.urlopen(req, timeout=1.5) as resp:
                return getattr(resp, "status", 200), resp.read()
        except error.HTTPError as e:
            return e.code, e.read()
        except (error.URLError, TimeoutError, OSError):
            return None, b""

    st, _body = http_get("asterisk/info")
    if st is None or st >= 400:
        out["ari_unreachable"] = True
        return out
    out["ari_unreachable"] = False

    if not trunk:
        return out

    st2, body = http_get("endpoints")
    if st2 is None or st2 >= 400 or not body:
        return out
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out

    token = trunk.replace("pjsip/", "").split("@")[0].strip()
    found = False
    online = False
    for ep in data:
        if not isinstance(ep, dict):
            continue
        res = str(ep.get("resource") or "").lower()
        if token and (token in res or res.endswith(token)):
            found = True
            state = str(ep.get("state") or "").lower()
            online = state not in ("offline",)
            break
    if found:
        out["sip_trunk_endpoint_online"] = online
    return out


def runtime_provider_info() -> dict[str, Any]:
    """Snapshot of resolved telephony provider state for debug/health UIs.

    Never includes secrets. Booleans like ``password_present`` indicate whether a
    secret value is configured without disclosing it. Callers must keep admin auth
    on any endpoint that returns this shape.
    """
    from . import config as app_config
    from .services.luvvoice_tts import api_token_configured, default_voice_id
    from .services.sip_up_settings_store import get_public_settings

    mode: TelephonyProviderMode = telephony_provider_mode()
    raw_port = os.getenv("ASTERISK_PORT", "").strip()
    raw_dial_format = (os.getenv("SIPUP_DIAL_FORMAT", "") or "").strip().lower()
    sip_account = get_public_settings()
    effective_caller_id = sip_account.get("outbound_caller_id") or (
        os.getenv("ASTERISK_CALLER_ID", "").strip()
        or os.getenv("SIPUP_OUTBOUND_CALLER_ID", "").strip()
        or None
    )
    sip_up_media = {
        "host": os.getenv("ASTERISK_HOST", "").strip() or None,
        "port": int(raw_port) if raw_port.isdigit() else 8088,
        "username_present": bool(os.getenv("ASTERISK_USERNAME", "").strip()),
        "password_present": bool(os.getenv("ASTERISK_PASSWORD", "").strip()),
        "context": os.getenv("ASTERISK_CONTEXT", "").strip() or None,
        "endpoint": (
            os.getenv("ASTERISK_ENDPOINT", "").strip()
            or os.getenv("SIPUP_PJSIP_ENDPOINT", "").strip()
            or None
        ),
        "ari_prefix": os.getenv("ASTERISK_ARI_PREFIX", "/asterisk/ari").strip()
        or "/asterisk/ari",
        "ari_app": os.getenv("ASTERISK_ARI_APP", "ivr-bridge").strip()
        or "ivr-bridge",
        "caller_id": effective_caller_id,
        "account_label": sip_account.get("label"),
        "sip_username": sip_account.get("sip_username") or None,
        "settings_source": sip_account.get("source"),
        "dial_format": raw_dial_format or "national",
        "dial_prefix": (os.getenv("SIPUP_DIAL_PREFIX", "") or "").strip(),
        "default_country_code": (
            os.getenv("SIPUP_DEFAULT_COUNTRY_CODE", "") or "216"
        ).strip(),
    }
    backend_events_url = (
        os.getenv("BACKEND_TELEPHONY_EVENTS_URL", "").strip()
        or "http://127.0.0.1:8000/api/telephony/events"
    )
    sip_up_ready = mode == "sip_up" and all(
        [
            sip_up_media["host"],
            sip_up_media["username_present"],
            sip_up_media["password_present"],
            sip_up_media["context"],
            sip_up_media["endpoint"],
        ]
    )
    live = sip_up_operator_liveness()
    sip_up_media["ari_unreachable"] = live["ari_unreachable"]
    sip_up_media["sip_trunk_endpoint_online"] = live["sip_trunk_endpoint_online"]
    return {
        "provider_mode": mode,
        "provider_label": default_outbound_provider_label(),
        "default_trunk": "sip_up",
        "provider_class": PROVIDER_CLASS_NAMES[mode],
        "app_env": os.getenv("APP_ENV", "development"),
        "local_development": app_config.LOCAL_DEVELOPMENT,
        "voice_mode": (
            "sip_up_call_audio" if mode == "sip_up" else "mock_simulation"
        ),
        "mock_scheduling_enabled": mode == "mock",
        "sip_up": sip_up_media,
        "sip_up_ready": sip_up_ready,
        "sip_up_ari_unreachable": live["ari_unreachable"],
        "sip_up_trunk_endpoint_online": live["sip_trunk_endpoint_online"],
        "backend_telephony_events_url": backend_events_url,
        "luvvoice": {
            "configured": api_token_configured(),
            "default_voice_id": default_voice_id(),
            "api_base": "https://luvvoice.com/api/v1/text-to-speech",
        },
    }
