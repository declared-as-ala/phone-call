"""Canonical ``CallEvent.event_type`` values: enum coverage and persistence guardrails."""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.event_types import (
    LEGACY_CALL_EVENT_TYPES,
    CallEventType,
    allowed_persisted_call_event_types,
)
from app.models import CallEvent, EventActor, SessionStatus, SimulatorStep
from app.services import outbound_simulation as osim
from app.services.call_service import MAX_VERIFICATION_ATTEMPTS, call_service


def test_call_event_type_values_unique():
    values = [e.value for e in CallEventType]
    assert len(values) == len(set(values))


def test_canonical_and_legacy_event_sets_disjoint():
    canonical = {e.value for e in CallEventType}
    assert canonical.isdisjoint(LEGACY_CALL_EVENT_TYPES)


def test_allowed_persisted_includes_all_enum_members():
    allowed = allowed_persisted_call_event_types()
    for e in CallEventType:
        assert e.value in allowed


def _tel(call_id: str, event_type: str, digit: Optional[str] = None) -> dict[str, Any]:
    p: dict[str, Any] = {"provider": "mock", "call_id": call_id, "event_type": event_type}
    if digit is not None:
        p["digit"] = digit
    return p


def test_persisted_event_types_after_representative_flows_are_canonical_or_legacy(
    client, test_engine
):
    """Every ``event_type`` stored by exercised API paths must be enum or explicitly legacy."""
    allowed = allowed_persisted_call_event_types()

    r0 = client.post(
        "/api/calls/start",
        json={"name": "A", "university": "U", "phone_number": "+15550008001"},
    )
    cid = r0.json()["call_id"]
    code = r0.json()["demo_code"]

    client.post(f"/api/simulator/{cid}/answered")
    client.post(f"/api/simulator/{cid}/press", json={"digit": "1"})
    client.post(f"/api/simulator/{cid}/enter-code", json={"digits": "000000"})
    client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code})

    r1 = client.post(
        "/api/calls/start",
        json={"name": "B", "university": "U", "phone_number": "+15550008002"},
    )
    cid2 = r1.json()["call_id"]
    client.post("/api/telephony/events", json=_tel(cid2, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid2, "DTMF", "5"))

    r2 = client.post(
        "/api/calls/start",
        json={"name": "C", "university": "U", "phone_number": "+15550008003"},
    )
    cid3 = r2.json()["call_id"]
    client.post("/api/telephony/events", json=_tel(cid3, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid3, "DTMF", "1"))
    for d in code:
        client.post("/api/telephony/events", json=_tel(cid3, "DTMF", d))

    r3 = client.post(
        "/api/calls/start",
        json={"name": "D", "university": "U", "phone_number": "+15550008004"},
    )
    cid4 = r3.json()["call_id"]
    client.post("/api/telephony/events", json=_tel(cid4, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid4, "HANGUP"))

    r4 = client.post(
        "/api/calls/start",
        json={"name": "E", "university": "U", "phone_number": "+15550008005"},
    )
    cid5 = r4.json()["call_id"]
    client.post("/api/telephony/events", json=_tel(cid5, "ANSWERED"))
    client.post("/api/telephony/events", json=_tel(cid5, "FAILED"))

    r5 = client.post(
        "/api/calls/start",
        json={"name": "F", "university": "U", "phone_number": "+15550008006"},
    )
    cid6 = r5.json()["call_id"]
    client.post(f"/api/simulator/{cid6}/answered")
    client.post(f"/api/simulator/{cid6}/press", json={"digit": "1"})
    for _ in range(MAX_VERIFICATION_ATTEMPTS):
        client.post(f"/api/simulator/{cid6}/enter-code", json={"digits": "000000"})

    r6 = client.post(
        "/api/calls/start",
        json={"name": "G", "university": "U", "phone_number": "+15550008007"},
    )
    cid7 = r6.json()["call_id"]
    client.post(f"/api/simulator/{cid7}/answered")
    client.post(f"/api/simulator/{cid7}/press", json={"digit": "1"})
    client.post(
        f"/api/simulator/{cid7}/action",
        json={"action": "submit_digits", "digits": "000000"},
    )

    async def _replay_outbound_lifecycle():
        Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        db = Session()
        try:
            row, _ = call_service.create_call_session(
                db, name="Replay", university="Uni", phone_number="+15550008008"
            )
            await call_service.add_event(
                db,
                row.id,
                CallEventType.CALL_INITIATED.value,
                "Outbound initiated",
                new_status=SessionStatus.DIALING,
            )
            sequence = [
                (CallEventType.DIAL_STARTED.value, "PJSIP/... dial"),
                (CallEventType.CALL_RINGING.value, "Ringing"),
                ("ANSWERED", "Channel answered"),
                (CallEventType.IVR_PROMPT.value, "Compliance prompt played"),
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
        finally:
            db.close()

    asyncio.run(_replay_outbound_lifecycle())

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        distinct_types = set(db.scalars(select(CallEvent.event_type).distinct()).all())
    finally:
        db.close()

    unknown = distinct_types - allowed
    assert not unknown, f"Unknown persisted event_type values: {unknown}"
