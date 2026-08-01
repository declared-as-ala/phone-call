"""Defaults and reset alignment with the finalized operator speech-pack."""

from app.services.prompt_renderer import PromptRenderer
from app.services import speech_script_service as ss


FINAL_EXPECTED_TEMPLATE: dict[str, str] = {
    "consent_prompt": (
        "Hello {name}. We call from {organization}. "
        "To confirm, press 1. To decline, press 2."
    ),
    "declined_prompt": "Verification declined. Goodbye.",
    "admin_send_code_instruction_prompt": (
        "Please wait while the administrator sends your verification code."
    ),
    "code_sent_prompt": (
        "Please enter your {code_length}-digit verification code on your keypad."
    ),
    "pending_admin_verification_prompt": "Please wait for the administrator verification.",
    "approved_prompt": "Thank you for choosing our services.",
    "rejected_retry_prompt": (
        "Verification failed. Please repeat your {code_length}-digit verification code."
    ),
    "failed_prompt": "Verification failed. Please contact the administration.",
    "goodbye_prompt": "Goodbye.",
}


def test_all_nine_python_defaults_match_final_spec_strings():
    for key in ss.SCRIPT_KEYS_ORDERED:
        assert ss.DEFAULT_SPEECH_SCRIPTS[key] == FINAL_EXPECTED_TEMPLATE[key], key


def test_reset_via_api_matches_defaults_after_customization(client):
    """After reset POST, DB mirrors DEFAULT_SPEECH_SCRIPTS exactly."""

    base = client.get("/api/speech-scripts").json()["scripts"]
    twisted = dict(base)
    twisted["approved_prompt"] = "Temporary override XYZ"
    assert client.put("/api/speech-scripts", json={"scripts": twisted}).status_code == 200
    r = client.post("/api/speech-scripts/reset")
    assert r.status_code == 200
    restored = r.json()["scripts"]
    for key in ss.SCRIPT_KEYS_ORDERED:
        assert restored[key] == ss.DEFAULT_SPEECH_SCRIPTS[key]


def test_substitution_variables_render_for_session(client, test_engine):
    """{name}, {organization}, {code_length} substitute through render_for_session."""

    start = client.post(
        "/api/calls/start",
        json={
            "name": "Yassin",
            "university": "Polytech",
            "phone_number": "+21626565725",
        },
    )
    assert start.status_code == 200
    cid = start.json()["call_id"]

    from app.database import SessionLocal
    from app.models import CallSession

    db = SessionLocal()
    try:
        row = db.get(CallSession, cid)
        assert row is not None
        consent = ss.render_for_session(db, row, "consent_prompt")
        assert "Yassin" in consent
        assert "Polytech" in consent
        assert "exam" not in consent.lower()
        code = ss.render_for_session(db, row, "code_sent_prompt")
        assert "6-digit" in code
        assert "verification" in code.lower()
    finally:
        db.close()


def test_call_language_auto_detects_and_renders_multilingual_defaults(client, test_engine):
    start = client.post(
        "/api/calls/start",
        json={
            "name": "María",
            "university": "Universidad",
            "phone_number": "+34123456789",
        },
    )
    assert start.status_code == 200
    cid = start.json()["call_id"]

    from app.database import SessionLocal
    from app.models import CallSession

    db = SessionLocal()
    try:
        row = db.get(CallSession, cid)
        assert row is not None
        assert row.language == "es"
        consent = ss.render_for_session(db, row, "consent_prompt")
        assert "Hola" in consent
        assert "presione 1" in consent.lower()
    finally:
        db.close()


def test_consent_renderer_matches_consent_prompt():
    p = PromptRenderer.consent_prompt("Test User", "Test University")
    assert "Test User" in p["text"]
    assert "Test University" in p["text"]
    assert "exam" not in p["text"].lower()
    assert "press 1" in p["text"].lower()
    assert "press 2" in p["text"].lower()
