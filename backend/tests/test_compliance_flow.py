"""Compliance and audit flow tests (API + persistence)."""

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import CallEvent, SessionStatus, SimulatorStep


def _start_payload(phone: str = "+15550001111"):
    return {
        "name": "Test User",
        "university": "Example University",
        "phone_number": phone,
    }


def test_start_call(client):
    r = client.post("/api/calls/start", json=_start_payload())
    assert r.status_code == 200
    data = r.json()
    assert "call_id" in data
    assert len(data["call_id"]) == 36
    assert "demo_code" in data
    assert len(data["demo_code"]) == 6
    assert data["demo_code"].isdigit()


def _answered_press1(client, cid):
    assert client.post(f"/api/simulator/{cid}/answered").status_code == 200
    assert client.post(f"/api/simulator/{cid}/press", json={"digit": "1"}).status_code == 200


def test_consent_accepted_flow(client):
    r0 = client.post("/api/calls/start", json=_start_payload())
    cid = r0.json()["call_id"]

    r1 = client.post(f"/api/simulator/{cid}/answered")
    assert r1.status_code == 200
    assert r1.json()["step"] == SimulatorStep.CONSENT.value

    evs = client.get(f"/api/calls/{cid}/events").json()
    answered = next(e for e in evs if e["event_type"] == "CALL_ANSWERED")
    assert "Example University" in answered["message"]
    assert answered["actor_type"] == "user"

    r2 = client.post(f"/api/simulator/{cid}/press", json={"digit": "1"})
    assert r2.status_code == 200
    assert r2.json()["step"] == SimulatorStep.VERIFICATION_CODE.value


def test_consent_press_2_still_proceeds_to_otp_entry(client):
    r0 = client.post("/api/calls/start", json=_start_payload())
    cid = r0.json()["call_id"]
    client.post(f"/api/simulator/{cid}/answered")
    r2 = client.post(f"/api/simulator/{cid}/press", json={"digit": "2"})
    assert r2.status_code == 200
    assert r2.json().get("consent_digit") == "2"
    assert r2.json()["step"] == SimulatorStep.VERIFICATION_CODE.value

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value
    assert sess["status"] == SessionStatus.COLLECTING.value


def test_correct_code(client):
    r0 = client.post("/api/calls/start", json=_start_payload())
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]

    _answered_press1(client, cid)
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})
    assert r.status_code == 200
    assert r.json()["verified"] is None

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value

    r_approve = client.post(f"/api/calls/{cid}/admin/approve-verification")
    assert r_approve.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value


def test_admin_reject_then_approve(client):
    r0 = client.post("/api/calls/start", json=_start_payload())
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]

    _answered_press1(client, cid)

    r_wrong = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
    assert r_wrong.status_code == 200
    assert r_wrong.json()["pending_admin_verification"] is True

    r_reject = client.post(f"/api/calls/{cid}/admin/reject-verification")
    assert r_reject.status_code == 200
    assert r_reject.json().get("remaining_attempts") == 2

    r_ok = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})
    assert r_ok.status_code == 200
    assert r_ok.json()["pending_admin_verification"] is True
    r_approve = client.post(f"/api/calls/{cid}/admin/approve-verification")
    assert r_approve.status_code == 200

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value


def test_max_attempts_exceeded(client):
    r0 = client.post("/api/calls/start", json=_start_payload())
    data = r0.json()
    cid = data["call_id"]

    _answered_press1(client, cid)

    for _ in range(3):
        r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
        assert r.status_code == 200
        r_reject = client.post(f"/api/calls/{cid}/admin/reject-verification")
        assert r_reject.status_code == 200

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value
    assert sess["wrong_code_attempts"] == 3

    r4 = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
    assert r4.status_code == 400


def test_rate_limit_per_phone_per_day(client, monkeypatch, test_engine):
    monkeypatch.setattr("app.config.MAX_CALLS_PER_PHONE_PER_DAY", 2)

    assert client.post("/api/calls/start", json=_start_payload("+15559999001")).status_code == 200
    assert client.post("/api/calls/start", json=_start_payload("+15559999001")).status_code == 200
    r3 = client.post("/api/calls/start", json=_start_payload("+15559999001"))
    assert r3.status_code == 429
    assert "exceeded" in r3.json()["detail"].lower()


def test_audit_state_change_row(client, test_engine):
    r0 = client.post("/api/calls/start", json=_start_payload())
    cid = r0.json()["call_id"]
    client.post(f"/api/simulator/{cid}/answered")

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        rows = db.scalars(
            select(CallEvent).where(CallEvent.session_id == cid).order_by(CallEvent.id.asc())
        ).all()
        types = [r.event_type for r in rows]
        assert "AUDIT_STATE_CHANGE" in types
        audits = [r for r in rows if r.event_type == "AUDIT_STATE_CHANGE"]
        assert any("step" in a.message for a in audits)
        assert all(a.actor_type == "system" for a in audits)
    finally:
        db.close()
