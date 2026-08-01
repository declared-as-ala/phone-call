"""Resolve per-call speech engine preferences from the database."""

from __future__ import annotations

import os
from typing import Optional

from ..database import SessionLocal
from ..models import CallSession
from ..speech_volume import DEFAULT_SPEECH_VOLUME_PERCENT, clamp_speech_volume_percent
from .luvvoice_tts import default_voice_id

SpeechEngine = str  # "free" | "luvvoice"


def get_session_speech_prefs(call_id: str) -> tuple[SpeechEngine, Optional[str], int]:
    """Return (speech_engine, luvvoice_voice_id, speech_volume_percent) for a call session."""
    fallback_engine: SpeechEngine = "luvvoice"
    fallback_voice = default_voice_id()
    fallback_volume = DEFAULT_SPEECH_VOLUME_PERCENT
    if not call_id:
        return fallback_engine, fallback_voice, fallback_volume

    db = SessionLocal()
    try:
        row = db.get(CallSession, call_id)
        if row is None:
            return fallback_engine, fallback_voice, fallback_volume
        engine = (row.speech_engine or fallback_engine).strip().lower() or fallback_engine
        if engine not in {"free", "luvvoice"}:
            engine = fallback_engine
        voice = (row.luvvoice_voice_id or fallback_voice).strip() or fallback_voice
        volume = clamp_speech_volume_percent(
            getattr(row, "speech_volume_percent", None) or fallback_volume
        )
        return engine, voice, volume
    finally:
        db.close()
