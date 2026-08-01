from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import CallEvent, CallSession, TelephonyEventReceipt, VerificationAttempt


def test_delete_call_removes_local_demo_history(client, test_engine):
    r = client.post(
        "/api/calls/start",
        json={"name": "History User", "university": "Demo University", "phone_number": "+21626565725"},
    )
    assert r.status_code == 200
    call_id = r.json()["call_id"]
    assert client.post(f"/api/simulator/{call_id}/answered").status_code == 200
    assert client.post(f"/api/simulator/{call_id}/press", json={"digit": "1"}).status_code == 200
    code_response = client.post(
        f"/api/simulator/{call_id}/enter-code",
        json={"digits": r.json()["demo_code"]},
    )
    assert code_response.status_code == 200
    assert client.post(f"/api/calls/{call_id}/admin/reject-verification").status_code == 200

    deleted = client.delete(f"/api/calls/{call_id}")

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/calls/{call_id}").status_code == 404

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        assert db.get(CallSession, call_id) is None
        assert db.scalars(select(CallEvent).where(CallEvent.session_id == call_id)).all() == []
        assert db.scalars(select(VerificationAttempt).where(VerificationAttempt.session_id == call_id)).all() == []
        assert db.scalars(select(TelephonyEventReceipt).where(TelephonyEventReceipt.call_id == call_id)).all() == []
    finally:
        db.close()


def test_delete_call_forbidden_outside_local_development(client, monkeypatch):
    r = client.post(
        "/api/calls/start",
        json={"name": "Protected User", "university": "Demo University", "phone_number": "+21626565725"},
    )
    assert r.status_code == 200
    call_id = r.json()["call_id"]
    monkeypatch.setattr("app.routers.calls.LOCAL_DEVELOPMENT", False)

    deleted = client.delete(f"/api/calls/{call_id}")

    assert deleted.status_code == 403
