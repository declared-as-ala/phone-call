"""Tests for Asterisk WAV conversion helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.services import audio_convert


def test_resolve_ffmpeg_prefers_path(monkeypatch):
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert audio_convert.resolve_ffmpeg_executable() == "/usr/bin/ffmpeg"


def test_resolve_ffmpeg_falls_back_to_imageio(monkeypatch):
    monkeypatch.setattr(audio_convert.shutil, "which", lambda _name: None)

    class FakeImageioFfmpeg:
        @staticmethod
        def get_ffmpeg_exe():
            return r"C:\fake\ffmpeg.exe"

    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", FakeImageioFfmpeg())
    with patch("os.path.isfile", return_value=True):
        assert audio_convert.resolve_ffmpeg_executable() == r"C:\fake\ffmpeg.exe"


def test_convert_media_to_asterisk_wav_success(monkeypatch, tmp_path):
    src = tmp_path / "in.mp3"
    dst = tmp_path / "out.wav"
    src.write_bytes(b"mp3")
    dst.write_bytes(b"RIFF")

    monkeypatch.setattr(audio_convert, "resolve_ffmpeg_executable", lambda: "/usr/bin/ffmpeg")

    class FakeProc:
        returncode = 0

    with patch("app.services.audio_convert.subprocess.run", return_value=FakeProc()) as run:
        ok = audio_convert.convert_media_to_asterisk_wav(str(src), str(dst), log_label="test")
    assert ok is True
    assert run.call_args.args[0][0] == "/usr/bin/ffmpeg"


def test_wav_duration_ms_reads_pcm(tmp_path):
    import wave

    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w_out:
        w_out.setnchannels(1)
        w_out.setsampwidth(2)
        w_out.setframerate(8000)
        w_out.writeframes(b"\x00" * 16000)
    assert audio_convert.wav_duration_ms(str(path)) == 1000.0
