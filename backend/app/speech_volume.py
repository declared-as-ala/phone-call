"""Callee TTS loudness: dashboard percent slider → linear WAV gain."""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess

from app.services.audio_convert import resolve_ffmpeg_executable

logger = logging.getLogger(__name__)

DEFAULT_SPEECH_VOLUME_PERCENT = 70
MIN_SPEECH_VOLUME_PERCENT = 40
MAX_SPEECH_VOLUME_PERCENT = 150


def clamp_speech_volume_percent(percent: object) -> int:
    try:
        n = int(percent)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SPEECH_VOLUME_PERCENT
    return max(MIN_SPEECH_VOLUME_PERCENT, min(MAX_SPEECH_VOLUME_PERCENT, n))


def volume_percent_to_gain(percent: object) -> float:
    """~1.0 gain at 70%; default 88% ≈ 1.26 (comfortable test level)."""
    p = clamp_speech_volume_percent(percent)
    return round(p / 70.0, 3)


def apply_wav_gain_inplace(path: str, gain: float) -> None:
    """Raise or lower synthesized WAV loudness (phone calls and dashboard preview)."""
    if gain <= 0 or abs(gain - 1.0) < 0.02:
        return
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        logger.warning("ffmpeg not found — skipping speech volume gain %.2f", gain)
        return
    outp = path + ".vol.wav"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            path,
            "-filter:a",
            f"volume={gain:.3f}",
            "-acodec",
            "pcm_s16le",
            outp,
        ],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:220]
        logger.warning("ffmpeg volume filter failed (gain=%s): %s", gain, err)
        with contextlib.suppress(OSError):
            if os.path.exists(outp):
                os.remove(outp)
        return
    os.replace(outp, path)
