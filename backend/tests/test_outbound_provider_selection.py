import asyncio

from app.services import outbound_simulation


def test_sip_up_ari_provider_mode_selects_asterisk_provider(monkeypatch):
    created = []

    class FakeSipUpAriProvider:
        def __init__(self, config=None):
            created.append("sip_up")

    class FakeMockProvider:
        def __init__(self):
            created.append("mock")

    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    monkeypatch.setattr(outbound_simulation, "SipUpAriProvider", FakeSipUpAriProvider)
    monkeypatch.setattr(outbound_simulation, "MockTelephonyProvider", FakeMockProvider)

    assert isinstance(outbound_simulation._provider_for_current_mode(), FakeSipUpAriProvider)
    assert created == ["sip_up"]


def test_mock_provider_mode_selects_mock_provider(monkeypatch):
    created = []

    class FakeSipUpAriProvider:
        def __init__(self):
            created.append("sip_up")

    class FakeMockProvider:
        def __init__(self):
            created.append("mock")

    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    monkeypatch.setattr(outbound_simulation, "SipUpAriProvider", FakeSipUpAriProvider)
    monkeypatch.setattr(outbound_simulation, "MockTelephonyProvider", FakeMockProvider)

    assert isinstance(outbound_simulation._provider_for_current_mode(), FakeMockProvider)
    assert created == ["mock"]


def _start_call(client, **extras):
    body = {
        "name": "Recipient",
        "university": "State U",
        "phone_number": "+15551112222",
        **extras,
    }
    r = client.post("/api/calls/start", json=body)
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


def test_call_initiated_message_in_asterisk_mode_is_sip_up(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    monkeypatch.setenv("SIPUP_SIP_HOST", "sip.example.test")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    call_id = _start_call(client, outbound_trunk="sip_up")
    events = client.get(f"/api/calls/{call_id}/events").json()
    init = [e for e in events if e["event_type"] == "CALL_INITIATED"]
    assert len(init) == 1
    msg = init[0]["message"]
    assert "mock" not in msg.lower()
    assert msg == "Real outbound call requested through SIP UP"


def test_mock_mode_start_succeeds_without_sipup_credentials(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    monkeypatch.delenv("SIPUP_SIP_HOST", raising=False)
    monkeypatch.delenv("SIPUP_SIP_DOMAIN", raising=False)
    monkeypatch.setenv("SIPUP_FALLBACK_REGISTRAR", "")
    monkeypatch.delenv("SIPUP_SIP_USERNAME", raising=False)
    monkeypatch.delenv("SIPUP_SIP_PASSWORD", raising=False)
    monkeypatch.delenv("SIPUP_PJSIP_ENDPOINT", raising=False)
    monkeypatch.delenv("SIPUP_OUTBOUND_CALLER_ID", raising=False)
    call_id = _start_call(client, outbound_trunk="sip_up")
    row = client.get(f"/api/calls/{call_id}").json()
    assert row.get("outbound_trunk") == "sip_up"


def test_call_initiated_message_in_mock_mode_is_mock(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    call_id = _start_call(client)
    events = client.get(f"/api/calls/{call_id}/events").json()
    init = [e for e in events if e["event_type"] == "CALL_INITIATED"]
    assert len(init) == 1
    assert init[0]["message"] == "Local mock telephony simulation initiated"


def test_call_start_in_asterisk_mode_does_not_emit_mock_lifecycle_events(
    client, monkeypatch
):
    """Asterisk mode must rely on real ARI events, not the mock provider's synthetic
    DIAL_STARTED/CALL_RINGING/ANSWERED/IVR_PROMPT sequence."""
    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    captured: list[str] = []

    class FakeMockProvider:
        async def start_outbound(self, *args, **kwargs):
            captured.append("mock-start_outbound-called")

    monkeypatch.setattr(outbound_simulation, "MockTelephonyProvider", FakeMockProvider)
    _start_call(client, outbound_trunk="sip_up")
    assert captured == [], (
        "MockTelephonyProvider.start_outbound must not run in asterisk mode"
    )


def test_call_initiated_message_for_sip_up_trunk(client, monkeypatch):
    monkeypatch.setenv("SIPUP_SIP_HOST", "sip.example.test")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    call_id = _start_call(client, outbound_trunk="sip_up")
    row = client.get(f"/api/calls/{call_id}").json()
    assert row.get("outbound_trunk") == "sip_up"
    events = client.get(f"/api/calls/{call_id}/events").json()
    init = [e for e in events if e["event_type"] == "CALL_INITIATED"]
    assert len(init) == 1
    assert init[0]["message"] == "Real outbound call requested through SIP UP"


def test_call_initiated_sip_up_accepts_sip_domain_without_host(client, monkeypatch):
    monkeypatch.delenv("SIPUP_SIP_HOST", raising=False)
    monkeypatch.setenv("SIPUP_SIP_DOMAIN", "sip.carrier.example")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    call_id = _start_call(client, outbound_trunk="sip_up")
    events = client.get(f"/api/calls/{call_id}/events").json()
    init = [e for e in events if e["event_type"] == "CALL_INITIATED"]
    assert len(init) == 1
    assert init[0]["message"] == "Real outbound call requested through SIP UP"


def test_call_initiated_sip_up_builtin_registrar_when_host_missing(client, monkeypatch):
    """Local development falls back to sip.sipup.org when registrar vars unset."""
    monkeypatch.delenv("SIPUP_SIP_HOST", raising=False)
    monkeypatch.delenv("SIPUP_SIP_DOMAIN", raising=False)
    monkeypatch.delenv("SIPUP_FALLBACK_REGISTRAR", raising=False)
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    call_id = _start_call(client, outbound_trunk="sip_up")
    events = client.get(f"/api/calls/{call_id}/events").json()
    init = [e for e in events if e["event_type"] == "CALL_INITIATED"]
    assert len(init) == 1
    assert init[0]["message"] == "Real outbound call requested through SIP UP"


def test_sip_up_start_without_sip_credentials_returns_503(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    monkeypatch.delenv("SIPUP_SIP_HOST", raising=False)
    monkeypatch.delenv("SIPUP_SIP_DOMAIN", raising=False)
    monkeypatch.setenv("SIPUP_FALLBACK_REGISTRAR", "")
    monkeypatch.delenv("SIPUP_SIP_USERNAME", raising=False)
    monkeypatch.delenv("SIPUP_SIP_PASSWORD", raising=False)
    monkeypatch.delenv("SIPUP_PJSIP_ENDPOINT", raising=False)
    monkeypatch.delenv("SIPUP_OUTBOUND_CALLER_ID", raising=False)
    r = client.post(
        "/api/calls/start",
        json={
            "name": "Recipient",
            "university": "State U",
            "phone_number": "+15551112222",
            "outbound_trunk": "sip_up",
        },
    )
    assert r.status_code == 503


def test_call_start_default_trunk_is_sip_up(client, monkeypatch):
    monkeypatch.setenv("SIPUP_SIP_HOST", "sip.example.test")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    call_id = _start_call(client)
    row = client.get(f"/api/calls/{call_id}").json()
    assert row.get("outbound_trunk") == "sip_up"


def test_resolve_outbound_sip_up_returns_sip_up_provider(monkeypatch):
    prov = outbound_simulation.resolve_outbound_provider(
        trunk_preference="sip_up", force_mock=False
    )
    assert isinstance(prov, outbound_simulation.SipUpTelephonyProvider)


def test_build_sip_up_ari_config_uses_sipup_trunk(monkeypatch):
    from app.services.telephony.sip_up_provider import (
        SipUpTelephonyConfig,
        build_sip_up_ari_config,
    )

    monkeypatch.setenv("ASTERISK_HOST", "127.0.0.1")
    monkeypatch.setenv("ASTERISK_USERNAME", "ari-user")
    monkeypatch.setenv("ASTERISK_PASSWORD", "secret")
    monkeypatch.setenv("ASTERISK_CONTEXT", "ivr-outbound")
    monkeypatch.setenv("ASTERISK_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    monkeypatch.setenv("SIPUP_DIAL_FORMAT", "e164_no_plus")
    monkeypatch.setenv("SIPUP_DEFAULT_COUNTRY_CODE", "216")

    sip = SipUpTelephonyConfig.from_env()
    ast = build_sip_up_ari_config(sip)
    assert ast.endpoint == "sip-up-trunk"
    assert ast.caller_id == "18006983228"
    assert ast.provider_display_name == "SIP UP"
    assert ast.dial_format == "e164_no_plus"
    assert ast.default_country_code == "216"


def test_sip_up_start_outbound_uses_ari_when_configured(monkeypatch):
    from app.services.telephony.sip_up_provider import SipUpTelephonyProvider

    captured: list[str] = []

    class FakeSipUpAriProvider:
        def __init__(self, config):
            captured.append(config.endpoint)

        async def start_outbound(self, *args, **kwargs):
            captured.append("start_outbound")

    monkeypatch.setenv("ASTERISK_HOST", "127.0.0.1")
    monkeypatch.setenv("ASTERISK_USERNAME", "ari-user")
    monkeypatch.setenv("ASTERISK_PASSWORD", "secret")
    monkeypatch.setenv("ASTERISK_CONTEXT", "ivr-outbound")
    monkeypatch.setenv("SIPUP_SIP_HOST", "sip.example.test")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")

    import app.services.telephony.sip_up_provider as sip_mod

    monkeypatch.setattr(sip_mod, "SipUpAriProvider", FakeSipUpAriProvider)

    class FakeEmitter:
        async def emit(self, *args, **kwargs):
            return None

    asyncio.run(
        SipUpTelephonyProvider().start_outbound(
            "sess-1",
            "+21652603967",
            FakeEmitter(),
            organization="State U",
            name="Recipient",
        )
    )
    assert captured == ["sip-up-trunk", "start_outbound"]


def test_start_call_stores_outbound_caller_id(client, monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    r = client.post(
        "/api/calls/start",
        json={
            "name": "Recipient",
            "university": "State U",
            "phone_number": "+21656340093",
            "outbound_trunk": "sip_up",
            "outbound_caller_id": "393888736444",
        },
    )
    assert r.status_code == 200, r.text
    call_id = r.json()["call_id"]
    row = client.get(f"/api/calls/{call_id}").json()
    assert row.get("outbound_caller_id") == "393888736444"
