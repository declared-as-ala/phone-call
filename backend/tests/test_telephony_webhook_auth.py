"""Tests for HMAC signing of POST /api/telephony/events (app.webhook_security).

The shared ``client`` fixture never sets ``TELEPHONY_WEBHOOK_SECRET``, so the rest of the
test suite (test_telephony_webhook.py, test_telephony_idempotency.py, etc.) continues to post
unsigned requests and keeps passing unchanged — this file is the only place the secret is
turned on, to verify the *enforced* path without touching every existing webhook test.
"""

from __future__ import annotations

import time

from app.webhook_security import (
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    compute_signature,
)

TEST_SECRET = "test-webhook-secret-do-not-use-in-prod"


def _start_call(client) -> str:
    r = client.post(
        "/api/calls/start",
        json={"name": "Sig", "university": "U", "phone_number": "+15550009001"},
    )
    assert r.status_code == 200
    return r.json()["call_id"]


def _signed_headers(secret: str, body: bytes, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    return {
        WEBHOOK_TIMESTAMP_HEADER: ts,
        WEBHOOK_SIGNATURE_HEADER: compute_signature(secret, ts, body),
    }


def test_webhook_unsigned_allowed_when_secret_not_configured(client):
    """Baseline: with no TELEPHONY_WEBHOOK_SECRET configured, behavior is unchanged (dev/test default)."""
    call_id = _start_call(client)
    r = client.post(
        "/api/telephony/events",
        json={"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"},
    )
    assert r.status_code == 200


def test_webhook_rejected_when_signature_missing(client, monkeypatch):
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    call_id = _start_call(client)
    r = client.post(
        "/api/telephony/events",
        json={"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"},
    )
    assert r.status_code == 401


def test_webhook_accepted_with_valid_signature(client, monkeypatch):
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    call_id = _start_call(client)
    payload = {"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"}
    body = __import__("json").dumps(payload).encode("utf-8")
    r = client.post(
        "/api/telephony/events",
        content=body,
        headers={"Content-Type": "application/json", **_signed_headers(TEST_SECRET, body)},
    )
    assert r.status_code == 200


def test_webhook_rejected_with_invalid_signature(client, monkeypatch):
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    call_id = _start_call(client)
    payload = {"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"}
    body = __import__("json").dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    r = client.post(
        "/api/telephony/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            WEBHOOK_TIMESTAMP_HEADER: ts,
            WEBHOOK_SIGNATURE_HEADER: "0" * 64,
        },
    )
    assert r.status_code == 401


def test_webhook_rejected_with_wrong_secret(client, monkeypatch):
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    call_id = _start_call(client)
    payload = {"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"}
    body = __import__("json").dumps(payload).encode("utf-8")
    r = client.post(
        "/api/telephony/events",
        content=body,
        headers={"Content-Type": "application/json", **_signed_headers("wrong-secret", body)},
    )
    assert r.status_code == 401


def test_webhook_rejected_with_stale_timestamp(client, monkeypatch):
    """Replay protection: a validly-signed request outside the tolerance window is rejected."""
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_TOLERANCE_SECONDS", 300)
    call_id = _start_call(client)
    payload = {"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"}
    body = __import__("json").dumps(payload).encode("utf-8")
    stale_ts = str(int(time.time()) - 3600)  # 1 hour old — well outside a 5-minute window
    r = client.post(
        "/api/telephony/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            **_signed_headers(TEST_SECRET, body, timestamp=stale_ts),
        },
    )
    assert r.status_code == 401


def test_webhook_replay_of_captured_signed_request_is_rejected_once_stale(client, monkeypatch):
    """A validly-signed request captured off the wire cannot be replayed once its
    timestamp falls outside the tolerance window — even with a correct signature.

    Deliberately avoids a real ``time.sleep()`` (flaky under load in a shared test
    process); the "capture" is simulated by signing with a timestamp already outside
    the configured tolerance, which exercises the exact same check.
    """
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setattr("app.config.TELEPHONY_WEBHOOK_TOLERANCE_SECONDS", 60)
    call_id = _start_call(client)
    payload = {"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"}
    body = __import__("json").dumps(payload).encode("utf-8")

    captured_ts = str(int(time.time()) - 90)  # "signed" 90s ago; tolerance is 60s
    headers = {
        "Content-Type": "application/json",
        **_signed_headers(TEST_SECRET, body, timestamp=captured_ts),
    }
    replay = client.post("/api/telephony/events", content=body, headers=headers)
    assert replay.status_code == 401
