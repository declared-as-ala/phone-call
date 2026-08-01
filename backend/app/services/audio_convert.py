"""Convert TTS audio to 8 kHz mono PCM WAV for Asterisk telephony playback."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

_ASTERISK_WAV_ARGS = (
    "-ar",
    "8000",
    "-ac",
    "1",
    "-sample_fmt",
    "s16",
)


def resolve_ffmpeg_executable() -> Optional[str]:
    """Return ffmpeg on PATH, or the bundled binary from imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except ImportError:
        pass
    return None


def convert_media_to_asterisk_wav(src_path: str, wav_path: str, *, log_label: str = "audio") -> bool:
    """Transcode any ffmpeg-readable source to 8 kHz mono signed-16 WAV."""
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        logger.warning(
            "ffmpeg not found — cannot convert %s to Asterisk WAV "
            "(install ffmpeg or: pip install imageio-ffmpeg)",
            log_label,
        )
        return False
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            src_path,
            *_ASTERISK_WAV_ARGS,
            wav_path,
        ],
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:240]
        logger.warning("ffmpeg %s→WAV failed: %s", log_label, err)
        return False
    return os.path.exists(wav_path) and os.path.getsize(wav_path) > 0


def wav_duration_ms(path: str) -> Optional[float]:
    """Return WAV duration in milliseconds when readable."""
    try:
        import wave

        with wave.open(path, "rb") as w_in:
            rate = w_in.getframerate()
            frames = w_in.getnframes()
            if rate <= 0:
                return None
            return (frames / rate) * 1000.0
    except Exception:
        return None
