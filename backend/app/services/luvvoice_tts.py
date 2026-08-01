"""LuvVoice cloud TTS (https://luvvoice.com/api/v1/text-to-speech)."""

from __future__ import annotations

import base64
import contextlib
import logging
import os
import tempfile
from typing import Any, Optional

import httpx

from .audio_convert import convert_media_to_asterisk_wav

logger = logging.getLogger(__name__)

LUVVOICE_API_TOKEN = "LUVVOICE_API_TOKEN"
LUVVOICE_DEFAULT_VOICE_ID = "LUVVOICE_DEFAULT_VOICE_ID"
LUVVOICE_API_BASE = "https://luvvoice.com/api/v1/text-to-speech"
DEFAULT_VOICE_ID = "voice-001"
REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class LuvVoiceConfigurationError(RuntimeError):
    pass


class LuvVoiceApiError(RuntimeError):
    pass


def api_token_configured() -> bool:
    return bool((os.getenv(LUVVOICE_API_TOKEN, "") or "").strip())


def default_voice_id() -> str:
    return (os.getenv(LUVVOICE_DEFAULT_VOICE_ID, "") or "").strip() or DEFAULT_VOICE_ID


def _auth_headers() -> dict[str, str]:
    token = (os.getenv(LUVVOICE_API_TOKEN, "") or "").strip()
    if not token:
        raise LuvVoiceConfigurationError(
            f"{LUVVOICE_API_TOKEN} is not set. Add your LuvVoice API token to backend/.env "
            "(Dashboard → API Tokens on a Plus plan or higher)."
        )
    return {"Authorization": f"Bearer {token}"}


def _mp3_to_wav_8k_mono(mp3_path: str, wav_path: str) -> bool:
    return convert_media_to_asterisk_wav(mp3_path, wav_path, log_label="LuvVoice MP3")


def _write_mp3_from_response(payload: dict[str, Any], mp3_path: str) -> bool:
    audio_url = (payload.get("audio_url") or "").strip()
    if audio_url:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(audio_url, headers=_auth_headers())
        if resp.status_code >= 400:
            raise LuvVoiceApiError(f"LuvVoice audio download failed: HTTP {resp.status_code}")
        mp3_path_obj = mp3_path
        with open(mp3_path_obj, "wb") as fh:
            fh.write(resp.content)
        return os.path.getsize(mp3_path_obj) > 0

    raw_b64 = payload.get("audio_data")
    if raw_b64:
        data = base64.b64decode(str(raw_b64))
        with open(mp3_path, "wb") as fh:
            fh.write(data)
        return len(data) > 0

    return False


def _fetch_voices_page(*, voice_type: Optional[str] = None) -> list[dict[str, Any]]:
    params: dict[str, str] = {"action": "voices"}
    if voice_type:
        params["type"] = voice_type
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.get(LUVVOICE_API_BASE, params=params, headers=_auth_headers())
    if resp.status_code == 401:
        raise LuvVoiceApiError("LuvVoice API token is invalid or missing (HTTP 401)")
    if resp.status_code == 403:
        raise LuvVoiceApiError("LuvVoice API access denied — Plus plan or higher required (HTTP 403)")
    if resp.status_code >= 400:
        raise LuvVoiceApiError(f"LuvVoice voice list failed: HTTP {resp.status_code}")
    body = resp.json()
    if not body.get("success"):
        raise LuvVoiceApiError(str(body.get("error") or body.get("message") or "voice list failed"))
    voices = body.get("voices") or []
    return [v for v in voices if isinstance(v, dict)]


def list_voices(*, voice_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Return LuvVoice voices. When ``voice_type`` is omitted, merge standard + cloned catalogs."""
    if voice_type:
        return _fetch_voices_page(voice_type=voice_type)

    merged: dict[str, dict[str, Any]] = {}
    for bucket in ("standard", "cloned"):
        for voice in _fetch_voices_page(voice_type=bucket):
            vid = str(voice.get("voice_id") or "").strip()
            if vid:
                merged[vid] = voice
    return sorted(
        merged.values(),
        key=lambda v: (
            str(v.get("name") or v.get("voice_id") or "").lower(),
            str(v.get("voice_id") or ""),
        ),
    )


def synthesize_to_wav(
    text: str,
    wav_path: str,
    *,
    voice_id: Optional[str] = None,
    voice_type: str = "standard",
    rate: int = 0,
    pitch: int = 0,
    volume: int = 0,
    language: Optional[str] = None,
) -> bool:
    """Generate speech via LuvVoice and write an 8 kHz mono WAV for Asterisk playback.
    
    Args:
        text: Text to synthesize
        wav_path: Output WAV file path
        voice_id: LuvVoice voice ID
        voice_type: "standard" or "cloned"
        rate: Speech rate adjustment (-50 to +50)
        pitch: Pitch adjustment (-50 to +50)
        volume: Volume adjustment (-50 to +50)
        language: Language code (e.g. "en", "es", "fr") - optional, uses voice's default if not specified
    """
    clean = (text or "").strip()
    if not clean:
        return False

    vid = (voice_id or default_voice_id()).strip() or DEFAULT_VOICE_ID
    body = {
        "text": clean,
        "voice_id": vid,
        "voice_type": voice_type,
        "rate": max(-50, min(50, int(rate))),
        "pitch": max(-50, min(50, int(pitch))),
        "volume": max(-50, min(50, int(volume))),
    }
    
    # Add language if specified (LuvVoice API will use voice's default if omitted)
    if language:
        body["language"] = str(language).strip().lower()

    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.post(
            LUVVOICE_API_BASE,
            json=body,
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )

    if resp.status_code == 402:
        raise LuvVoiceApiError("LuvVoice insufficient credits (HTTP 402)")
    if resp.status_code == 429:
        raise LuvVoiceApiError("LuvVoice rate limit exceeded (HTTP 429)")
    if resp.status_code >= 400:
        detail = resp.text[:300] if resp.text else resp.status_code
        raise LuvVoiceApiError(f"LuvVoice TTS failed: HTTP {resp.status_code}: {detail}")

    payload = resp.json()
    if payload.get("error"):
        raise LuvVoiceApiError(str(payload.get("error")))

    fd, mp3_path = tempfile.mkstemp(prefix="luvvoice-", suffix=".mp3")
    os.close(fd)
    try:
        if not _write_mp3_from_response(payload, mp3_path):
            logger.warning("LuvVoice response had no audio_url or audio_data")
            return False
        return _mp3_to_wav_8k_mono(mp3_path, wav_path)
    finally:
        with contextlib.suppress(OSError):
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
