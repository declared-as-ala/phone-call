"""HMAC-SHA256 authentication for inbound telephony provider webhooks.

``POST /api/telephony/events`` is called directly by our own SIP UP ARI bridge
process (``app.services.sip_up_ari_bridge._post_backend_event``), not by an
end user's browser, so a shared symmetric secret (rather than the admin JWT)
is the right fit — the same pattern Stripe/GitHub use for webhook delivery.

Verification is enforced only when ``TELEPHONY_WEBHOOK_SECRET`` is configured.
When it is unset (the default in local development and in the test suite,
where ``conftest.py`` never sets it), requests are accepted unsigned — exactly
matching pre-existing behavior, so the local Asterisk lab dry run and the
existing webhook test suite keep working unchanged. ``config.validate_auth_configuration()``
refuses to start in staging/production without this secret set, which closes
the unauthenticated gap in every environment that matters.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status

from . import config

WEBHOOK_TIMESTAMP_HEADER = "X-Webhook-Timestamp"
WEBHOOK_SIGNATURE_HEADER = "X-Webhook-Signature"


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """HMAC-SHA256 over ``"{timestamp}." + raw_body``, hex-encoded."""
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    )
    return mac.hexdigest()


async def verify_telephony_webhook_signature(request: Request) -> None:
    """FastAPI dependency: reject unsigned/invalid/stale telephony webhook deliveries.

    No-op when ``TELEPHONY_WEBHOOK_SECRET`` is unset (see module docstring).
    """
    secret = (config.TELEPHONY_WEBHOOK_SECRET or "").strip()
    if not secret:
        return

    timestamp = request.headers.get(WEBHOOK_TIMESTAMP_HEADER)
    signature = request.headers.get(WEBHOOK_SIGNATURE_HEADER)
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature headers",
        )

    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook timestamp",
        ) from exc

    now = int(time.time())
    if abs(now - signed_at) > config.TELEPHONY_WEBHOOK_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook timestamp outside the allowed window (possible replay)",
        )

    raw_body = await request.body()
    expected = compute_signature(secret, timestamp, raw_body)
    provided = signature.strip().lower()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
