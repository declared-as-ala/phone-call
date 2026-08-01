"""VirtualCallDevice transcripts — updated for admin-confirmed external code send."""

import importlib

from app.models import CallEvent, CallSession, SessionStatus, SimulatorStep
from app.services.prompt_renderer import PromptRenderer
from app.services.virtual_call_device import VirtualCallDevice


def _session(step=SimulatorStep.VERIFICATION_CODE.value, status=SessionStatus.COLLECTING.value):
    return CallSession(
        id="call-1",
        name="Yassin",
        university="Polytech",
        phone_number="+15550002525",
        verification_code_hash="hash",
        status=status,
        simulator_step=step,
    )


def _event(event_type: str, message: str):
    return CallEvent(session_id="call-1", event_type=event_type, message=message, actor_type="system")


def test_virtual_device_shows_full_six_digit_code(monkeypatch):
    monkeypatch.setattr("app.config.VIRTUAL_CALL_DEVICE_ENABLED", True)
    lines = []
    device = VirtualCallDevice(printer=lines.append)

    device.handle_event(
        _session(),
        _event("DIGITS_RECEIVED", "Keypad entry complete (6 digits): 123456"),
    )

    output = "\n".join(lines)
    assert "123456" in output
    assert "DTMF RECEIVED: 123456" in output


def test_virtual_device_disabled_in_production_by_default(monkeypatch):
    import app.config as cfg

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("VIRTUAL_CALL_DEVICE_ENABLED", raising=False)
    importlib.reload(cfg)
    try:
        assert cfg.VIRTUAL_CALL_DEVICE_ENABLED is False
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)
        importlib.reload(cfg)


def test_virtual_device_prints_expected_speech_lines(monkeypatch):
    monkeypatch.setattr("app.config.VIRTUAL_CALL_DEVICE_ENABLED", True)
    lines = []
    device = VirtualCallDevice(printer=lines.append)

    device.handle_event(_session(SimulatorStep.CONSENT.value), _event("CALL_ANSWERED", "answered"))
    device.handle_event(
        _session(SimulatorStep.VERIFICATION_CODE.value),
        _event("RECIPIENT_ACCEPTED", "Recipient pressed 1"),
    )
    device.handle_event(
        _session(SimulatorStep.PENDING_ADMIN_VERIFICATION.value, SessionStatus.PENDING_ADMIN_VERIFICATION.value),
        _event("PENDING_ADMIN_VERIFICATION", "Entered code pending admin verification: 654321"),
    )
    device.handle_event(
        _session(SimulatorStep.FINISHED.value, SessionStatus.COMPLETED.value),
        _event("ADMIN_VERIFICATION_APPROVED", "Admin approved"),
    )

    output = "\n".join(lines)
    consent = PromptRenderer.consent_prompt("Yassin", "Polytech")
    code_entry = PromptRenderer.verification_code_prompt()
    pend = PromptRenderer.pending_admin_verification_prompt()
    ok = PromptRenderer.success_prompt()
    assert f"SAY: {consent['text']}" in output
    assert "WAITING FOR DTMF: press 1 to confirm, 2 to decline" in output
    assert f"SAY: {code_entry['text']}" in output
    assert f"SAY: {pend['text']}" in output
    assert "ADMIN APPROVED" in output
    assert f"SAY: {ok['text']}" in output


def test_virtual_device_does_not_change_call_state_flow(client, monkeypatch):
    monkeypatch.setattr("app.config.VIRTUAL_CALL_DEVICE_ENABLED", True)
    r0 = client.post(
        "/api/calls/start",
        json={"name": "Virtual", "university": "Local U", "phone_number": "+15550003030"},
    )
    data = r0.json()
    cid, code = data["call_id"], data["demo_code"]

    assert client.post(f"/api/simulator/{cid}/answered").status_code == 200
    assert client.post(f"/api/simulator/{cid}/press", json={"digit": "1"}).status_code == 200
    assert client.post(f"/api/simulator/{cid}/enter-code", json={"digits": code}).status_code == 200

    pending = client.get(f"/api/calls/{cid}").json()
    assert pending["status"] == SessionStatus.PENDING_ADMIN_VERIFICATION.value
    assert pending["simulator_step"] == SimulatorStep.PENDING_ADMIN_VERIFICATION.value

    assert client.post(f"/api/calls/{cid}/admin/approve-verification").status_code == 200
    final = client.get(f"/api/calls/{cid}").json()
    assert final["status"] == SessionStatus.COMPLETED.value
    assert final["simulator_step"] == SimulatorStep.FINISHED.value
