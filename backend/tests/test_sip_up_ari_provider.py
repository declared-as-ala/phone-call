"""Unit tests for :class:`SipUpAriProvider` (no real Asterisk or network I/O)."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.exceptions import SipUpAriConfigurationError
from app.services.telephony.sip_up_ari_provider import (
    ASTERISK_CONTEXT,
    ASTERISK_ENDPOINT,
    ASTERISK_HOST,
    ASTERISK_PASSWORD,
    ASTERISK_USERNAME,
    SipUpAriProvider,
    SipUpAriProviderConfig,
)
from app.services.telephony.base import TelephonyProvider


def _full_config(**overrides) -> SipUpAriProviderConfig:
    base = dict(
        host="10.0.0.2",
        port=8089,
        username="ari-user",
        password="not-used-in-payload",
        context="ivr-outbound",
        endpoint="sip-up-trunk",
        dial_format="e164_plus",
    )
    base.update(overrides)
    return SipUpAriProviderConfig(**base)


def test_build_originate_request_payload_includes_required_fields():
    prov = SipUpAriProvider(_full_config())
    payload = prov.build_originate_request_payload(
        "550e8400-e29b-41d4-a716-446655440000",
        "+15551234567",
        organization=" State U ",
        name=" Pat Example ",
    )
    assert payload["call_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert payload["phone_number"] == "+15551234567"
    assert payload["name"] == "Pat Example"
    assert payload["organization"] == "State U"
    assert payload["context"] == "ivr-outbound"
    assert payload["ari_app"] == "ivr-bridge"
    assert payload["timeout"] == "25"
    assert payload["endpoint"] == "sip-up-trunk"
    assert payload["dial_endpoint"] == "PJSIP/+15551234567@sip-up-trunk"
    assert payload["ari"]["host"] == "10.0.0.2"
    assert payload["ari"]["port"] == 8089
    assert payload["ari"]["username"] == "ari-user"
    assert "password" not in payload
    assert "not-used-in-payload" not in str(payload)


@pytest.mark.parametrize(
    "field_name,missing_factory",
    [
        (ASTERISK_HOST, lambda c: SipUpAriProviderConfig(None, c.port, c.username, c.password, c.context, c.endpoint)),
        (ASTERISK_USERNAME, lambda c: SipUpAriProviderConfig(c.host, c.port, None, c.password, c.context, c.endpoint)),
        (ASTERISK_PASSWORD, lambda c: SipUpAriProviderConfig(c.host, c.port, c.username, None, c.context, c.endpoint)),
        (ASTERISK_CONTEXT, lambda c: SipUpAriProviderConfig(c.host, c.port, c.username, c.password, None, c.endpoint)),
        (ASTERISK_ENDPOINT, lambda c: SipUpAriProviderConfig(c.host, c.port, c.username, c.password, c.context, None)),
    ],
)
def test_missing_required_config_raises_clear_error(field_name, missing_factory):
    base = _full_config()
    bad = missing_factory(base)
    prov = SipUpAriProvider(bad)
    with pytest.raises(SipUpAriConfigurationError) as exc:
        prov.build_originate_request_payload("x", "+1")
    assert field_name in str(exc.value)
    assert "missing required environment" in str(exc.value).lower()


def test_start_outbound_builds_payload_and_passes_to_send(monkeypatch):
    captured: list[dict] = []

    async def fake_send(self, payload, emitter):
        captured.append(payload)
        await emitter.emit(payload["call_id"], "DIAL_STARTED", "ok")

    monkeypatch.setattr(SipUpAriProvider, "_send_originate_request", fake_send)

    emitter = AsyncMock()
    prov = SipUpAriProvider(_full_config())
    asyncio.run(
        prov.start_outbound(
            "call-uuid-1",
            "+15550001111",
            emitter,
            organization="Uni",
            name="Sam",
        )
    )
    assert len(captured) == 1
    p = captured[0]
    assert p["call_id"] == "call-uuid-1"
    assert p["phone_number"] == "+15550001111"
    assert p["name"] == "Sam"
    assert p["organization"] == "Uni"
    assert p["context"] == "ivr-outbound"
    assert p["endpoint"] == "sip-up-trunk"
    assert p["dial_endpoint"] == "PJSIP/+15550001111@sip-up-trunk"
    emitter.emit.assert_awaited_once()


def test_start_outbound_posts_ari_originate_without_leaking_password(monkeypatch):
    emitter = AsyncMock()
    prov = SipUpAriProvider(_full_config())

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.telephony.sip_up_ari_provider.request.urlopen", fake_urlopen)
    with patch("app.services.telephony.sip_up_ari_provider.logger.info") as log_info:
        asyncio.run(prov.start_outbound("id", "+15551112222", emitter, organization="O", name="N"))

    assert "http://10.0.0.2:8089/asterisk/ari/channels" in captured["url"]
    assert "endpoint=PJSIP%2F%2B15551112222%40sip-up-trunk" in captured["url"]
    assert "app=ivr-bridge" in captured["url"]
    assert "timeout=25" in captured["url"]
    assert "context=ivr-outbound" not in captured["url"]
    assert "Authorization" in captured["headers"]
    assert "not-used-in-payload" not in captured["url"]
    assert "not-used-in-payload" not in captured["data"]
    assert "not-used-in-payload" not in str(log_info.call_args_list)
    emitter.emit.assert_awaited_once()


def test_sip_up_ari_provider_matches_telephony_provider_signature():
    base_sig = inspect.signature(TelephonyProvider.start_outbound)
    conc_sig = inspect.signature(SipUpAriProvider.start_outbound)
    assert list(base_sig.parameters.keys()) == list(conc_sig.parameters.keys())
    assert issubclass(SipUpAriProvider, TelephonyProvider)


# --- Dial number normalization (SIPUP_DIAL_FORMAT) -----------------------


@pytest.mark.parametrize(
    "raw,fmt,expected",
    [
        ("+21652603967", "e164_plus", "+21652603967"),
        ("+21652603967", "e164_no_plus", "21652603967"),
        ("+21652603967", "international_00", "0021652603967"),
        ("+21652603967", "national", "52603967"),
        ("21652603967", "e164_plus", "+21652603967"),
        ("21652603967", "e164_no_plus", "21652603967"),
        ("21652603967", "international_00", "0021652603967"),
        ("21652603967", "national", "52603967"),
        ("0021652603967", "e164_no_plus", "21652603967"),
        ("00 216 52 603 967", "e164_no_plus", "21652603967"),
        ("+216 52 603 967", "e164_no_plus", "21652603967"),
        ("+216-52-603-967", "international_00", "0021652603967"),
        ("(216) 52 603 967", "national", "52603967"),
        ("+21652603967", "raw", "+21652603967"),
        ("56340093", "e164_no_plus", "21656340093"),
        ("056340093", "e164_no_plus", "21656340093"),
        ("21656340093", "e164_no_plus", "21656340093"),
    ],
)
def test_normalize_phone_for_dial_basic_formats(raw, fmt, expected):
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert (
        normalize_phone_for_dial(raw, dial_format=fmt, default_country_code="216")
        == expected
    )


def test_normalize_phone_for_dial_respects_prefix():
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert (
        normalize_phone_for_dial(
            "+21652603967", dial_format="e164_no_plus", dial_prefix="9"
        )
        == "921652603967"
    )


def test_normalize_phone_for_dial_unknown_format_falls_back_to_digits():
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert (
        normalize_phone_for_dial("+21652603967", dial_format="bogus")
        == "21652603967"
    )


def test_normalize_phone_for_dial_empty_input():
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert normalize_phone_for_dial("", dial_format="e164_no_plus") == ""
    assert normalize_phone_for_dial(None, dial_format="e164_no_plus") == ""  # type: ignore[arg-type]


def test_normalize_phone_for_dial_tunisia_already_has_cc_no_double_country():
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert normalize_phone_for_dial("21656340093", dial_format="e164_no_plus", default_country_code="216") == "21656340093"


def test_normalize_phone_for_dial_does_not_prepend_when_subscriber_too_long_for_heuristic():
    """Avoid mangling plausible bare NANP-style digits that lack ``+``."""
    from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial

    assert normalize_phone_for_dial("4155552677", dial_format="e164_no_plus", default_country_code="216") == "4155552677"


def test_sip_up_ari_provider_default_dial_format_is_national():
    """SIP UP uses national subscriber format by default."""
    from app.services.telephony.sip_up_ari_provider import (
        DEFAULT_DIAL_FORMAT,
        SipUpAriProviderConfig,
    )

    config = SipUpAriProviderConfig(
        host="h",
        port=8088,
        username="u",
        password="p",
        context="ivr-outbound",
        endpoint="sip-up-trunk",
    )
    assert DEFAULT_DIAL_FORMAT == "national"
    assert config.dial_format == "national"

    prov = SipUpAriProvider(config)
    payload = prov.build_originate_request_payload(
        "uuid-1", "+21652603967", organization="Org", name="Recipient"
    )
    assert payload["normalized_destination"] == "52603967"
    assert payload["dial_format"] == "national"
    assert payload["dial_endpoint"] == "PJSIP/52603967@sip-up-trunk"


def test_build_originate_matches_manual_sip_up_pjsip_digits():
    """``channel originate PJSIP/216…@sip-up-trunk …`` — no ``+`` in userpart."""
    prov = SipUpAriProvider(_full_config(dial_format="e164_no_plus", default_country_code="216"))

    bare = prov.build_originate_request_payload("u1", "56340093", organization="Org", name="Recipient")
    assert bare["normalized_destination"] == "21656340093"
    assert bare["dial_endpoint"] == "PJSIP/21656340093@sip-up-trunk"
    assert "+" not in bare["dial_endpoint"]

    with_plus = prov.build_originate_request_payload("u2", "+21656340093")
    assert with_plus["normalized_destination"] == "21656340093"
    assert with_plus["dial_endpoint"] == bare["dial_endpoint"]
def test_sip_up_ari_provider_e164_plus_format_keeps_plus_sign():
    prov = SipUpAriProvider(_full_config(dial_format="e164_plus"))
    payload = prov.build_originate_request_payload("uuid-2", "+21652603967")
    assert payload["normalized_destination"] == "+21652603967"
    assert payload["dial_endpoint"] == "PJSIP/+21652603967@sip-up-trunk"


def test_sip_up_ari_provider_international_00_format():
    prov = SipUpAriProvider(_full_config(dial_format="international_00"))
    payload = prov.build_originate_request_payload("uuid-3", "+21652603967")
    assert payload["normalized_destination"] == "0021652603967"
    assert payload["dial_endpoint"] == "PJSIP/0021652603967@sip-up-trunk"


def test_sip_up_ari_provider_national_format_strips_country_code():
    prov = SipUpAriProvider(
        _full_config(dial_format="national", default_country_code="216")
    )
    payload = prov.build_originate_request_payload("uuid-4", "+21652603967")
    assert payload["normalized_destination"] == "52603967"
    assert payload["dial_endpoint"] == "PJSIP/52603967@sip-up-trunk"


def test_sip_up_ari_provider_config_reads_dial_format_from_env(monkeypatch):
    from app.services.telephony.sip_up_ari_provider import SipUpAriProviderConfig

    monkeypatch.setenv("ASTERISK_HOST", "h")
    monkeypatch.setenv("ASTERISK_USERNAME", "u")
    monkeypatch.setenv("ASTERISK_PASSWORD", "p")
    monkeypatch.setenv("ASTERISK_CONTEXT", "ivr-outbound")
    monkeypatch.setenv("ASTERISK_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_DIAL_FORMAT", "international_00")
    monkeypatch.setenv("SIPUP_DIAL_PREFIX", "")
    monkeypatch.setenv("SIPUP_DEFAULT_COUNTRY_CODE", "216")

    cfg = SipUpAriProviderConfig.from_env()
    assert cfg.dial_format == "international_00"
    assert cfg.default_country_code == "216"

    monkeypatch.setenv("SIPUP_DIAL_FORMAT", "totally-bogus")
    cfg2 = SipUpAriProviderConfig.from_env()
    assert cfg2.dial_format == "national"  # falls back to default
