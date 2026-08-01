"""LuvVoice TTS helpers for the admin dashboard."""

from __future__ import annotations

import contextlib
import os
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import get_current_admin
from ..speech_volume import apply_wav_gain_inplace, clamp_speech_volume_percent, volume_percent_to_gain
from ..services.luvvoice_tts import (
    LuvVoiceApiError,
    LuvVoiceConfigurationError,
    api_token_configured,
    default_voice_id,
    list_voices,
    synthesize_to_wav,
)


class LuvVoicePreviewBody(BaseModel):
    text: str = Field(
        default="Please wait while the administrator sends your verification code.",
        min_length=1,
        max_length=500,
    )
    voice_id: str = Field(min_length=1, max_length=128)
    speech_volume_percent: int = Field(default=88, ge=40, le=150)

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/luvvoice/voices")
def luvvoice_voices(type: Optional[str] = None) -> dict[str, Any]:
    """List LuvVoice voices available to the configured API token."""
    if not api_token_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "LUVVOICE_API_TOKEN is not configured on the backend. "
                "Add your token from LuvVoice Dashboard → API Tokens."
            ),
        )
    try:
        voices = list_voices(voice_type=type)
    except LuvVoiceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LuvVoiceApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "default_voice_id": default_voice_id(),
        "voices": voices,
        "total_voices": len(voices),
    }


@router.get("/luvvoice/status")
def luvvoice_status() -> dict[str, Any]:
    """Whether premium LuvVoice TTS is configured (no secrets returned)."""
    return {
        "configured": api_token_configured(),
        "default_voice_id": default_voice_id(),
    }


@router.post("/luvvoice/preview")
def luvvoice_preview(body: LuvVoicePreviewBody) -> Response:
    """Synthesize preview audio with the selected LuvVoice speaker and call volume gain."""
    if not api_token_configured():
        raise HTTPException(
            status_code=503,
            detail="LUVVOICE_API_TOKEN is not configured on the backend.",
        )
    text = body.text.strip()
    voice_id = body.voice_id.strip()
    volume = clamp_speech_volume_percent(body.speech_volume_percent)
    gain = volume_percent_to_gain(volume)

    fd, wav_path = tempfile.mkstemp(prefix="luvvoice-preview-", suffix=".wav")
    os.close(fd)
    try:
        try:
            ok = synthesize_to_wav(text, wav_path, voice_id=voice_id)
        except LuvVoiceConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LuvVoiceApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=502, detail="LuvVoice preview synthesis failed")
        apply_wav_gain_inplace(wav_path, gain)
        with open(wav_path, "rb") as fh:
            data = fh.read()
        return Response(
            content=data,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    finally:
        with contextlib.suppress(OSError):
            if os.path.exists(wav_path):
                os.remove(wav_path)
