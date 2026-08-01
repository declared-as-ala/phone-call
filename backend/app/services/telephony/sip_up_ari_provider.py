"""
Asterisk integration skeleton (ARI / AMI placeholders).

This module defines :class:`SipUpAriProvider`, the intended **production**
implementation for outbound verification calls through SIP UP media.

Provider behavior
-----------------

1. **Same abstract interface** — :class:`SipUpAriProvider` subclasses
   :class:`TelephonyProvider` and implements ``start_outbound`` as a thin bridge.
   Long term, prefer calling :meth:`start_call` with a persisted
   :class:`~app.models.CallSession` from your dial-plan / task runner so ARI
   channel IDs map cleanly to ``call_session.id``.

2. **Outbound flow** — ``start_outbound`` (or ``start_call``) should issue an
   Asterisk ``Originate`` (AMI) or ``POST /ari/channels`` (ARI) using
   ``ASTERISK_CONTEXT``, ``ASTERISK_ENDPOINT``, and the session’s
   ``phone_number``. Do not log or persist plaintext verification codes.

3. **Event-driven leg** — ARI/AMI Stasis or AGI callbacks should invoke:

   - :meth:`handle_call_answered` when the callee answers (maps to your
     ``CALL_ANSWERED`` / consent step in the app layer).
   - :meth:`handle_dtmf` for each DTMF digit (drive simulator / verification
     state machine or forward to existing ``verify_digits`` logic).
   - :meth:`hangup` to tear down the channel and emit final events.

4. **Wire-up** — ``outbound_simulation`` selects this provider when
   ``TELEPHONY_PROVIDER=sip_up``. It keeps the same :class:`CallEventEmitter`
   used by the mock path so events are masked and broadcast consistently.

5. **Secrets** — Load all connection parameters from environment (or a secret
   store). Never commit credentials; the placeholders below read **only** from
   ``os.environ``.
"""

from __future__ import annotations

import logging
import os
import asyncio
import json
from dataclasses import dataclass
from urllib import error, parse, request
from typing import TYPE_CHECKING, Any, Optional

from ...event_types import CallEventType
from ...exceptions import SipUpAriConfigurationError
from ...security import mask_digits_in_text
from .base import CallEventEmitter, TelephonyProvider
from .dial_plan import strip_national_trunk_zero

if TYPE_CHECKING:
    from ...models import CallSession

logger = logging.getLogger(__name__)

# --- Environment variable names (ARI / AMI style configuration) ---

ASTERISK_HOST = "ASTERISK_HOST"
ASTERISK_PORT = "ASTERISK_PORT"
ASTERISK_USERNAME = "ASTERISK_USERNAME"
ASTERISK_PASSWORD = "ASTERISK_PASSWORD"
ASTERISK_CONTEXT = "ASTERISK_CONTEXT"
ASTERISK_ENDPOINT = "ASTERISK_ENDPOINT"
ASTERISK_ARI_PREFIX = "ASTERISK_ARI_PREFIX"
ASTERISK_ARI_APP = "ASTERISK_ARI_APP"
ASTERISK_CALLER_ID = "ASTERISK_CALLER_ID"
ASTERISK_ORIGINATE_TIMEOUT_SECONDS = "ASTERISK_ORIGINATE_TIMEOUT_SECONDS"
SIPUP_OUTBOUND_CALLER_ID = "SIPUP_OUTBOUND_CALLER_ID"
SIPUP_PJSIP_ENDPOINT = "SIPUP_PJSIP_ENDPOINT"
SIPUP_DIAL_FORMAT = "SIPUP_DIAL_FORMAT"
SIPUP_DIAL_PREFIX = "SIPUP_DIAL_PREFIX"
SIPUP_DEFAULT_COUNTRY_CODE = "SIPUP_DEFAULT_COUNTRY_CODE"

# Supported destination-number formats for the configured SIP trunk.
DIAL_FORMATS = ("e164_plus", "e164_no_plus", "international_00", "national", "raw")
DEFAULT_DIAL_FORMAT = "national"
DEFAULT_COUNTRY_CODE = "216"


def _digits_only(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _maybe_prepend_default_country_digits(core_digits: str, default_country_code: str) -> str:
    """If ``core_digits`` lacks the default CC, treat it as subscriber-only (e.g. Tunisia +216).

    Used only with ``e164_no_plus``: bare national input like ``56340093`` becomes ``21656340093``.
    A narrow length band avoids prepending ambiguous longer international-digit strings."""
    cc = _digits_only(default_country_code)
    if not cc or not core_digits:
        return core_digits
    if core_digits.startswith(cc):
        return core_digits

    subscriber = core_digits
    # Single leading trunk zero (national dial habit)
    if subscriber.startswith("0") and len(subscriber) > 1:
        without0 = subscriber[1:]
        if without0.startswith(cc):
            return without0
        subscriber = without0
    if subscriber.startswith(cc):
        return subscriber

    # Tunisia mobile subscriber is commonly 8 digits; allow 7–9 for similar national shapes.
    if 7 <= len(subscriber) <= 9:
        return f"{cc}{subscriber}"
    return core_digits


def normalize_phone_for_dial(
    phone_number: str,
    *,
    dial_format: str = DEFAULT_DIAL_FORMAT,
    dial_prefix: str = "",
    default_country_code: str = DEFAULT_COUNTRY_CODE,
) -> str:
    """Convert a user-entered phone string into the dial-string the SIP trunk expects.

    ``dial_format`` controls the shape:

    * ``e164_plus`` — leading ``+`` plus all digits, e.g. ``+21652603967``.
    * ``e164_no_plus`` — digits only, e.g. ``21652603967``. Subscriber-only input
      like ``56340093`` (no ``+``, no CC) becomes ``21656340093`` when ``default_country_code`` matches
      the deployment trunk (narrow length heuristic).
    * ``international_00`` — ``00`` prefix, e.g. ``0021652603967``.
    * ``national`` — strip the country code, e.g. ``52603967``. Requires
      ``default_country_code`` to be set when the input has no ``+``.
    * ``raw`` — pass-through after stripping spaces/dashes/parens, no other change.

    ``dial_prefix`` is prepended verbatim after the format conversion (e.g. carrier-required
    access digits).

    Inputs that already use ``+`` or ``00`` international notation are accepted
    interchangeably; the formatter operates on the core E.164 digits.
    """
    raw = str(phone_number or "").strip()
    prefix = (dial_prefix or "").strip()
    chosen = (dial_format or DEFAULT_DIAL_FORMAT).strip().lower()

    if not raw:
        return prefix

    if chosen == "raw":
        cleaned = "".join(ch for ch in raw if ch in "+0123456789")
        return f"{prefix}{cleaned}" if cleaned else prefix

    digits = _digits_only(raw)
    if not digits:
        return prefix

    # Collapse "+" / "00" international prefixes to the bare E.164 digit string.
    if raw.startswith("+"):
        core = digits
    elif digits.startswith("00") and len(digits) > 4:
        core = digits[2:]
    else:
        core = digits

    # Fix ``+3307…`` / ``+3903…`` style paste errors before applying dial_format.
    core = strip_national_trunk_zero(core)

    # Subscriber-only (+ optional trunk 0), no "+" / "00" in final dial digit string.
    if chosen == "e164_no_plus" and default_country_code:
        core = _maybe_prepend_default_country_digits(core, default_country_code)

    if chosen == "e164_plus":
        return f"{prefix}+{core}"
    if chosen == "e164_no_plus":
        return f"{prefix}{core}"
    if chosen == "international_00":
        return f"{prefix}00{core}"
    if chosen == "national":
        cc = _digits_only(default_country_code)
        if cc and core.startswith(cc):
            return f"{prefix}{core[len(cc):]}"
        return f"{prefix}{core}"
    return f"{prefix}{core}"


@dataclass(frozen=True)
class SipUpAriProviderConfig:
    """
    Runtime configuration resolved from the environment.

    ``ASTERISK_PASSWORD`` must be supplied in production; no default is applied.
    """

    host: Optional[str]
    port: int
    username: Optional[str]
    password: Optional[str]
    context: Optional[str]
    endpoint: Optional[str]
    ari_prefix: str = "/asterisk/ari"
    ari_app: str = "ivr-bridge"
    caller_id: Optional[str] = None
    originate_timeout_seconds: int = 25
    dial_format: str = DEFAULT_DIAL_FORMAT
    dial_prefix: str = ""
    default_country_code: str = DEFAULT_COUNTRY_CODE
    provider_display_name: str = "SIP UP"

    @classmethod
    def from_env(cls) -> SipUpAriProviderConfig:
        from ..sip_up_settings_store import env_lookup

        raw_port = os.getenv(ASTERISK_PORT, "").strip()
        port = int(raw_port) if raw_port.isdigit() else 8088
        raw_timeout = os.getenv(ASTERISK_ORIGINATE_TIMEOUT_SECONDS, "").strip()
        timeout = int(raw_timeout) if raw_timeout.isdigit() else 25
        raw_format = (os.getenv(SIPUP_DIAL_FORMAT, "") or "").strip().lower()
        dial_format = raw_format if raw_format in DIAL_FORMATS else DEFAULT_DIAL_FORMAT
        return cls(
            host=os.getenv(ASTERISK_HOST),
            port=port,
            username=os.getenv(ASTERISK_USERNAME),
            password=os.getenv(ASTERISK_PASSWORD),
            context=os.getenv(ASTERISK_CONTEXT),
            endpoint=os.getenv(ASTERISK_ENDPOINT) or os.getenv(SIPUP_PJSIP_ENDPOINT),
            ari_prefix=os.getenv(ASTERISK_ARI_PREFIX, "/asterisk/ari"),
            ari_app=os.getenv(ASTERISK_ARI_APP, "ivr-bridge"),
            caller_id=env_lookup("ASTERISK_CALLER_ID") or env_lookup("SIPUP_OUTBOUND_CALLER_ID"),
            originate_timeout_seconds=max(5, min(timeout, 60)),
            dial_format=dial_format,
            dial_prefix=(os.getenv(SIPUP_DIAL_PREFIX, "") or "").strip(),
            default_country_code=(
                os.getenv(SIPUP_DEFAULT_COUNTRY_CODE, "") or DEFAULT_COUNTRY_CODE
            ).strip(),
            provider_display_name="SIP UP",
        )


class SipUpAriProvider(TelephonyProvider):
    """
    Production-oriented telephony provider for Asterisk (ARI/AMI placeholders).

    Implements :meth:`start_outbound` for compatibility with
    :class:`TelephonyProvider`. Use :meth:`start_call` when you have an ORM
    :class:`~app.models.CallSession` instance from the application layer.
    """

    def __init__(self, config: Optional[SipUpAriProviderConfig] = None) -> None:
        self._config = config or SipUpAriProviderConfig.from_env()

    def build_originate_request_payload(
        self,
        session_id: str,
        phone_number: str,
        *,
        organization: str = "",
        name: str = "",
        outbound_caller_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Build the JSON-serializable originate request body (ARI ``/channels`` style).

        Passwords are not included; use HTTP basic auth or TLS client certs at send time.
        """
        self._validate_config()
        endpoint = (self._config.endpoint or "").strip()
        normalized = self._normalized_destination(phone_number)
        target = self._build_dial_endpoint(normalized)
        return {
            "call_id": session_id,
            "phone_number": phone_number,
            "normalized_destination": normalized,
            "dial_format": self._config.dial_format,
            "name": (name or "").strip(),
            "organization": (organization or "").strip(),
            "context": (self._config.context or "").strip(),
            "ari_app": (self._config.ari_app or "").strip(),
            "caller_id": (
                (outbound_caller_id or "").strip()
                or (self._config.caller_id or "").strip()
            ),
            "timeout": str(self._config.originate_timeout_seconds),
            "endpoint": endpoint,
            "dial_endpoint": target,
            "ari": {
                "host": (self._config.host or "").strip(),
                "port": self._config.port,
                "username": (self._config.username or "").strip(),
            },
        }

    def _normalized_destination(self, phone_number: str) -> str:
        return normalize_phone_for_dial(
            phone_number,
            dial_format=self._config.dial_format,
            dial_prefix=self._config.dial_prefix,
            default_country_code=self._config.default_country_code,
        )

    def _build_dial_endpoint(self, destination: str) -> str:
        endpoint = (self._config.endpoint or "").strip()
        dest = str(destination or "").strip()
        if not endpoint:
            return dest
        if endpoint.startswith(("PJSIP/", "SIP/", "Local/")):
            return endpoint.format(phone_number=dest, destination=dest)
        return f"PJSIP/{dest}@{endpoint}"

    async def _send_originate_request(
        self,
        payload: dict[str, Any],
        emitter: CallEventEmitter,
    ) -> None:
        """
        Deliver the originate to Asterisk over ARI.
        """
        masked_input = mask_digits_in_text(str(payload.get("phone_number", "")))
        masked_dialed = mask_digits_in_text(str(payload.get("normalized_destination", "")))
        await asyncio.to_thread(self._post_ari_originate, payload)
        logger.info(
            "SipUpAriProvider originated call_id=%s input=%s dialed=%s dial_format=%s "
            "dial_endpoint=%s context=%s ari_app=%s",
            payload.get("call_id"),
            masked_input,
            masked_dialed,
            payload.get("dial_format"),
            payload.get("dial_endpoint"),
            payload.get("context"),
            payload.get("ari_app"),
        )
        brand = self._config.provider_display_name or "Asterisk"
        await emitter.emit(
            str(payload["call_id"]),
            CallEventType.DIAL_STARTED.value,
            (
                f"Real outbound call requested through {brand} "
                f"(input {masked_input}, dialed {masked_dialed} via "
                f"{payload.get('dial_format')})"
            ),
        )

    def _post_ari_originate(self, payload: dict[str, Any]) -> None:
        self._validate_config()
        host = (self._config.host or "").strip()
        prefix = "/" + self._config.ari_prefix.strip("/")
        base = f"http://{host}:{self._config.port}{prefix}/channels"
        query = parse.urlencode(
            {
                "endpoint": payload["dial_endpoint"],
                "app": payload["ari_app"],
                "appArgs": f"call_id={payload['call_id']}",
                "callerId": (payload.get("caller_id") or "").strip() or "IVR",
                "timeout": payload["timeout"],
            }
        )
        url = f"{base}?{query}"
        body = json.dumps(
            {
                "variables": {
                    "CALL_ID": str(payload["call_id"]),
                    "__CALL_ID": str(payload["call_id"]),
                    "IVR_RECIPIENT_NAME": str(payload.get("name") or ""),
                    "IVR_ORGANIZATION": str(payload.get("organization") or ""),
                }
            }
        ).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": self._basic_auth_header(),
            },
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                status_code = getattr(resp, "status", 200)
                if status_code >= 400:
                    raise SipUpAriConfigurationError(
                        f"SIP UP media originate failed with HTTP {status_code}"
                    )
                masked_input = mask_digits_in_text(str(payload.get("phone_number", "")))
                masked_dialed = mask_digits_in_text(str(payload.get("normalized_destination", "")))
                logger.info(
                    "SipUpAriProvider ARI originate OK http=%s call_id=%s input=%s dialed=%s dial_endpoint=%s "
                    "context=%s ari_app=%s",
                    status_code,
                    payload.get("call_id"),
                    masked_input,
                    masked_dialed,
                    payload.get("dial_endpoint"),
                    payload.get("context"),
                    payload.get("ari_app"),
                )
        except error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise SipUpAriConfigurationError(f"SIP UP media originate failed with HTTP {e.code}: {detail}") from e
        except error.URLError as e:
            raise SipUpAriConfigurationError(f"SIP UP media originate connection failed: {e.reason}") from e

    def _basic_auth_header(self) -> str:
        import base64

        raw = f"{self._config.username}:{self._config.password}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _validate_config(self) -> None:
        missing: list[str] = []
        checks: list[tuple[str, Optional[str]]] = [
            (ASTERISK_HOST, self._config.host),
            (ASTERISK_USERNAME, self._config.username),
            (ASTERISK_PASSWORD, self._config.password),
            (ASTERISK_CONTEXT, self._config.context),
            (ASTERISK_ENDPOINT, self._config.endpoint),
        ]

        for name, val in checks:
            if not val:
                missing.append(name)

        if missing:
            raise SipUpAriConfigurationError(
                "SipUpAriProvider: missing required environment variables: "
                + ", ".join(missing)
            )

    async def start_call(self, call_session: CallSession) -> None:
        """
        Originate an outbound call for the given session via ARI.
        """
        self._validate_config()
        masked_phone = mask_digits_in_text(call_session.phone_number)
        logger.info(
            "SipUpAriProvider.start_call (skeleton) session_id=%s phone=%s host=%s port=%s "
            "context=%s endpoint=%s",
            call_session.id,
            masked_phone,
            self._config.host,
            self._config.port,
            self._config.context,
            self._config.endpoint,
        )

    async def handle_call_answered(self, call_id: str) -> None:
        """
        Placeholder: invoked when Asterisk reports the callee answered.

        Intended implementation: notify application layer (e.g. emit
        ``CALL_ANSWERED``, advance simulator step) via shared event service.
        """
        self._validate_config()
        logger.info(
            "SipUpAriProvider.handle_call_answered (skeleton) call_id=%s",
            call_id,
        )

    async def handle_dtmf(self, call_id: str, digit: str) -> None:
        """
        Placeholder: single DTMF digit from ARI ``ChannelDtmfReceived`` (or AMI).

        Intended implementation: map digits to consent / verification flow or
        buffer until pound; never log full code sequences as plaintext.
        """
        self._validate_config()
        safe_digit = digit if digit in "0123456789*#" else "?"
        logger.info(
            "SipUpAriProvider.handle_dtmf (skeleton) call_id=%s digit=%s",
            call_id,
            safe_digit,
        )

    async def hangup(self, call_id: str) -> None:
        """
        Placeholder: hang up the Asterisk channel associated with ``call_id``.

        Intended implementation: ARI ``DELETE /ari/channels/{channelId}`` or AMI
        ``Hangup``, using the stored mapping from application ``call_id`` to
        channel id.
        """
        self._validate_config()
        logger.info("SipUpAriProvider.hangup (skeleton) call_id=%s", call_id)

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
        """
        :class:`TelephonyProvider` entry point.

        Validates configuration, builds the originate payload (see
        :meth:`build_originate_request_payload`), then calls :meth:`_send_originate_request`.
        Replace :meth:`_send_originate_request` with real ARI/AMI I/O when integrating.
        """
        payload = self.build_originate_request_payload(
            session_id,
            phone_number,
            organization=organization,
            name=name,
            outbound_caller_id=outbound_caller_id,
        )
        await self._send_originate_request(payload, emitter)
