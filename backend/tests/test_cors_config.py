import pytest

from app import config


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "https://dashboard.example.com, https://admin.example.com,https://dashboard.example.com",
    )

    assert config.get_cors_allowed_origins() == [
        "https://dashboard.example.com",
        "https://admin.example.com",
    ]


def test_cors_development_defaults_to_vite_ports(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setattr(config, "LOCAL_DEVELOPMENT", True)

    origins = config.get_cors_allowed_origins()

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5189" in origins


def test_cors_wildcard_is_rejected_with_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="cannot contain '\\*'"):
        config.get_cors_allowed_origins()


def test_production_requires_explicit_cors_origins(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")
    monkeypatch.setenv("DTMF_BUFFER_SECRET", "test-dtmf-secret")
    monkeypatch.setenv("TELEPHONY_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("SIP_UP_SETTINGS_SECRET", "test-sip-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "LOCAL_DEVELOPMENT", False)

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        config.validate_auth_configuration()


def test_production_requires_sip_settings_encryption_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")
    monkeypatch.setenv("DTMF_BUFFER_SECRET", "test-dtmf-secret")
    monkeypatch.setenv("TELEPHONY_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://dashboard.example.com")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
    monkeypatch.delenv("SIP_UP_SETTINGS_SECRET", raising=False)
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "LOCAL_DEVELOPMENT", False)

    with pytest.raises(RuntimeError, match="SIP_UP_SETTINGS_SECRET"):
        config.validate_auth_configuration()
