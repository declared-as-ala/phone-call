"""Production-safety checks: demo_code gating, hashed verification storage (no plaintext column)."""

from sqlalchemy.orm import sessionmaker

from app.models import CallSession
from app.services.call_service import call_service


def test_start_returns_demo_code_when_local_development_enabled(client, monkeypatch):
    monkeypatch.setattr("app.routers.calls.LOCAL_DEVELOPMENT", True)
    r = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550009001"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "demo_code" in data
    assert len(data["demo_code"]) == 6
    assert data["demo_code"].isdigit()


def test_start_omits_demo_code_when_local_development_disabled(client, monkeypatch):
    monkeypatch.setattr("app.routers.calls.LOCAL_DEVELOPMENT", False)
    r = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550009002"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "demo_code" not in data
    assert "call_id" in data


def test_app_env_staging_disables_local_development_flag(monkeypatch):
    import importlib

    import app.config as cfg

    try:
        monkeypatch.setenv("APP_ENV", "staging")
        importlib.reload(cfg)
        assert cfg.LOCAL_DEVELOPMENT is False

        monkeypatch.setenv("APP_ENV", "production")
        importlib.reload(cfg)
        assert cfg.LOCAL_DEVELOPMENT is False

        monkeypatch.setenv("APP_ENV", "development")
        importlib.reload(cfg)
        assert cfg.LOCAL_DEVELOPMENT is True
    finally:
        monkeypatch.setenv("APP_ENV", "development")
        importlib.reload(cfg)


def test_call_session_persists_verification_code_hash_not_plaintext(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row, plain = call_service.create_call_session(
            db,
            name="N",
            university="U",
            phone_number="+15550009003",
        )
        col_names = {c.key for c in CallSession.__table__.columns}
        assert "verification_code_hash" in col_names
        assert "verification_code" not in col_names
        assert row.verification_code_hash
        assert len(row.verification_code_hash) > 32
        assert row.verification_code_hash != plain
        db.refresh(row)
        assert row.verification_code_hash
    finally:
        db.close()
