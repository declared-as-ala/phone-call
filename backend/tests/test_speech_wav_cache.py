"""Tests for LuvVoice prefetch cache."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from app.services.speech_wav_cache import (
    clear_call_cache,
    content_cache_key,
    copy_cached_wav_if_available,
    global_cached_wav_path,
    schedule_luvvoice_prefetch,
    store_cached_wav,
    synthesize_spoken_wav_singleflight,
    wait_for_cached_wav,
)


def test_content_cache_key_stable():
    a = content_cache_key("Hello", speech_engine="luvvoice", voice_id="voice-001", volume_percent=70)
    b = content_cache_key("  hello  ", speech_engine="luvvoice", voice_id="voice-001", volume_percent=70)
    assert a == b


def test_copy_cached_wav_miss(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    dest = tmp_path / "out.wav"
    hit = copy_cached_wav_if_available(
        "call-1",
        "Consent text",
        speech_engine="luvvoice",
        luvvoice_voice_id="voice-001",
        volume_percent=70,
        dest_wav_path=str(dest),
    )
    assert hit is False
    assert not dest.exists()


def test_copy_cached_wav_global_hit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    key = content_cache_key(
        "Consent text",
        speech_engine="luvvoice",
        voice_id="voice-001",
        volume_percent=70,
    )
    global_path = global_cached_wav_path(key)
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_bytes(b"RIFFGLOBAL")
    dest = tmp_path / "out.wav"
    hit = copy_cached_wav_if_available(
        "call-1",
        "Consent text",
        speech_engine="luvvoice",
        luvvoice_voice_id="voice-001",
        volume_percent=70,
        dest_wav_path=str(dest),
    )
    assert hit is True
    assert dest.read_bytes() == b"RIFFGLOBAL"
    # Promoted into per-call cache.
    assert (tmp_path / "call-1" / f"{key}.wav").is_file()


def test_wait_for_cached_wav_sees_late_write(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    key = content_cache_key(
        "Late text",
        speech_engine="luvvoice",
        voice_id="voice-001",
        volume_percent=70,
    )
    call_dir = tmp_path / "call-late"
    call_dir.mkdir()
    dest = tmp_path / "out.wav"

    def _writer() -> None:
        time.sleep(0.12)
        (call_dir / f"{key}.wav").write_bytes(b"RIFFLATE")

    threading.Thread(target=_writer, daemon=True).start()
    hit = wait_for_cached_wav(
        "call-late",
        "Late text",
        speech_engine="luvvoice",
        luvvoice_voice_id="voice-001",
        volume_percent=70,
        dest_wav_path=str(dest),
        wait_ms=800,
    )
    assert hit is True
    assert dest.read_bytes() == b"RIFFLATE"


def test_synthesize_singleflight_stores_global(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    wav = tmp_path / "synth.wav"
    aiff = tmp_path / "synth.aiff"

    def fake_synth(text, wav_path, *, aiff_path, speech_engine, luvvoice_voice_id, volume_percent, allow_free_fallback=True):
        Path(wav_path).write_bytes(b"RIFFSYNTH")
        return True

    with patch("app.services.speech_wav_cache.synthesize_spoken_wav", side_effect=fake_synth):
        ok = synthesize_spoken_wav_singleflight(
            "Hello there",
            str(wav),
            aiff_path=str(aiff),
            speech_engine="luvvoice",
            luvvoice_voice_id="voice-001",
            volume_percent=70,
            call_id="call-sf",
            allow_free_fallback=False,
        )
    assert ok is True
    key = content_cache_key(
        "Hello there",
        speech_engine="luvvoice",
        voice_id="voice-001",
        volume_percent=70,
    )
    assert global_cached_wav_path(key).read_bytes() == b"RIFFSYNTH"
    assert (tmp_path / "call-sf" / f"{key}.wav").read_bytes() == b"RIFFSYNTH"


def test_schedule_prefetch_skips_without_token(monkeypatch):
    monkeypatch.delenv("LUVVOICE_API_TOKEN", raising=False)
    with patch("app.services.speech_wav_cache._prefetch_consent_blocking") as prefetch:
        schedule_luvvoice_prefetch("abc")
        prefetch.assert_not_called()


def test_prefetch_creates_parent_dir_before_synth(tmp_path, monkeypatch):
    from app.services.speech_wav_cache import _prefetch_consent_blocking

    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.speech_wav_cache.get_session_speech_prefs",
        lambda _cid: ("luvvoice", "voice-001", 70),
    )

    class FakeSession:
        name = "Test"
        university = "Bank"
        expected_digits_count = 6

    class FakeDb:
        def get(self, _model, _cid):
            return FakeSession()

        def close(self):
            return None

    monkeypatch.setattr("app.services.speech_wav_cache.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        "app.services.speech_wav_cache.speech_script_service.render_for_session",
        lambda _db, _sess, _key: "Hello test consent",
    )

    seen = {"parent_existed": False}

    def fake_synth(text, wav_path, *, aiff_path, speech_engine, luvvoice_voice_id, volume_percent, allow_free_fallback=True):
        parent = Path(wav_path).parent
        seen["parent_existed"] = parent.is_dir()
        Path(wav_path).write_bytes(b"RIFF")
        return True

    with patch("app.services.speech_wav_cache.synthesize_spoken_wav", side_effect=fake_synth):
        assert _prefetch_consent_blocking("call-xyz") is True
    assert seen["parent_existed"] is True


def test_clear_call_cache_removes_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    call_dir = tmp_path / "call-xyz"
    call_dir.mkdir()
    (call_dir / "abc.wav").write_bytes(b"wav")
    clear_call_cache("call-xyz")
    assert not call_dir.exists()


def test_store_cached_wav_writes_global(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.speech_wav_cache._cache_root", lambda: tmp_path)
    src = tmp_path / "src.wav"
    src.write_bytes(b"RIFFSRC")
    store_cached_wav("call-a", "abc123", str(src))
    assert (tmp_path / "call-a" / "abc123.wav").read_bytes() == b"RIFFSRC"
    assert (tmp_path / "_content" / "abc123.wav").read_bytes() == b"RIFFSRC"
