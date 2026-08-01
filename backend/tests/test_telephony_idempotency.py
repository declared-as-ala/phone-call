"""Idempotency for ``POST /api/telephony/events`` via ``provider_event_id``."""

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import CallSession, SessionStatus, SimulatorStep, TelephonyEventReceipt


def _payload(**kwargs):
    base = {
        "provider": "mock",
        "call_id": kwargs.pop("call_id"),
        "event_type": kwargs.pop("event_type"),
    }
    for k in ("provider_call_id", "provider_event_id", "digit", "raw_payload"):
        if k in kwargs:
            base[k] = kwargs.pop(k)
    assert not kwargs, kwargs
    return base


def _start(client):
    r = client.post(
        "/api/calls/start",
        json={"name": "I", "university": "U", "phone_number": "+15550008001"},
    )
    assert r.status_code == 200
    return r.json()["call_id"]


def test_duplicate_answered_ignored(client, test_engine):
    cid = _start(client)
    p = _payload(call_id=cid, event_type="ANSWERED", provider_event_id="evt-answered-1")
    r1 = client.post("/api/telephony/events", json=p)
    assert r1.status_code == 200
    assert r1.json().get("status") != "duplicate_ignored"
    assert r1.json()["session_status"] is not None

    r2 = client.post("/api/telephony/events", json=p)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        n = db.scalar(
            select(TelephonyEventReceipt.id).where(
                TelephonyEventReceipt.provider_event_id == "evt-answered-1"
            )
        )
        assert n is not None
        ev_ans = sum(
            1
            for e in client.get(f"/api/calls/{cid}/events").json()
            if e["event_type"] == "CALL_ANSWERED"
        )
        assert ev_ans == 1
    finally:
        db.close()


def test_duplicate_dtmf_digit_not_appended_twice(client, test_engine):
    cid = _start(client)
    client.post("/api/telephony/events", json=_payload(call_id=cid, event_type="ANSWERED"))
    client.post(
        "/api/telephony/events",
        json=_payload(call_id=cid, event_type="DTMF", digit="1"),
    )
    p = _payload(
        call_id=cid,
        event_type="DTMF",
        digit="3",
        provider_event_id="dtmf-digit-3",
    )
    r1 = client.post("/api/telephony/events", json=p)
    assert r1.status_code == 200
    assert r1.json()["digits_collected"] == 1

    r2 = client.post("/api/telephony/events", json=p)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row = db.get(CallSession, cid)
        from app import config
        from app.security import decrypt_dtmf_buffer

        plain = decrypt_dtmf_buffer(
            row.dtmf_buffer,
            secret=config.DTMF_BUFFER_SECRET,
            session_id=cid,
        )
        assert plain == "3"
    finally:
        db.close()


def test_duplicate_sixth_digit_wrong_code_does_not_double_increment(client):
    cid = _start(client)
    client.post("/api/telephony/events", json=_payload(call_id=cid, event_type="ANSWERED"))
    client.post(
        "/api/telephony/events",
        json=_payload(call_id=cid, event_type="DTMF", digit="1"),
    )
    wrong = "123456"
    for d in wrong[:5]:
        client.post(
            "/api/telephony/events",
            json=_payload(call_id=cid, event_type="DTMF", digit=d),
        )
    p6 = _payload(
        call_id=cid,
        event_type="DTMF",
        digit=wrong[5],
        provider_event_id="wrong-attempt-final-digit",
    )
    r1 = client.post("/api/telephony/events", json=p6)
    assert r1.status_code == 200
    assert r1.json().get("verified") is None
    r_hash = client.post(
        "/api/telephony/events",
        json=_payload(call_id=cid, event_type="DTMF", digit="#", provider_event_id="wrong-submit"),
    )
    assert r_hash.status_code == 200
    assert r_hash.json().get("detail") == "pending_admin_verification"

    sess1 = client.get(f"/api/calls/{cid}").json()
    assert sess1["wrong_code_attempts"] == 0
    assert sess1["simulator_step"] == "pending_admin_verification"

    r2 = client.post("/api/telephony/events", json=p6)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

    assert client.post(f"/api/calls/{cid}/admin/reject-verification").status_code == 200
    sess2 = client.get(f"/api/calls/{cid}").json()
    assert sess2["wrong_code_attempts"] == 1


def test_duplicate_terminal_event_consistent(client):
    cid = _start(client)
    client.post("/api/telephony/events", json=_payload(call_id=cid, event_type="ANSWERED"))
    client.post(
        "/api/telephony/events",
        json=_payload(call_id=cid, event_type="DTMF", digit="1"),
    )
    p = _payload(call_id=cid, event_type="HANGUP", provider_event_id="hang-1")
    r1 = client.post("/api/telephony/events", json=p)
    assert r1.status_code == 200
    assert r1.json()["session_status"] == SessionStatus.FAILED.value

    r2 = client.post("/api/telephony/events", json=p)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"
    assert r2.json()["session_status"] == SessionStatus.FAILED.value

    p2 = _payload(call_id=cid, event_type="FAILED", provider_event_id="fail-after-terminal")
    r3 = client.post("/api/telephony/events", json=p2)
    assert r3.status_code == 200
    assert r3.json().get("noop") is True
    assert r3.json().get("status") != "duplicate_ignored"

    r4 = client.post("/api/telephony/events", json=p2)
    assert r4.status_code == 200
    assert r4.json()["status"] == "duplicate_ignored"
