"""Strict IVR ``CallStep`` transitions (see ``app.ivr_state``)."""

import asyncio

import pytest
from sqlalchemy.orm import sessionmaker

from app.exceptions import InvalidIvrTransition
from app.models import SessionStatus, SimulatorStep
from app.security import mask_digits_in_text
from app.services.call_service import call_service


def _run(coro):
    return asyncio.run(coro)


def test_cannot_enter_code_before_consent_service(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row, _ = call_service.create_call_session(
            db,
            name="Test",
            university="Uni",
            phone_number="+15550001111",
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "CALL_INITIATED",
                "Dial",
                new_status=SessionStatus.DIALING,
            )
        )
        with pytest.raises(InvalidIvrTransition):
            _run(
                call_service.add_event(
                    db,
                    row.id,
                    "SKIP",
                    "skip consent",
                    new_step=SimulatorStep.VERIFICATION_CODE.value,
                )
            )
    finally:
        db.close()


def test_cannot_press_one_after_declined_service(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row, _ = call_service.create_call_session(
            db,
            name="Test",
            university="Uni",
            phone_number="+15550002222",
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "CALL_INITIATED",
                "Dial",
                new_status=SessionStatus.DIALING,
            )
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "ANS",
                "consent",
                new_step=SimulatorStep.CONSENT.value,
            )
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "DECL",
                "declined",
                new_status=SessionStatus.COMPLETED,
                new_step=SimulatorStep.FINISHED.value,
                ivr_terminal="declined",
            )
        )
        with pytest.raises(InvalidIvrTransition):
            _run(
                call_service.add_event(
                    db,
                    row.id,
                    "BAD",
                    "press 1 after decline",
                    new_step=SimulatorStep.VERIFICATION_CODE.value,
                )
            )
    finally:
        db.close()


def test_cannot_mutate_final_session_service(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row, _ = call_service.create_call_session(
            db,
            name="Test",
            university="Uni",
            phone_number="+15550003333",
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "CALL_INITIATED",
                "Dial",
                new_status=SessionStatus.DIALING,
            )
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "ANS",
                "consent",
                new_step=SimulatorStep.CONSENT.value,
            )
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "ACC",
                "recipient pressed 1",
                new_step=SimulatorStep.VERIFICATION_CODE.value,
            )
        )
        _run(
            call_service.add_event(
                db,
                row.id,
                "DONE",
                "verified",
                new_status=SessionStatus.COMPLETED,
                new_step=SimulatorStep.FINISHED.value,
                ivr_terminal="verified",
            )
        )
        with pytest.raises(InvalidIvrTransition):
            _run(
                call_service.add_event(
                    db,
                    row.id,
                    "LATE",
                    "late consent",
                    new_step=SimulatorStep.CONSENT.value,
                )
            )
    finally:
        db.close()


def test_cannot_enter_code_before_consent_api(client):
    r0 = client.post(
        "/api/calls/start",
        json={
            "name": "A",
            "university": "U",
            "phone_number": "+15550004444",
        },
    )
    cid = r0.json()["call_id"]
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "123456"})
    assert r.status_code == 400


def test_press_2_then_enter_code_works(client):
    r0 = client.post(
        "/api/calls/start",
        json={
            "name": "A",
            "university": "U",
            "phone_number": "+15550005555",
        },
    )
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]
    client.post(f"/api/simulator/{cid}/answered")
    client.post(f"/api/simulator/{cid}/press", json={"digit": "2"})
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})
    assert r.status_code == 200
    assert r.json()["pending_admin_verification"] is True


def test_cannot_update_final_call_api(client):
    r0 = client.post(
        "/api/calls/start",
        json={
            "name": "A",
            "university": "U",
            "phone_number": "+15550006666",
        },
    )
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]
    client.post(f"/api/simulator/{cid}/answered")
    client.post(f"/api/simulator/{cid}/press", json={"digit": "1"})
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200
    assert client.post(f"/api/calls/{cid}/admin/approve-verification").status_code == 200

    r = client.post(f"/api/simulator/{cid}/answered")
    assert r.status_code == 400


def test_valid_flow_api(client):
    r0 = client.post(
        "/api/calls/start",
        json={
            "name": "A",
            "university": "U",
            "phone_number": "+15550007777",
        },
    )
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]
    assert client.post(f"/api/simulator/{cid}/answered").status_code == 200
    assert client.post(f"/api/simulator/{cid}/press", json={"digit": "1"}).status_code == 200
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})
    assert r.status_code == 200
    assert r.json()["verified"] is None
    assert r.json()["pending_admin_verification"] is True

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value
    assert sess["masked_entered_code"] == mask_digits_in_text(code)
    assert "entered_code" not in sess

    approved = client.post(f"/api/calls/{cid}/admin/approve-verification")
    assert approved.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value
    assert sess.get("ivr_outcome") == "verified"
