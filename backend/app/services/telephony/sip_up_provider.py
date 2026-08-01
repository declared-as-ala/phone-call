"""
SIP UP outbound path: SIP trunk credentials + trunk id from ``SIPUP_*`` env vars.

PSTN placement order:

* SIP UP media when ``ASTERISK_HOST`` / credentials / ``ASTERISK_CONTEXT`` are set —
  originates via ``SIPUP_PJSIP_ENDPOINT`` (not ``ASTERISK_ENDPOINT``);
* optional ``SIPUP_ORIGINATE_POST_URL`` — POST JSON payload for an external gateway; or
* local simulation — same lifecycle events and :class:`~app.services.prompt_renderer.PromptRenderer`
  consent copy as :class:`~app.services.telephony.mock_provider.MockTelephonyProvider`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, replace

from ...compliance import operator_consent_ivr_playing_message
from ...event_types import LEGACY_CHANNEL_CONNECTED_EVENT, CallEventType
from ...exceptions import SipUpConfigurationError
from ...security import mask_digits_in_text
from ..prompt_renderer import PromptRenderer
from .sip_up_ari_provider import (
    ASTERISK_CONTEXT,
    ASTERISK_HOST,
    ASTERISK_PASSWORD,
    ASTERISK_USERNAME,
    SipUpAriProvider,
    SipUpAriProviderConfig,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_DIAL_FORMAT,
    DIAL_FORMATS,
    normalize_phone_for_dial,
)
from .dial_plan import resolve_dial_plan
from .base import CallEventEmitter, TelephonyProvider

logger = logging.getLogger(__name__)

SIPUP_SIP_HOST = "SIPUP_SIP_HOST"
SIPUP_SIP_DOMAIN = "SIPUP_SIP_DOMAIN"
SIPUP_SIP_PORT = "SIPUP_SIP_PORT"
SIPUP_SIP_USERNAME = "SIPUP_SIP_USERNAME"
SIPUP_SIP_PASSWORD = "SIPUP_SIP_PASSWORD"
SIPUP_PJSIP_ENDPOINT = "SIPUP_PJSIP_ENDPOINT"
SIPUP_OUTBOUND_CALLER_ID = "SIPUP_OUTBOUND_CALLER_ID"
SIPUP_DIAL_FORMAT = "SIPUP_DIAL_FORMAT"
SIPUP_DIAL_PREFIX = "SIPUP_DIAL_PREFIX"
SIPUP_DEFAULT_COUNTRY_CODE = "SIPUP_DEFAULT_COUNTRY_CODE"
SIPUP_ORIGINATE_POST_URL = "SIPUP_ORIGINATE_POST_URL"
SIPUP_ORIGINATE_POST_TOKEN = "SIPUP_ORIGINATE_POST_TOKEN"

# Public SIP registrar hostname for SIP UP Telecom; used when host/domain unset in local development.
DEFAULT_SIP_UP_TELECOM_REGISTRAR = "sip.sipup.org"
SIPUP_FALLBACK_REGISTRAR = "SIPUP_FALLBACK_REGISTRAR"


@dataclass(frozen=True)
class SipUpTelephonyConfig:
    """Runtime SIP UP trunk settings (environment only)."""

    sip_host: str
    sip_port: int
    sip_username: str
    sip_password: str
    trunk_endpoint: str
    outbound_caller_id: str
    dial_format: str
    dial_prefix: str
    default_country_code: str
    originate_post_url: str
    originate_post_token: str

    @classmethod
    def from_env(cls) -> SipUpTelephonyConfig:
        from ..sip_up_settings_store import env_lookup

        raw_port = env_lookup(SIPUP_SIP_PORT)
        port = int(raw_port) if raw_port.isdigit() else 5060
        raw_primary = (os.getenv(SIPUP_DIAL_FORMAT, "") or "").strip().lower()
        dial_format = raw_primary if raw_primary in DIAL_FORMATS else DEFAULT_DIAL_FORMAT
        dial_prefix = (os.getenv(SIPUP_DIAL_PREFIX, "") or "").strip()
        cc_primary = (os.getenv(SIPUP_DEFAULT_COUNTRY_CODE, "") or "").strip()
        cc_fallback = cc_primary or DEFAULT_COUNTRY_CODE
        raw_host = (os.getenv(SIPUP_SIP_HOST, "") or "").strip()
        domain = env_lookup(SIPUP_SIP_DOMAIN)
        effective_host = raw_host or domain
        if not effective_host:
            fb_raw = os.getenv(SIPUP_FALLBACK_REGISTRAR)
            if fb_raw is None:
                from ...config import LOCAL_DEVELOPMENT

                effective_host = (
                    DEFAULT_SIP_UP_TELECOM_REGISTRAR if LOCAL_DEVELOPMENT else ""
                )
            else:
                effective_host = fb_raw.strip()
            if effective_host and not raw_host and not domain:
                logger.info(
                    "SipUpTelephonyConfig: registrar host %s (set %s / %s to override; "
                    "%s= to disable default in development)",
                    effective_host,
                    SIPUP_SIP_HOST,
                    SIPUP_SIP_DOMAIN,
                    SIPUP_FALLBACK_REGISTRAR,
                )
        return cls(
            sip_host=effective_host,
            sip_port=port,
            sip_username=env_lookup(SIPUP_SIP_USERNAME),
            sip_password=env_lookup(SIPUP_SIP_PASSWORD),
            trunk_endpoint=(os.getenv(SIPUP_PJSIP_ENDPOINT, "") or "").strip(),
            outbound_caller_id=env_lookup(SIPUP_OUTBOUND_CALLER_ID),
            dial_format=dial_format,
            dial_prefix=dial_prefix,
            default_country_code=cc_primary or cc_fallback,
            originate_post_url=(os.getenv(SIPUP_ORIGINATE_POST_URL, "") or "").strip(),
            originate_post_token=(os.getenv(SIPUP_ORIGINATE_POST_TOKEN, "") or "").strip(),
        )

    def validate(self) -> None:
        checks: list[tuple[str, str]] = [
            (f"{SIPUP_SIP_HOST} or {SIPUP_SIP_DOMAIN}", self.sip_host),
            (SIPUP_SIP_USERNAME, self.sip_username),
            (SIPUP_SIP_PASSWORD, self.sip_password),
            (SIPUP_PJSIP_ENDPOINT, self.trunk_endpoint),
            (SIPUP_OUTBOUND_CALLER_ID, self.outbound_caller_id),
        ]
        missing = [name for name, val in checks if not val]
        if missing:
            hint = (
                " SIP UP needs SIP registrar reachability: set "
                f"{SIPUP_SIP_HOST} (IP/hostname) and/or {SIPUP_SIP_DOMAIN} "
                f"(carrier domain — used when host is unset). Use the **device** SIP "
                f"credentials under Appareils/Devices ({SIPUP_SIP_USERNAME} / "
                f"{SIPUP_SIP_PASSWORD}), not only your SIP UP web-dashboard login — "
                f"often the device username is numeric. Also set trunk + CLI "
                f"({SIPUP_PJSIP_ENDPOINT}, {SIPUP_OUTBOUND_CALLER_ID}). "
                "Ensure `backend/.env` loads for the FastAPI process, or place `SIPUP_*` "
                "in `infra/sipup/.env` (merged automatically after `backend/.env` in "
                "local APP_ENV unless `BACKEND_MERGE_INFRA_SIPUP_DOTENV=0`). "
                "In local development, registrar defaults to sip.sipup.org when unset "
                f"(override with {SIPUP_SIP_HOST}/{SIPUP_SIP_DOMAIN}; set "
                f"`{SIPUP_FALLBACK_REGISTRAR}=` empty to disable). "
                f"Optional: {SIPUP_ORIGINATE_POST_URL} forwards originate to your gateway."
            )
            raise SipUpConfigurationError(
                "SipUpTelephonyProvider: missing required environment variables: "
                + ", ".join(missing)
                + "."
                + hint
            )

        if self.sip_port < 1 or self.sip_port > 65535:
            raise SipUpConfigurationError(f"{SIPUP_SIP_PORT} must be between 1 and 65535")

    @classmethod
    def for_call(
        cls,
        phone_number: str,
        *,
        outbound_caller_id: Optional[str] = None,
    ) -> "SipUpTelephonyConfig":
        """Env defaults + per-destination dial plan + optional per-call caller ID."""
        base = cls.from_env()
        dial_format, cc = resolve_dial_plan(
            phone_number,
            "sip_up",
            fallback_dial_format=base.dial_format,
            fallback_country_code=base.default_country_code,
        )
        cid = (outbound_caller_id or base.outbound_caller_id or "").strip()
        return replace(
            base,
            outbound_caller_id=cid,
            dial_format=dial_format,
            default_country_code=cc,
        )

    def normalized_destination(self, phone_number: str) -> str:
        return normalize_phone_for_dial(
            phone_number,
            dial_format=self.dial_format,
            dial_prefix=self.dial_prefix,
            default_country_code=self.default_country_code,
        )

    def build_pjsip_dial_string(self, normalized_destination: str) -> str:
        endpoint = self.trunk_endpoint.strip()
        dest = str(normalized_destination or "").strip()
        if not endpoint:
            return dest
        if endpoint.startswith(("PJSIP/", "SIP/", "Local/")):
            return endpoint.format(phone_number=dest, destination=dest)
        return f"PJSIP/{dest}@{endpoint}"


def sip_up_ari_connection_configured() -> bool:
    """True when shared SIP UP media connection vars are present (trunk comes from SIPUP_*)."""
    return all(
        (os.getenv(name, "") or "").strip()
        for name in (ASTERISK_HOST, ASTERISK_USERNAME, ASTERISK_PASSWORD, ASTERISK_CONTEXT)
    )


def build_sip_up_ari_config(
    sip_config: SipUpTelephonyConfig,
) -> SipUpAriProviderConfig:
    """Map SIP UP trunk/dial settings onto the shared SIP UP media connection."""
    base = SipUpAriProviderConfig.from_env()
    return SipUpAriProviderConfig(
        host=base.host,
        port=base.port,
        username=base.username,
        password=base.password,
        context=base.context,
        endpoint=sip_config.trunk_endpoint,
        ari_prefix=base.ari_prefix,
        ari_app=base.ari_app,
        caller_id=sip_config.outbound_caller_id,
        originate_timeout_seconds=base.originate_timeout_seconds,
        dial_format=sip_config.dial_format,
        dial_prefix=sip_config.dial_prefix,
        default_country_code=sip_config.default_country_code,
        provider_display_name="SIP UP",
    )


class SipUpTelephonyProvider(TelephonyProvider):
    """Outbound IVR leg for SIP UP without SIP UP media."""

    def __init__(self, config: SipUpTelephonyConfig | None = None) -> None:
        self._config = config or SipUpTelephonyConfig.from_env()

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
        self._config.validate()

        masked = mask_digits_in_text(phone_number)
        normalized = self._config.normalized_destination(phone_number)
        masked_dialed = mask_digits_in_text(normalized)
        dial_str = self._config.build_pjsip_dial_string(normalized)

        logger.info(
            "SipUpTelephonyProvider.start_outbound session_id=%s masked_input=%s masked_dialed=%s "
            "trunk=%s sip_host=%s sip_port=%s",
            session_id,
            masked,
            masked_dialed,
            self._config.trunk_endpoint,
            self._config.sip_host,
            self._config.sip_port,
        )

        consent = PromptRenderer.consent_prompt(name, organization)

        post_url = self._config.originate_post_url
        if post_url:
            await emitter.emit(
                session_id,
                CallEventType.DIAL_STARTED.value,
                (
                    f"SIP UP outbound dial started (input {masked}, dialed {masked_dialed}; "
                    f"PJSIP target {dial_str})"
                ),
            )
            headers: dict[str, str] = {"Content-Type": "application/json"}
            token = self._config.originate_post_token.strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = {
                "session_id": session_id,
                "destination": normalized,
                "pjsip_dial_string": dial_str,
                "caller_id": self._config.outbound_caller_id,
                "sip_trunk": self._config.trunk_endpoint,
                "sip_registration": {
                    "host": self._config.sip_host,
                    "port": self._config.sip_port,
                    "username": self._config.sip_username,
                    # Intentionally omit password — gateways should hold secrets or mint SIP auth server-side.
                },
                "dial_format": self._config.dial_format,
                "name": (name or "").strip(),
                "organization": (organization or "").strip(),
                "consent_prompt_text": consent["text"],
                "consent_prompt_key": consent["prompt_key"],
            }
            timeout = httpx.Timeout(15.0, connect=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(post_url, headers=headers, json=body)
            if r.status_code >= 400:
                detail = r.text[:500] if r.text else "(empty body)"
                raise RuntimeError(
                    f"SIP UP originate webhook failed ({SIPUP_ORIGINATE_POST_URL}): "
                    f"HTTP {r.status_code}: {detail}"
                )
            return

        if sip_up_ari_connection_configured():
            ast_config = build_sip_up_ari_config(self._config)
            cid = (outbound_caller_id or self._config.outbound_caller_id or "").strip()
            await SipUpAriProvider(ast_config).start_outbound(
                session_id,
                phone_number,
                emitter,
                organization=organization,
                name=name,
                outbound_caller_id=cid or None,
            )
            return

        await emitter.emit(
            session_id,
            CallEventType.DIAL_STARTED.value,
            (
                f"SIP UP outbound dial started (input {masked}, dialed {masked_dialed}; "
                f"PJSIP target {dial_str})"
            ),
        )

        await asyncio.sleep(0.35)
        await emitter.emit(session_id, CallEventType.CALL_RINGING.value, "Remote party ringing")
        await asyncio.sleep(0.45)
        await emitter.emit(session_id, LEGACY_CHANNEL_CONNECTED_EVENT, "Call answered")
        await asyncio.sleep(0.28)
        await emitter.emit(session_id, CallEventType.IVR_PROMPT.value, operator_consent_ivr_playing_message())
