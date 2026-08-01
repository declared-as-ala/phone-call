"""Tests for LuvVoice TTS integration."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from app.services import luvvoice_tts
from app.services.speech_session_lookup import get_session_speech_prefs


def test_api_token_configured(monkeypatch):
    monkeypatch.delenv("LUVVOICE_API_TOKEN", raising=False)
    assert luvvoice_tts.api_token_configured() is False
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")
    assert luvvoice_tts.api_token_configured() is True


def test_list_voices_parses_response(monkeypatch):
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")

    def fake_page(voice_type=None):
        if voice_type == "standard":
            return [{"voice_id": "voice-001", "name": "Jenny"}]
        if voice_type == "cloned":
            return [{"voice_id": "clone-001", "name": "Custom A"}]
        return []

    with patch("app.services.luvvoice_tts._fetch_voices_page", side_effect=fake_page):
        voices = luvvoice_tts.list_voices()
    assert [v["voice_id"] for v in voices] == ["clone-001", "voice-001"]


def test_list_voices_single_type_skips_merge(monkeypatch):
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")

    with patch(
        "app.services.luvvoice_tts._fetch_voices_page",
        return_value=[{"voice_id": "voice-002", "name": "Bob"}],
    ) as fetch:
        voices = luvvoice_tts.list_voices(voice_type="standard")
    fetch.assert_called_once_with(voice_type="standard")
    assert voices[0]["voice_id"] == "voice-002"


def test_synthesize_to_wav_from_base64(monkeypatch, tmp_path):
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")
    mp3_bytes = b"fake-mp3"
    b64 = base64.b64encode(mp3_bytes).decode("ascii")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"success": True, "audio_data": b64}

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = lambda *a: None
    mock_client.post.return_value = FakeResp()

    wav_path = str(tmp_path / "out.wav")

    with patch("app.services.luvvoice_tts.httpx.Client", return_value=mock_client), patch(
        "app.services.luvvoice_tts._mp3_to_wav_8k_mono", return_value=True
    ) as conv:
        ok = luvvoice_tts.synthesize_to_wav("Hello", wav_path, voice_id="voice-001")
    assert ok is True
    conv.assert_called_once()


def test_get_session_speech_prefs_defaults(monkeypatch, test_engine):
    from sqlalchemy.orm import sessionmaker

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    monkeypatch.setattr("app.services.speech_session_lookup.SessionLocal", TestSessionLocal)
    monkeypatch.setenv("LUVVOICE_DEFAULT_VOICE_ID", "voice-050")
    engine, voice, volume = get_session_speech_prefs("00000000-0000-0000-0000-000000000000")
    assert volume == 88
    assert engine == "luvvoice"
    assert voice == "voice-050"


def test_start_call_rejects_luvvoice_without_token(client, monkeypatch):
    monkeypatch.delenv("LUVVOICE_API_TOKEN", raising=False)

    r = client.post(
        "/api/calls/start",
        json={
            "name": "Test",
            "university": "Org",
            "phone_number": "+21626565725",
            "outbound_trunk": "sip_up",
            "outbound_caller_id": "393888736444",
            "speech_engine": "luvvoice",
        },
    )
    assert r.status_code == 503


def test_luvvoice_preview_endpoint(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")
    wav = tmp_path / "preview.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)

    with patch("app.routers.tts.synthesize_to_wav", return_value=True) as synth, patch(
        "app.routers.tts.apply_wav_gain_inplace"
    ) as gain:

        def fake_synth(text, path, *, voice_id=None, **kwargs):
            with open(path, "wb") as fh:
                fh.write(wav.read_bytes())
            return True

        synth.side_effect = fake_synth

        r = client.post(
            "/api/tts/luvvoice/preview",
            json={
                "text": "Hello preview",
                "voice_id": "voice-042",
                "speech_volume_percent": 88,
            },
        )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("audio/wav")
    assert len(r.content) > 8
    gain.assert_called_once()
    synth.assert_called_once()


def test_start_call_stores_speech_engine(client, monkeypatch):
    monkeypatch.setenv("LUVVOICE_API_TOKEN", "tok")

    r = client.post(
        "/api/calls/start",
        json={
            "name": "Test",
            "university": "Org",
            "phone_number": "+21626565725",
            "outbound_trunk": "sip_up",
            "outbound_caller_id": "393888736444",
            "speech_engine": "free",
            "luvvoice_voice_id": "voice-002",
        },
    )
    assert r.status_code == 200
    call_id = r.json()["call_id"]
    detail = client.get(f"/api/calls/{call_id}").json()
    assert detail["speech_engine"] == "free"
