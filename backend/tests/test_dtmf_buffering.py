"""DTMF buffer: encryption at rest, DIGIT_RECEIVED / DIGITS_RECEIVED, retry and terminal noop."""

from sqlalchemy.orm import sessionmaker

from app import config
from app.models import CallEvent, CallSession, SessionStatus, SimulatorStep
from app.security import decrypt_dtmf_buffer, mask_digits_in_text


def _start(client):
    r = client.post(
        "/api/calls/start",
        json={"name": "B", "university": "Uni", "phone_number": "+15550008801"},
    )
    assert r.status_code == 200
    return r.json()["call_id"], r.json()["demo_code"]


def _evt(call_id, event_type, digit=None):
    p = {"provider": "mock", "call_id": call_id, "event_type": event_type}
    if digit is not None:
        p["digit"] = digit
    return p


def _answered_press1(client, cid):
    assert client.post("/api/telephony/events", json=_evt(cid, "ANSWERED")).status_code == 200
    assert client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit="1")).status_code == 200


def _submit_code_digits(client, cid, digits):
    for i, d in enumerate(digits):
        r = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=d))
        assert r.status_code == 200
        if i + 1 < len(digits):
            assert r.json().get("verified") is None
            assert r.json().get("digits_collected") == i + 1


def test_pending_admin_stage_blocks_dtmf(client):
    cid, code = _start(client)
    _answered_press1(client, cid)
    _submit_code_digits(client, cid, code)
    r = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit="9"))
    assert r.status_code == 400


def test_single_dtmf_digits_build_code_and_emit_digit_received(client):
    cid, code = _start(client)
    _answered_press1(client, cid)

    for i, d in enumerate(code[:5]):
        r = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=d))
        assert r.status_code == 200
        assert r.json()["digits_collected"] == i + 1

    evs = client.get(f"/api/calls/{cid}/events").json()
    digit_events = [e for e in evs if e["event_type"] == "DIGIT_RECEIVED"]
    assert len(digit_events) == 5


def test_partial_buffer_is_encrypted_at_rest(client, test_engine):
    cid, code = _start(client)
    _answered_press1(client, cid)
    client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=code[0]))
    client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=code[1]))

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row = db.get(CallSession, cid)
        assert row is not None
        assert row.dtmf_buffer
        assert row.buffer_updated_at is not None
        assert row.dtmf_buffer != code[:2]
        plain = decrypt_dtmf_buffer(
            row.dtmf_buffer,
            secret=config.DTMF_BUFFER_SECRET,
            session_id=row.id,
        )
        assert plain == code[:2]
    finally:
        db.close()


def test_admin_reject_clears_buffer_allows_retry(client, test_engine):
    cid, code = _start(client)
    _answered_press1(client, cid)

    wrong = "000000"
    for d in wrong:
        client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=d))
    client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit="#"))

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value
    assert sess["masked_entered_code"] == mask_digits_in_text(wrong)
    assert "entered_code" not in sess
    assert client.get(f"/api/calls/{cid}/admin/entered-code").json()["entered_code"] == wrong

    r_reject = client.post(f"/api/calls/{cid}/admin/reject-verification")
    assert r_reject.status_code == 200

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row = db.get(CallSession, cid)
        assert row.wrong_code_attempts == 1
        assert decrypt_dtmf_buffer(
            row.dtmf_buffer,
            secret=config.DTMF_BUFFER_SECRET,
            session_id=row.id,
        ) == ""
    finally:
        db.close()

    evs = client.get(f"/api/calls/{cid}/events").json()
    assert any(e["event_type"] == "DIGITS_RECEIVED" for e in evs)

    _submit_code_digits(client, cid, code)

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert client.post(f"/api/calls/{cid}/admin/approve-verification").status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value
    assert sess["ivr_outcome"] == "verified"


def test_correct_code_waits_for_admin_with_digits_received(client):
    cid, code = _start(client)
    _answered_press1(client, cid)
    _submit_code_digits(client, cid, code)

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value
    evs = client.get(f"/api/calls/{cid}/events").json()
    assert any(e["event_type"] == "DIGITS_RECEIVED" for e in evs)
    assert any(e["event_type"] == "PENDING_ADMIN_VERIFICATION" for e in evs)
    assert not any(e["event_type"] == "VERIFICATION_SUCCESS" for e in evs)
    dr = next(e for e in evs if e["event_type"] == "DIGITS_RECEIVED")
    assert code not in dr["message"]
    assert mask_digits_in_text(code) in dr["message"]


def test_ten_digit_code_auto_submits_on_last_digit(client):
    cid, code = _start(client)
    _answered_press1(client, cid)
    assert len(code) == 6  # default generated code length in tests

    ten = "1234567890"
    for i, d in enumerate(ten):
        r = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit=d))
        assert r.status_code == 200
        if i + 1 < len(ten):
            assert r.json().get("verified") is None
            assert r.json().get("digits_collected") == i + 1

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert "entered_code" not in sess
    assert client.get(f"/api/calls/{cid}/admin/entered-code").json()["entered_code"] == ten


def test_extra_dtmf_after_final_state_ignored(client):
    cid, code = _start(client)
    _answered_press1(client, cid)
    _submit_code_digits(client, cid, code)
    assert client.post(f"/api/calls/{cid}/admin/approve-verification").status_code == 200

    r = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit="5"))
    assert r.status_code == 200
    assert r.json()["noop"] is True
    assert "ignored" in (r.json().get("detail") or "").lower()

    n_events_before = len(client.get(f"/api/calls/{cid}/events").json())
    r2 = client.post("/api/telephony/events", json=_evt(cid, "DTMF", digit="9"))
    assert r2.status_code == 200
    assert r2.json()["noop"] is True
    n_events_after = len(client.get(f"/api/calls/{cid}/events").json())
    assert n_events_after == n_events_before
