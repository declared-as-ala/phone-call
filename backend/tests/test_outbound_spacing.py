"""SIP UP outbound spacing — active call guard and post-call cooldown."""

from datetime import timedelta

from sqlalchemy.orm import sessionmaker
from sqlalchemy import update

from app.exceptions import OutboundCallBlocked
from app.models import CallSession, SessionStatus
from app.services.call_service import call_service, enforce_outbound_call_spacing, utcnow


def _start(client, phone="+17373946144"):
    r = client.post(
        "/api/calls/start",
        json={
            "name": "Test",
            "university": "Org",
            "phone_number": phone,
            "outbound_trunk": "sip_up",
            "outbound_caller_id": "393888736444",
            "speech_engine": "free",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


def test_outbound_spacing_allows_when_idle(client):
    r = client.get("/api/calls/outbound-spacing")
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is True


def test_outbound_spacing_blocks_while_call_active(client, test_engine, monkeypatch):
    monkeypatch.setattr("app.config.SIPUP_MIN_SECONDS_BETWEEN_CALLS", 45)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        cid = _start(client)
        sess = db.get(CallSession, cid)
        sess.status = SessionStatus.DIALING.value
        sess.updated_at = utcnow()
        db.commit()

        status = call_service.outbound_spacing_status(db)
        assert status["allowed"] is False
        assert status["reason"] == "active_call"

        r = client.post(
            "/api/calls/start",
            json={
                "name": "Two",
                "university": "Org",
                "phone_number": "+17373946144",
                "outbound_trunk": "sip_up",
                "speech_engine": "free",
            },
        )
        assert r.status_code == 429
    finally:
        db.close()


def test_outbound_spacing_reconciles_stale_active_sessions(test_engine, monkeypatch):
    monkeypatch.setattr("app.config.SIPUP_ACTIVE_CALL_STALE_MINUTES", 20)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        sess = CallSession(
            name="Stale",
            university="Org",
            phone_number="+17373946144",
            verification_code_hash="x" * 60,
            status=SessionStatus.DIALING.value,
            simulator_step="consent",
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)
        db.execute(
            update(CallSession)
            .where(CallSession.id == sess.id)
            .values(updated_at=utcnow() - timedelta(minutes=30))
        )
        db.commit()

        status = call_service.outbound_spacing_status(db)
        assert status["allowed"] is True
        db.refresh(sess)
        assert sess.status == SessionStatus.FAILED.value
    finally:
        db.close()


def test_admin_end_call_unblocks_outbound_spacing(client, test_engine, monkeypatch):
    monkeypatch.setattr("app.config.SIPUP_MIN_SECONDS_BETWEEN_CALLS", 0)
    Session = sessionmaker(bind=test_engine)
    cid = _start(client)
    db = Session()
    try:
        status = call_service.outbound_spacing_status(db)
        assert status["allowed"] is False
        assert status["reason"] == "active_call"
    finally:
        db.close()

    r = client.post(f"/api/calls/{cid}/admin/end-call")
    assert r.status_code == 200, r.text

    r2 = client.get("/api/calls/outbound-spacing")
    assert r2.status_code == 200
    assert r2.json()["allowed"] is True


def test_outbound_spacing_cooldown_after_terminal_call(test_engine, monkeypatch):
    monkeypatch.setattr("app.config.SIPUP_MIN_SECONDS_BETWEEN_CALLS", 45)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        sess = CallSession(
            name="Done",
            university="Org",
            phone_number="+17373946144",
            verification_code_hash="x" * 60,
            status=SessionStatus.COMPLETED.value,
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)

        with __import__("pytest").raises(OutboundCallBlocked) as exc:
            enforce_outbound_call_spacing(db)
        assert exc.value.wait_seconds > 0

        status = call_service.outbound_spacing_status(db)
        assert status["allowed"] is False
        assert status["reason"] == "cooldown"

        sess.updated_at = utcnow() - timedelta(seconds=60)
        db.commit()
        assert call_service.outbound_spacing_status(db)["allowed"] is True
    finally:
        db.close()
