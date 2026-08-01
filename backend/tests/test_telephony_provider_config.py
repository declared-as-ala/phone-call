"""Cutover guard: non-mock telephony providers require credentials (startup validation)."""

import pytest

from app.telephony_provider_config import (
    validate_telephony_provider_configuration_on_startup,
)


def test_mock_provider_requires_no_client_env(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    monkeypatch.delenv("CLIENT_PROVIDER_BASE_URL", raising=False)
    monkeypatch.delenv("CLIENT_PROVIDER_API_KEY", raising=False)
    assert validate_telephony_provider_configuration_on_startup() == "mock"


def test_client_api_requires_base_url(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "client_api")
    monkeypatch.delenv("CLIENT_PROVIDER_BASE_URL", raising=False)
    monkeypatch.setenv("CLIENT_PROVIDER_API_KEY", "secret-key-not-logged")
    with pytest.raises(RuntimeError, match="CLIENT_PROVIDER_BASE_URL"):
        validate_telephony_provider_configuration_on_startup()


def test_client_api_requires_api_key(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "client_api")
    monkeypatch.setenv("CLIENT_PROVIDER_BASE_URL", "https://api.example.test")
    monkeypatch.delenv("CLIENT_PROVIDER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CLIENT_PROVIDER_API_KEY"):
        validate_telephony_provider_configuration_on_startup()


def test_client_api_passes_with_base_and_key(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "client_api")
    monkeypatch.setenv("CLIENT_PROVIDER_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("CLIENT_PROVIDER_API_KEY", "test-api-key")
    assert validate_telephony_provider_configuration_on_startup() == "client_api"


def test_asterisk_requires_core_env(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "sip_up")
    monkeypatch.delenv("ASTERISK_HOST", raising=False)
    with pytest.raises(RuntimeError, match="ASTERISK"):
        validate_telephony_provider_configuration_on_startup()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "carrier_xyz")
    with pytest.raises(RuntimeError, match="Unknown TELEPHONY_PROVIDER"):
        validate_telephony_provider_configuration_on_startup()
