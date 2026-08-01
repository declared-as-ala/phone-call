from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import CallEvent, SessionStatus, SimulatorStep
from app.security import mask_digits_in_text


def _start_and_consent(client, phone="+15550006601"):
    r0 = client.post(
        "/api/calls/start",
        json={"name": "Admin Review", "university": "Internal U", "phone_number": phone},
    )
    assert r0.status_code == 200
    cid, code = r0.json()["call_id"], r0.json()["demo_code"]
    assert client.post(f"/api/simulator/{cid}/answered").status_code == 200
    assert client.post(f"/api/simulator/{cid}/press", json={"digit": "1"}).status_code == 200
    return cid, code


def test_entering_valid_otp_moves_to_pending_admin_not_success(client):
    cid, code = _start_and_consent(client)

    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})

    assert r.status_code == 200
    assert r.json()["verified"] is None
    assert r.json()["pending_admin_verification"] is True
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value
    assert len(code) == 6
    assert sess["masked_entered_code"] == mask_digits_in_text(code)
    assert "entered_code" not in sess

    evs = client.get(f"/api/calls/{cid}/events").json()
    assert any(e["event_type"] == "DIGITS_RECEIVED" for e in evs)
    assert any(e["event_type"] == "PENDING_ADMIN_VERIFICATION" for e in evs)
    assert not any(e["event_type"] == "VERIFICATION_SUCCESS" for e in evs)
    dr = next(e for e in evs if e["event_type"] == "DIGITS_RECEIVED")
    assert code not in dr["message"]
    assert mask_digits_in_text(code) in dr["message"]


def test_five_digits_not_enough(client):
    cid, code = _start_and_consent(client)
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code[:5]})

    assert r.status_code == 400


def test_admin_can_fetch_full_entered_code_after_approval(client):
    cid, code = _start_and_consent(client)
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200

    r = client.get(f"/api/calls/{cid}/admin/entered-code")

    assert r.status_code == 200
    assert r.json()["entered_code"] == code
    assert r.json()["masked_entered_code"] == mask_digits_in_text(code)
    dr = next(e for e in client.get(f"/api/calls/{cid}/events").json() if e["event_type"] == "DIGITS_RECEIVED")
    assert code not in dr["message"]
    assert mask_digits_in_text(code) in dr["message"]

    # Revealing the plaintext code is audit-logged against the calling admin.
    reveal_events = [
        e
        for e in client.get(f"/api/calls/{cid}/events").json()
        if e["event_type"] == "ADMIN_ENTERED_CODE_VIEWED"
    ]
    assert reveal_events
    assert code not in reveal_events[0]["message"]

    assert client.post(f"/api/calls/{cid}/admin/approve-verification").status_code == 200
    after_approval = client.get(f"/api/calls/{cid}/admin/entered-code")
    assert after_approval.status_code == 200
    assert after_approval.json()["entered_code"] == code


def test_admin_approve_completes_call_and_uses_admin_actor(client):
    cid, code = _start_and_consent(client)
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200

    r = client.post(f"/api/calls/{cid}/admin/approve-verification")

    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value
    assert sess["simulator_step"] == SimulatorStep.FINISHED.value
    assert sess["ivr_outcome"] == "verified"

    evs = client.get(f"/api/calls/{cid}/events").json()
    approved = next(e for e in evs if e["event_type"] == "ADMIN_VERIFICATION_APPROVED")
    success = next(e for e in evs if e["event_type"] == "VERIFICATION_SUCCESS")
    assert approved["actor_type"] == "admin"
    assert success["actor_type"] == "admin"


def test_admin_reject_allows_retry_when_attempts_remain(client):
    cid, _ = _start_and_consent(client)
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"}).status_code == 200

    r = client.post(f"/api/calls/{cid}/admin/reject-verification")

    assert r.status_code == 200
    assert r.json()["remaining_attempts"] == 2
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COLLECTING.value
    assert sess["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value
    assert sess["wrong_code_attempts"] == 1
    assert sess["masked_entered_code"] is None
    assert sess.get("entered_code") is None


def test_admin_reject_after_max_attempts_fails_call(client):
    cid, _ = _start_and_consent(client)

    for i in range(3):
        code = f"{i:06d}"
        assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200
        r = client.post(f"/api/calls/{cid}/admin/reject-verification")
        assert r.status_code == 200

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value
    assert sess["simulator_step"] == SimulatorStep.FINISHED.value
    assert sess["wrong_code_attempts"] == 3
    assert sess["ivr_outcome"] == "failed"


def test_admin_approve_reject_forbidden_from_wrong_states(client):
    cid, _ = _start_and_consent(client)

    r_approve = client.post(f"/api/calls/{cid}/admin/approve-verification")
    r_reject = client.post(f"/api/calls/{cid}/admin/reject-verification")

    assert r_approve.status_code == 400
    assert r_reject.status_code == 400


def test_admin_reject_actor_and_code_masked_in_persisted_events(client, test_engine):
    cid, code = _start_and_consent(client)
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200
    assert client.post(f"/api/calls/{cid}/admin/reject-verification").status_code == 200

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        rows = db.scalars(select(CallEvent).where(CallEvent.session_id == cid)).all()
        rejected = next(e for e in rows if e.event_type == "ADMIN_VERIFICATION_REJECTED")
        assert rejected.actor_type == "admin"
        digits_received = [e for e in rows if e.event_type == "DIGITS_RECEIVED"]
        assert digits_received
        assert not any(code in e.message for e in digits_received)
        assert any(mask_digits_in_text(code) in e.message for e in digits_received)
    finally:
        db.close()
