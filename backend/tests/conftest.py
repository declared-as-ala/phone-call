"""API tests use an in-memory SQLite engine patched onto ``app.database`` — no Alembic runs."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.database import Base

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_engine, monkeypatch):
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr("app.database.engine", test_engine)
    monkeypatch.setattr("app.main.engine", test_engine)
    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.services.speech_session_lookup.SessionLocal", TestSessionLocal)

    import app.routers.simulator as sim

    monkeypatch.setattr(sim, "SessionLocal", TestSessionLocal)

    import app.services.outbound_simulation as osim

    monkeypatch.setattr(osim, "SessionLocal", TestSessionLocal)

    monkeypatch.setattr("app.routers.calls.schedule_outbound_call", lambda *a, **k: None)

    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    monkeypatch.setenv("SIPUP_SIP_HOST", "sip.test.local")
    monkeypatch.setenv("SIPUP_SIP_USERNAME", "sipuser")
    monkeypatch.setenv("SIPUP_SIP_PASSWORD", "sippw")
    monkeypatch.setenv("SIPUP_PJSIP_ENDPOINT", "sip-up-trunk")
    monkeypatch.setenv("SIPUP_OUTBOUND_CALLER_ID", "18006983228")
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "test-luvvoice-token")
    monkeypatch.setenv("SIPUP_MIN_SECONDS_BETWEEN_CALLS", "0")
    monkeypatch.setenv("MAX_CALLS_PER_PHONE_PER_DAY", "0")

    from app.database import get_db
    from app.main import app
    from app.auth import create_access_token
    from app.models import AdminUser
    from app.security import hash_password

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        db = TestSessionLocal()
        try:
            admin = AdminUser(
                email="admin@example.com",
                password_hash=hash_password("StrongPassword123!"),
                full_name="Test Admin",
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            c.headers.update({"Authorization": f"Bearer {create_access_token(admin)}"})
        finally:
            db.close()
        yield c
    app.dependency_overrides.clear()


def simulator_answered_press1(client, call_id: str) -> None:
    """Answer + confirm consent (keypad 1) → student card entry step."""
    assert client.post(f"/api/simulator/{call_id}/answered").status_code == 200
    assert client.post(f"/api/simulator/{call_id}/press", json={"digit": "1"}).status_code == 200


def telephony_answered_press1(client, call_id: str) -> None:
    """Telephony ANSWERED + DTMF 1 → student card entry step."""
    assert (
        client.post(
            "/api/telephony/events",
            json={"provider": "mock", "call_id": call_id, "event_type": "ANSWERED"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/telephony/events",
            json={"provider": "mock", "call_id": call_id, "event_type": "DTMF", "digit": "1"},
        ).status_code
        == 200
    )
