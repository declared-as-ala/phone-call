"""
Regression tests for release / audit checklist items.

Covers: no plaintext codes in DB, masked DTMF in persisted logs, consent gating,
attempt caps, rate limit, actor_type on events, audit rows, simulator smoke,
stable telephony interface, and Asterisk-style event replay.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Optional

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.exceptions import InvalidIvrTransition
from app.models import CallEvent, CallSession, EventActor, SessionStatus, SimulatorStep
from app.security import mask_digits_in_text
from app.services import outbound_simulation as osim
from app.services.call_service import MAX_VERIFICATION_ATTEMPTS, call_service
from app.services.telephony.base import TelephonyProvider


def _tel(call_id: str, event_type: str, digit: Optional[str] = None) -> dict[str, Any]:
    p: dict[str, Any] = {"provider": "mock", "call_id": call_id, "event_type": event_type}
    if digit is not None:
        p["digit"] = digit
    return p


def test_no_plaintext_verification_column_on_session_model():
    names = {c.name for c in CallSession.__table__.columns}
    assert "verification_code_hash" in names
    assert "verification_code" not in names
    assert "demo_code" not in names


def test_digits_received_events_never_store_full_code_in_message(client):
    """Persisted/broadcast DIGITS_RECEIVED must mask the entered code (last 2 digits only).

    The full code remains available exclusively via the dedicated, audited
    GET /api/calls/{id}/admin/entered-code endpoint (see test_admin_verification.py).
    """
    r0 = client.post(
        "/api/calls/start",
        json={"name": "C", "university": "U", "phone_number": "+15550007001"},
    )
    cid, code = r0.json()["call_id"], r0.json()["demo_code"]
    client.post("/api/telephony/events", json=_tel(cid, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid, "DTMF", "1"))
    for d in code:
        client.post("/api/telephony/events", json=_tel(cid, "DTMF", d))
    client.post("/api/telephony/events", json=_tel(cid, "DTMF", "#"))

    evs = client.get(f"/api/calls/{cid}/events").json()
    dr = [e for e in evs if e["event_type"] == "DIGITS_RECEIVED"]
    assert dr, "expected DIGITS_RECEIVED from OTP DTMF buffer submit"
    msg = dr[0]["message"]
    assert code not in msg
    assert mask_digits_in_text(code) in msg

    # The general session view never carries the plaintext code either.
    sess = client.get(f"/api/calls/{cid}").json()
    assert "entered_code" not in sess
    assert code not in (sess.get("masked_entered_code") or "")


def test_consent_required_before_verification_service(test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row, _ = call_service.create_call_session(
            db, name="x", university="y", phone_number="+15550007002"
        )
        asyncio.run(
            call_service.add_event(
                db,
                row.id,
                "CALL_INITIATED",
                "dial",
                new_status=SessionStatus.DIALING,
            )
        )
        with pytest.raises(InvalidIvrTransition):
            asyncio.run(
                call_service.add_event(
                    db,
                    row.id,
                    "SKIP",
                    "skip",
                    new_step=SimulatorStep.VERIFICATION_CODE.value,
                )
            )
    finally:
        db.close()


def test_max_three_attempts_simulator_and_webhook(client):
    r0 = client.post(
        "/api/calls/start",
        json={"name": "C", "university": "U", "phone_number": "+15550007003"},
    )
    cid = r0.json()["call_id"]
    client.post(f"/api/simulator/{cid}/answered")
    client.post(f"/api/simulator/{cid}/press", json={"digit": "1"})
    for _ in range(MAX_VERIFICATION_ATTEMPTS):
        r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
        assert r.status_code == 200
        r_reject = client.post(f"/api/calls/{cid}/admin/reject-verification")
        assert r_reject.status_code == 200
    r4 = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
    assert r4.status_code == 400

    r1 = client.post(
        "/api/calls/start",
        json={"name": "C", "university": "U", "phone_number": "+15550007004"},
    )
    cid2 = r1.json()["call_id"]
    client.post("/api/telephony/events", json=_tel(cid2, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid2, "DTMF", "1"))
    for _ in range(MAX_VERIFICATION_ATTEMPTS):
        for d in "000000":
            assert client.post("/api/telephony/events", json=_tel(cid2, "DTMF", d)).status_code == 200
        r_reject = client.post(f"/api/calls/{cid2}/admin/reject-verification")
        assert r_reject.status_code == 200
    sess = client.get(f"/api/calls/{cid2}").json()
    assert sess["status"] == SessionStatus.FAILED.value
    r_bad = client.post("/api/telephony/events", json=_tel(cid2, "DTMF", "0"))
    assert r_bad.status_code == 200
    assert r_bad.json()["noop"] is True


def test_daily_phone_rate_limit(client, monkeypatch):
    monkeypatch.setattr("app.config.MAX_CALLS_PER_PHONE_PER_DAY", 2)
    p = {"name": "R", "university": "U", "phone_number": "+15550007005"}
    assert client.post("/api/calls/start", json=p).status_code == 200
    assert client.post("/api/calls/start", json=p).status_code == 200
    r3 = client.post("/api/calls/start", json=p)
    assert r3.status_code == 429


def test_all_persisted_events_have_actor_type(client, test_engine):
    r0 = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550007006"},
    )
    cid = r0.json()["call_id"]
    client.post(f"/api/simulator/{cid}/answered")

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        rows = db.scalars(select(CallEvent).where(CallEvent.session_id == cid)).all()
        assert rows
        allowed = {a.value for a in EventActor}
        for ev in rows:
            assert ev.actor_type in allowed
            assert ev.actor_type is not None and ev.actor_type != ""
    finally:
        db.close()


def test_audit_state_change_on_status_or_step_transition(client, test_engine):
    r0 = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550007007"},
    )
    cid = r0.json()["call_id"]
    client.post(f"/api/simulator/{cid}/answered")

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        audits = db.scalars(
            select(CallEvent).where(
                CallEvent.session_id == cid,
                CallEvent.event_type == "AUDIT_STATE_CHANGE",
            )
        ).all()
        assert audits
    finally:
        db.close()


def test_simulator_answered_press_enter_code_happy_path(client):
    r0 = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550007008"},
    )
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]
    assert client.post(f"/api/simulator/{cid}/answered").status_code == 200
    assert client.post(f"/api/simulator/{cid}/press", json={"digit": "1"}).status_code == 200
    r = client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})
    assert r.status_code == 200
    assert r.json()["verified"] is None
    assert r.json()["pending_admin_verification"] is True
    r_approve = client.post(f"/api/calls/{cid}/admin/approve-verification")
    assert r_approve.status_code == 200


def test_telephony_provider_start_outbound_signature_stable():
    sig = inspect.signature(TelephonyProvider.start_outbound)
    params = list(sig.parameters.keys())
    assert params[:4] == ["self", "session_id", "phone_number", "emitter"]
    assert "organization" in sig.parameters
    assert "name" in sig.parameters


def test_replay_asterisk_style_lifecycle_events(test_engine):
    """Replay the same event types the mock emitter uses (SIP UP bridge can mirror this)."""

    async def _run():
        Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        db = Session()
        try:
            row, _ = call_service.create_call_session(
                db, name="Replay", university="Uni", phone_number="+15550007009"
            )
            await call_service.add_event(
                db,
                row.id,
                "CALL_INITIATED",
                "Outbound initiated",
                new_status=SessionStatus.DIALING,
            )
            sequence = [
                ("DIAL_STARTED", "PJSIP/... dial"),
                ("CALL_RINGING", "Ringing"),
                ("ANSWERED", "Channel answered"),
                ("IVR_PROMPT", "Compliance prompt played"),
            ]
            for event_type, message in sequence:
                st = osim._EVENT_STATUS.get(event_type)
                await call_service.add_event(
                    db,
                    row.id,
                    event_type,
                    message,
                    new_status=st,
                    actor=EventActor.TELEPHONY_PROVIDER,
                )
            db.refresh(row)
            assert row.status == SessionStatus.COLLECTING.value
            types = [
                e.event_type
                for e in db.scalars(
                    select(CallEvent).where(CallEvent.session_id == row.id).order_by(CallEvent.id)
                ).all()
            ]
            for et in ("DIAL_STARTED", "CALL_RINGING", "ANSWERED", "IVR_PROMPT"):
                assert et in types
        finally:
            db.close()

    asyncio.run(_run())
