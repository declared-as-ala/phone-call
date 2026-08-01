"""Admin speech script persistence and validation (API)."""

from sqlalchemy.orm import sessionmaker

from app.models import CallSession
from app.services import speech_script_service as ss


def _all_keys(payload: dict) -> dict[str, str]:
    return {k: (payload[k] + "").strip() for k in ss.SCRIPT_KEYS_ORDERED}


def test_get_speech_scripts_returns_defaults_when_empty(client):
    data = client.get("/api/speech-scripts").json()
    scripts = data["scripts"]
    for key in ss.SCRIPT_KEYS_ORDERED:
        assert key in scripts
        assert (scripts[key] or "").strip()
    assert "{name}" in scripts["consent_prompt"]


def test_put_validation_blocks_whatsapp_word(client):
    base = client.get("/api/speech-scripts").json()["scripts"]
    bad = _all_keys(base)
    bad["consent_prompt"] = bad["consent_prompt"] + " Use WhatsApp for help."
    r = client.put("/api/speech-scripts", json={"scripts": bad})
    assert r.status_code == 422


def test_put_save_then_reset_matches_defaults(client):
    base = client.get("/api/speech-scripts").json()["scripts"]
    custom = _all_keys(base)
    custom["approved_prompt"] = "All set. Have a wonderful day."

    put = client.put("/api/speech-scripts", json={"scripts": custom})
    assert put.status_code == 200
    got = client.get("/api/speech-scripts").json()["scripts"]
    assert got["approved_prompt"] == custom["approved_prompt"]

    pst = client.post("/api/speech-scripts/reset")
    assert pst.status_code == 200
    restored = pst.json()["scripts"]
    assert restored["approved_prompt"] == ss.DEFAULT_SPEECH_SCRIPTS["approved_prompt"]


def test_latest_saved_templates_used_by_renderer_for_sessions(client, test_engine):
    """Realtime/Asterisk uses ``render_for_session`` (DB-backed); edits apply until reset."""

    base = client.get("/api/speech-scripts").json()["scripts"]
    custom = _all_keys(base)
    marker = "CUSTOM_CONSENT_PHRASE_XYZ"
    custom["consent_prompt"] = f"Hello {{name}}. {{organization}} {marker}"

    assert client.put("/api/speech-scripts", json={"scripts": custom}).status_code == 200

    start = client.post(
        "/api/calls/start",
        json={
            "name": "Neo",
            "university": "Matrix U",
            "phone_number": "+15550009001",
        },
    )
    assert start.status_code == 200
    cid = start.json()["call_id"]

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = Session()
    try:
        row = db.get(CallSession, cid)
        assert row is not None
        text = ss.render_for_session(db, row, "consent_prompt")
        assert marker in text
        assert "Neo" in text
        assert "Matrix U" in text
    finally:
        db.close()
