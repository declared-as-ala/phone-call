"""POST /api/telephony/events — provider webhook ingestion."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import CallEvent, SessionStatus, SimulatorStep
from app.security import mask_digits_in_text


def _evt(**kwargs):
    base = {
        "provider": "mock",
        "call_id": kwargs.pop("call_id"),
        "event_type": kwargs.pop("event_type"),
    }
    if "provider_call_id" in kwargs:
        base["provider_call_id"] = kwargs.pop("provider_call_id")
    if "digit" in kwargs:
        base["digit"] = kwargs.pop("digit")
    if "raw_payload" in kwargs:
        base["raw_payload"] = kwargs.pop("raw_payload")
    if "provider_event_id" in kwargs:
        base["provider_event_id"] = kwargs.pop("provider_event_id")
    assert not kwargs, kwargs
    return base


def _start(client):
    r = client.post(
        "/api/calls/start",
        json={
            "name": "T",
            "university": "Uni",
            "phone_number": "+15550009901",
        },
    )
    assert r.status_code == 200
    return r.json()["call_id"], r.json().get("demo_code")


def _answered_press1_confirm(client, cid):
    assert client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED")).status_code == 200
    assert (
        client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="1")).status_code == 200
    )


def test_press1_moves_session_to_verification_code_step(client):
    cid, _ = _start(client)
    _answered_press1_confirm(client, cid)
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value


def test_admin_code_sent_idempotent_when_already_verification_code_step(client):
    cid, _ = _start(client)
    _answered_press1_confirm(client, cid)

    def _admin_code_sent_count(call_id: str) -> int:
        evs = client.get(f"/api/calls/{call_id}/events").json()
        return sum(1 for e in evs if e["event_type"] == "ADMIN_CODE_SENT_CONFIRMED")

    assert _admin_code_sent_count(cid) == 0
    r_dup = client.post(f"/api/calls/{cid}/admin/code-sent")
    assert r_dup.status_code == 200
    assert r_dup.json().get("idempotent") is True
    assert _admin_code_sent_count(cid) == 0

    cid2, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid2, event_type="ANSWERED"))
    r_bad = client.post(f"/api/calls/{cid2}/admin/code-sent")
    assert r_bad.status_code == 400


def test_telephony_events_unknown_call(client):
    r = client.post(
        "/api/telephony/events",
        json=_evt(call_id=str(uuid4()), event_type="ANSWERED"),
    )
    assert r.status_code == 404


def test_answered_moves_to_consent(client):
    cid, _ = _start(client)
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["simulator_step"] == SimulatorStep.CONSENT.value

    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["simulator_step"] == SimulatorStep.CONSENT.value

    evs = client.get(f"/api/calls/{cid}/events").json()
    answered = next(e for e in evs if e["event_type"] == "CALL_ANSWERED")
    assert answered["actor_type"] == "telephony_provider"


def test_answered_idempotent_when_already_consent(client):
    cid, _ = _start(client)
    assert client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED")).status_code == 200
    r2 = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    assert r2.status_code == 200
    assert r2.json()["noop"] is True


def test_dtmf_consent_accept_and_decline(client):
    cid, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))

    r1 = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="1"))
    assert r1.status_code == 200
    assert r1.json()["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value

    cid2, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid2, event_type="ANSWERED"))
    r2 = client.post("/api/telephony/events", json=_evt(call_id=cid2, event_type="DTMF", digit="2"))
    assert r2.status_code == 200
    assert r2.json()["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value
    ivr2 = r2.json().get("ivr_speech")
    assert ivr2 is not None
    text = (ivr2.get("text") or "").lower()
    assert "otp" in text
    sess = client.get(f"/api/calls/{cid2}").json()
    assert sess["simulator_step"] == SimulatorStep.VERIFICATION_CODE.value
    assert sess["status"] == SessionStatus.COLLECTING.value


def test_dtmf_press_1_announces_otp_entry(client):
    cid, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="1"))
    assert r.status_code == 200
    ivr = r.json().get("ivr_speech")
    assert ivr is not None
    text = (ivr.get("text") or "").lower()
    assert "verification" in text
    assert "6-digit" in text


def test_dtmf_invalid_consent_input(client, test_engine):
    cid, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="5"))
    assert r.status_code == 200
    assert r.json()["detail"] == "invalid_consent_digit"
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["simulator_step"] == SimulatorStep.CONSENT.value

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        rows = db.scalars(select(CallEvent).where(CallEvent.session_id == cid)).all()
        assert any(e.event_type == "INVALID_CONSENT_INPUT" for e in rows)
    finally:
        db.close()


def test_dtmf_collects_otp_and_waits_for_admin(client):
    cid, code = _start(client)
    _answered_press1_confirm(client, cid)

    for i, d in enumerate(code[:5]):
        r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=d))
        assert r.status_code == 200
        assert r.json()["verified"] is None
        assert r.json()["digits_collected"] == i + 1

    r_last = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=code[5]))
    assert r_last.status_code == 200
    assert r_last.json()["verified"] is None
    r_hash = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="#"))
    assert r_hash.status_code == 200
    assert r_hash.json().get("detail") == "pending_admin_verification"
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert sess["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value
    assert sess["masked_entered_code"] == mask_digits_in_text(code)
    assert "entered_code" not in sess

    r_approve = client.post(f"/api/calls/{cid}/admin/approve-verification")
    assert r_approve.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value
    assert sess["ivr_outcome"] == "verified"


def test_duplicate_dtmf_digit_after_otp_pending_verification_noop(client):
    from uuid import uuid4

    cid, code = _start(client)
    _answered_press1_confirm(client, cid)
    for d in code[:5]:
        assert (
            client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=d)).status_code
            == 200
        )
    assert (
        client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=code[5])).status_code
        == 200
    )
    assert (
        client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit="#")).status_code
        == 200
    )

    dup = client.post(
        "/api/telephony/events",
        json=_evt(
            call_id=cid,
            event_type="DTMF",
            digit="9",
            provider_event_id=str(uuid4()),
        ),
    )
    assert dup.status_code == 200
    body = dup.json()
    assert body.get("noop") is True
    assert body.get("detail") == "duplicate_dtmf_after_code_complete"
    assert body.get("digits_collected") == 6


def test_hangup_during_verification_marks_failed(client):
    cid, code = _start(client)
    _answered_press1_confirm(client, cid)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=code[0]))
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="HANGUP"))
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value


def test_hangup_during_consent_marks_completed_declined(client):
    cid, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="HANGUP"))
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.COMPLETED.value
    assert sess["ivr_outcome"] == "declined"


def test_hangup_busy_before_answer_declines_with_clear_message(client):
    cid, _ = _start(client)
    r = client.post(
        "/api/telephony/events",
        json=_evt(
            call_id=cid,
            event_type="HANGUP",
            raw_payload={"cause": 17, "dialstatus": "BUSY"},
        ),
    )
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value

    evs = client.get(f"/api/calls/{cid}/events").json()
    hangup = next(e for e in evs if e["event_type"] == "CALL_HANGUP")
    assert "already on another call" in hangup["message"].lower()
    assert "declined" in hangup["message"].lower()


def test_failed_busy_event_declines_with_clear_message(client):
    cid, _ = _start(client)
    r = client.post(
        "/api/telephony/events",
        json=_evt(
            call_id=cid,
            event_type="FAILED",
            raw_payload={"failure_kind": "recipient_busy", "dialstatus": "BUSY", "cause": 17},
        ),
    )
    assert r.status_code == 200
    evs = client.get(f"/api/calls/{cid}/events").json()
    failed_ev = next(e for e in evs if e["event_type"] == "CALL_FAILED")
    assert "already on another call" in failed_ev["message"].lower()
    assert "declined" in failed_ev["message"].lower()


def test_ringing_event_emits_call_ringing(client):
    cid, _ = _start(client)
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="RINGING"))
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.RINGING.value
    evs = client.get(f"/api/calls/{cid}/events").json()
    ringing = [e for e in evs if e["event_type"] == "CALL_RINGING"]
    assert len(ringing) == 1


def test_hangup_invalid_destination_before_answer_has_clear_message(client):
    cid, _ = _start(client)
    r = client.post(
        "/api/telephony/events",
        json=_evt(
            call_id=cid,
            event_type="HANGUP",
            raw_payload={"cause": 1, "channel_state": "Down"},
        ),
    )
    assert r.status_code == 200
    evs = client.get(f"/api/calls/{cid}/events").json()
    hangup = next(e for e in evs if e["event_type"] == "CALL_HANGUP")
    assert "invalid" in hangup["message"].lower() or "unallocated" in hangup["message"].lower()
    assert "caller id" in hangup["message"].lower()


def test_hangup_before_answer_emits_pre_answer_failure_message(client):
    cid, _ = _start(client)
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="HANGUP"))
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value

    evs = client.get(f"/api/calls/{cid}/events").json()
    hangup = next(e for e in evs if e["event_type"] == "CALL_HANGUP")
    assert "before answer" in hangup["message"].lower()
    assert "sip up" in hangup["message"].lower() or "403" in hangup["message"].lower()
    answered_events = [e for e in evs if e["event_type"] == "CALL_ANSWERED"]
    assert answered_events == []


def test_hangup_after_answer_during_verification_uses_after_answer_wording(client):
    cid, code = _start(client)
    _answered_press1_confirm(client, cid)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="DTMF", digit=code[0]))
    r = client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="HANGUP"))
    assert r.status_code == 200

    evs = client.get(f"/api/calls/{cid}/events").json()
    hangup = next(e for e in evs if e["event_type"] == "CALL_HANGUP")
    assert "after answer" in hangup["message"].lower()
    assert "before answer" not in hangup["message"].lower()


def test_failed_event_marks_session_failed(client):
    cid, _ = _start(client)
    client.post("/api/telephony/events", json=_evt(call_id=cid, event_type="ANSWERED"))
    r = client.post(
        "/api/telephony/events",
        json=_evt(call_id=cid, event_type="FAILED", raw_payload={"cause": "sip_486"}),
    )
    assert r.status_code == 200
    sess = client.get(f"/api/calls/{cid}").json()
    assert sess["status"] == SessionStatus.FAILED.value

    evs = client.get(f"/api/calls/{cid}/events").json()
    failed_ev = next(e for e in evs if e["event_type"] == "CALL_FAILED")
    assert failed_ev["actor_type"] == "telephony_provider"
    assert "sip_" in failed_ev["message"].lower() or "cause" in failed_ev["message"].lower()


def test_failed_ring_timeout_uses_clear_message(client, monkeypatch):
    monkeypatch.setenv("ASTERISK_ORIGINATE_TIMEOUT_SECONDS", "60")
    cid, _ = _start(client)
    r = client.post(
        "/api/telephony/events",
        json=_evt(
            call_id=cid,
            event_type="FAILED",
            raw_payload={
                "type": "ChannelDestroyed",
                "channel_name": "PJSIP/sip-up-trunk-00000003",
                "channel_state": "Ringing",
                "cause": 0,
                "failure_kind": "ring_timeout",
            },
        ),
    )
    assert r.status_code == 200
    evs = client.get(f"/api/calls/{cid}/events").json()
    failed_ev = next(e for e in evs if e["event_type"] == "CALL_FAILED")
    assert "timed out while ringing" in failed_ev["message"].lower()
    assert "sip up" in failed_ev["message"].lower()
    assert "not a sip trunk rejection" in failed_ev["message"].lower()


def test_provider_client_api_literal_accepted(client):
    cid, _ = _start(client)
    r = client.post(
        "/api/telephony/events",
        json={
            "provider": "client_api",
            "call_id": cid,
            "event_type": "ANSWERED",
            "provider_call_id": "ext-123",
        },
    )
    assert r.status_code == 200
