"""API tests for SIP UP account settings."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import sip_up_settings_store as store


@pytest.fixture(autouse=True)
def isolated_settings_store(monkeypatch, tmp_path):
    path = tmp_path / "sip_up_account.json"
    monkeypatch.setattr(store, "_settings_path", lambda: path)
    monkeypatch.setattr(
        store,
        "_sync_infra_env",
        lambda _settings: {"ok": False, "message": "disabled in isolated test"},
    )
    yield


def test_get_sip_up_account_requires_admin(test_engine, monkeypatch):
    from app.database import get_db
    from app.main import app
    from sqlalchemy.orm import sessionmaker

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        r = c.get("/api/system/sip-up-account")
        assert r.status_code == 401
    app.dependency_overrides.clear()


def test_put_and_get_sip_up_account(client, monkeypatch):
    env_password = "".join(("test-only", "-sip-password"))
    replacement_password = "".join(("replacement", "-sip-password"))
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "10593")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", env_password)
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "28897028")

    r = client.put(
        "/api/system/sip-up-account",
        json={
            "label": "Ala account",
            "sip_username": "10593",
            "sip_password": replacement_password,
            "outbound_caller_id": "393888736444",
            "sip_domain": "sip.sipup.org",
            "sip_port": 5060,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["outbound_caller_id"] == "393888736444"
    assert body["label"] == "Ala account"
    assert "password" not in body

    g = client.get("/api/system/sip-up-account")
    assert g.status_code == 200
    row = g.json()
    assert row["outbound_caller_id"] == "393888736444"
    assert row["password_present"] is True
    assert "password" not in row

    runtime = client.get("/api/system/runtime").json()
    assert runtime["sip_up"]["caller_id"] == "393888736444"
    assert runtime["sip_up"]["account_label"] == "Ala account"
