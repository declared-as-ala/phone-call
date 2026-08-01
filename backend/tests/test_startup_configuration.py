import pytest

from app import config


_PRODUCTION_ENV = {
    "DATABASE_URL": "sqlite:////opt/ivr-project/backend/ivr_verification.db",
    "JWT_SECRET_KEY": "jwt-secret",
    "DTMF_BUFFER_SECRET": "dtmf-secret",
    "TELEPHONY_WEBHOOK_SECRET": "webhook-secret",
    "CORS_ALLOWED_ORIGINS": "https://dashboard.example.com",
    "SIP_UP_SETTINGS_SECRET": "sip-settings-secret",
    "AUTH_COOKIE_SECURE": "1",
}


def _set_production(monkeypatch) -> None:
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "LOCAL_DEVELOPMENT", False)
    for name, value in _PRODUCTION_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("missing_name", tuple(_PRODUCTION_ENV))
def test_startup_fails_without_required_prod_env(monkeypatch, missing_name):
    _set_production(monkeypatch)
    monkeypatch.delenv(missing_name, raising=False)

    with pytest.raises(RuntimeError, match=missing_name):
        config.validate_auth_configuration()


def test_startup_accepts_complete_production_environment(monkeypatch):
    _set_production(monkeypatch)

    config.validate_auth_configuration()
