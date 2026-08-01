"""GET /api/system/runtime — non-secret runtime telephony provider info for the dashboard."""

from __future__ import annotations

import json


def test_runtime_endpoint_reports_asterisk_provider(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    monkeypatch.setenv("ASTERISK_HOST", "asterisk-test.local")
    monkeypatch.setenv("ASTERISK_PORT", "8088")
    monkeypatch.setenv("ASTERISK_USERNAME", "ari-user")
    monkeypatch.setenv("ASTERISK_PASSWORD", "ari-secret-not-logged")
    monkeypatch.setenv("ASTERISK_CONTEXT", "ivr-outbound")
    monkeypatch.setenv("ASTERISK_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("ASTERISK_ARI_APP", "ivr-bridge")
    monkeypatch.setenv("ASTERISK_CALLER_ID", "18009359935")
    monkeypatch.setenv(
        "BACKEND_TELEPHONY_EVENTS_URL", "http://127.0.0.1:8000/api/telephony/events"
    )

    r = client.get("/api/system/runtime")
    assert r.status_code == 200
    body = r.json()

    assert body["provider_mode"] == "sip_up"
    assert body["provider_label"] == "SIP UP"
    assert body["provider_class"] == "SipUpAriProvider"
    assert body["mock_scheduling_enabled"] is False
    assert body["voice_mode"] == "sip_up_call_audio"
    assert body["sip_up"]["host"] == "asterisk-test.local"
    assert body["sip_up"]["port"] == 8088
    assert body["sip_up"]["context"] == "ivr-outbound"
    assert body["sip_up"]["endpoint"] == "sip-up-trunk"
    assert body["sip_up"]["ari_app"] == "ivr-bridge"
    assert body["sip_up"]["username_present"] is True
    assert body["sip_up"]["password_present"] is True
    assert body["sip_up_ready"] is True
    assert body["backend_telephony_events_url"].endswith("/api/telephony/events")

    serialized = json.dumps(body)
    assert "ari-secret-not-logged" not in serialized
    assert "ari-user" not in serialized
    plain_secret_keys = [
        key
        for key in body["sip_up"].keys()
        if key.lower() in {"password", "username"} or key.lower().endswith("_password")
    ]
    assert plain_secret_keys == []


def test_runtime_endpoint_reports_mock_provider(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    monkeypatch.delenv("ASTERISK_HOST", raising=False)
    monkeypatch.delenv("ASTERISK_USERNAME", raising=False)
    monkeypatch.delenv("ASTERISK_PASSWORD", raising=False)
    monkeypatch.delenv("ASTERISK_CONTEXT", raising=False)
    monkeypatch.delenv("ASTERISK_ENDPOINT", raising=False)

    r = client.get("/api/system/runtime")
    assert r.status_code == 200
    body = r.json()
    assert body["provider_mode"] == "mock"
    assert body["provider_label"] == "Mock"
    assert body["provider_class"] == "MockTelephonyProvider"
    assert body["mock_scheduling_enabled"] is True
    assert body["voice_mode"] == "mock_simulation"
    assert body["sip_up_ready"] is False
    assert body["sip_up"]["host"] is None
    assert body["sip_up"]["password_present"] is False


def test_runtime_endpoint_requires_admin_auth(client):
    """Without a valid admin bearer token the endpoint rejects the call."""
    r = client.get(
        "/api/system/runtime",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401
