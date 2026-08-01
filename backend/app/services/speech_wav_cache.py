"""Pre-synthesize LuvVoice speech during ring so audio plays immediately on answer."""

from __future__ import annotations

import contextlib
import hashlib
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from ..database import SessionLocal
from ..models import CallSession
from ..speech_volume import apply_wav_gain_inplace, clamp_speech_volume_percent, volume_percent_to_gain
from . import luvvoice_tts, speech_script_service
from .audio_convert import convert_media_to_asterisk_wav
from .speech_session_lookup import get_session_speech_prefs

logger = logging.getLogger(__name__)

_prefetch_lock = threading.Lock()
_prefetch_inflight: set[str] = set()
_synth_singleflight_guard = threading.Lock()
_synth_singleflight_locks: dict[str, threading.Lock] = {}

# How long playback may wait for ring-time prefetch / cross-process cache before deciding.
IVR_TTS_CACHE_WAIT_MS_ENV = "IVR_TTS_CACHE_WAIT_MS"
_DEFAULT_CACHE_WAIT_MS = 1500


def _cache_root() -> Path:
    override = (os.getenv("IVR_TTS_CACHE_DIR") or "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        # Project/.local/tts-cache (not backend/.local — matches logs and start-all layout)
        root = Path(__file__).resolve().parents[3] / ".local" / "tts-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def content_cache_key(text: str, *, speech_engine: str, voice_id: str, volume_percent: int) -> str:
    norm = _normalize_text(text).lower()
    raw = f"{speech_engine}|{voice_id}|{volume_percent}|{norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cached_wav_path(call_id: str, cache_key: str) -> Path:
    safe_id = str(call_id or "").strip() or "unknown"
    return _cache_root() / safe_id / f"{cache_key}.wav"


def global_cached_wav_path(cache_key: str) -> Path:
    """Content-addressed WAV shared across calls (same script/voice/volume)."""
    return _cache_root() / "_content" / f"{cache_key}.wav"


def read_cache_wait_ms(default_ms: int = _DEFAULT_CACHE_WAIT_MS) -> int:
    raw = (os.getenv(IVR_TTS_CACHE_WAIT_MS_ENV) or "").strip()
    if not raw:
        return max(0, int(default_ms))
    try:
        return max(0, min(30_000, int(raw)))
    except ValueError:
        return max(0, int(default_ms))


def prefetch_inflight(call_id: str) -> bool:
    safe_id = str(call_id or "").strip()
    if not safe_id:
        return False
    with _prefetch_lock:
        return safe_id in _prefetch_inflight


def _singleflight_lock(cache_key: str) -> threading.Lock:
    with _synth_singleflight_guard:
        lock = _synth_singleflight_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _synth_singleflight_locks[cache_key] = lock
        return lock


def clear_call_cache(call_id: str) -> None:
    safe_id = str(call_id or "").strip()
    if not safe_id:
        return
    with _prefetch_lock:
        if safe_id in _prefetch_inflight:
            logger.info(
                "IVR speech cache clear deferred (prefetch in flight) call_prefix=%s",
                safe_id[:8],
            )
            return
    target = _cache_root() / safe_id
    if not target.exists():
        return
    shutil.rmtree(target, ignore_errors=True)
    logger.info("IVR speech cache cleared call_prefix=%s", safe_id[:8])


def clear_all_speech_cache() -> None:
    """Drop synthesized WAV cache so updated speech scripts take effect on the next call."""
    root = _cache_root()
    if not root.exists():
        return
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    logger.info("IVR speech cache cleared after speech-script update")


def _ffmpeg_to_asterisk_wav(src_path: str, wav_path: str) -> bool:
    return convert_media_to_asterisk_wav(src_path, wav_path, log_label="TTS source")


def _synthesize_windows_sapi_wav(text: str, wav_path: str) -> bool:
    """Windows-only fallback when LuvVoice/ffmpeg/espeak are unavailable."""
    if os.name != "nt":
        return False
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return False
    fd, tmp_native = tempfile.mkstemp(prefix="ivr-sapi-", suffix=".wav")
    os.close(fd)
    try:
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        out_path = json.dumps(tmp_native)
        script = (
            "$ErrorActionPreference = 'Stop'; "
            f"$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}')); "
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$synth.SetOutputToWaveFile({out_path}); "
            "$synth.Speak($text); "
            "$synth.Dispose();"
        )
        proc = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=180,
        )
        if proc.returncode != 0 or not os.path.exists(tmp_native) or os.path.getsize(tmp_native) < 100:
            return False
        return _ffmpeg_to_asterisk_wav(tmp_native, wav_path)
    finally:
        with contextlib.suppress(OSError):
            if os.path.exists(tmp_native):
                os.remove(tmp_native)


def _synthesize_platform_wav(text: str, wav_path: str, aiff_path: str) -> bool:
    if shutil.which("say") and shutil.which("afconvert"):
        r1 = subprocess.run(
            ["say", "-v", "Samantha", "-o", aiff_path, text],
            capture_output=True,
            timeout=180,
        )
        if r1.returncode != 0:
            return False
        r2 = subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@8000", aiff_path, wav_path],
            capture_output=True,
        )
        return r2.returncode == 0 and os.path.exists(wav_path)
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe:
        r = subprocess.run([exe, "-s", "155", "-w", wav_path, text], capture_output=True, timeout=180)
        return r.returncode == 0 and os.path.exists(wav_path)
    return _synthesize_windows_sapi_wav(text, wav_path)


def synthesize_spoken_wav(
    text: str,
    wav_path: str,
    *,
    aiff_path: str,
    speech_engine: str,
    luvvoice_voice_id: Optional[str],
    volume_percent: int,
    allow_free_fallback: bool = True,
) -> bool:
    """Synthesize callee speech to an 8 kHz mono WAV (LuvVoice or local free TTS)."""
    clean = _normalize_text(text)
    if not clean:
        return False

    engine = (speech_engine or "luvvoice").strip().lower()
    volume = clamp_speech_volume_percent(volume_percent)
    gain = volume_percent_to_gain(volume)

    if engine == "luvvoice":
        try:
            if luvvoice_tts.synthesize_to_wav(
                clean,
                wav_path,
                voice_id=luvvoice_voice_id,
            ):
                try:
                    apply_wav_gain_inplace(wav_path, gain)
                except Exception as exc:
                    logger.warning("IVR could not apply LuvVoice gain=%s: %s", gain, exc)
                return True
            logger.warning("LuvVoice synthesis returned no WAV — trying free system TTS")
        except luvvoice_tts.LuvVoiceApiError as exc:
            logger.warning("LuvVoice TTS failed (%s) — trying free system TTS", exc)
        except luvvoice_tts.LuvVoiceConfigurationError as exc:
            logger.warning("LuvVoice not configured (%s) — trying free system TTS", exc)
        if not allow_free_fallback:
            return False

    ok = _synthesize_platform_wav(clean, wav_path, aiff_path)
    if ok:
        try:
            apply_wav_gain_inplace(wav_path, gain)
        except Exception as exc:
            logger.warning("IVR could not apply free-TTS gain=%s: %s", gain, exc)
    return ok


def store_cached_wav(call_id: str, cache_key: str, wav_path: str) -> None:
    if not os.path.exists(wav_path):
        return
    global_dest = global_cached_wav_path(cache_key)
    global_dest.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        shutil.copy2(wav_path, global_dest)
    if not call_id:
        return
    dest = cached_wav_path(call_id, cache_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav_path, dest)


def _resolve_cache_key(
    text: str,
    *,
    speech_engine: str,
    luvvoice_voice_id: Optional[str],
    volume_percent: int,
) -> tuple[str, str, int]:
    voice = (luvvoice_voice_id or luvvoice_tts.default_voice_id()).strip()
    volume = clamp_speech_volume_percent(volume_percent)
    key = content_cache_key(
        text,
        speech_engine=speech_engine,
        voice_id=voice,
        volume_percent=volume,
    )
    return key, voice, volume


def _copy_wav_src(src: Path, dest_wav_path: str) -> bool:
    if not src.is_file() or src.stat().st_size <= 0:
        return False
    shutil.copy2(src, dest_wav_path)
    return True


def copy_cached_wav_if_available(
    call_id: str,
    text: str,
    *,
    speech_engine: str,
    luvvoice_voice_id: Optional[str],
    volume_percent: int,
    dest_wav_path: str,
) -> bool:
    key, _voice, _volume = _resolve_cache_key(
        text,
        speech_engine=speech_engine,
        luvvoice_voice_id=luvvoice_voice_id,
        volume_percent=volume_percent,
    )
    if call_id:
        src = cached_wav_path(call_id, key)
        if _copy_wav_src(src, dest_wav_path):
            logger.info(
                "IVR speech cache hit call_prefix=%s engine=%s bytes=%s",
                call_id[:8],
                speech_engine,
                src.stat().st_size,
            )
            return True
    global_src = global_cached_wav_path(key)
    if _copy_wav_src(global_src, dest_wav_path):
        logger.info(
            "IVR speech cache hit (global content) engine=%s bytes=%s",
            speech_engine,
            global_src.stat().st_size,
        )
        if call_id:
            # Promote into per-call dir so hangup cleanup still owns a copy.
            store_cached_wav(call_id, key, dest_wav_path)
        return True
    return False


def wait_for_cached_wav(
    call_id: str,
    text: str,
    *,
    speech_engine: str,
    luvvoice_voice_id: Optional[str],
    volume_percent: int,
    dest_wav_path: str,
    wait_ms: Optional[int] = None,
) -> bool:
    """Poll for prefetch / cross-process cache before falling through to cold TTS.

    Returns True when a WAV was copied into ``dest_wav_path``.
    """
    if copy_cached_wav_if_available(
        call_id,
        text,
        speech_engine=speech_engine,
        luvvoice_voice_id=luvvoice_voice_id,
        volume_percent=volume_percent,
        dest_wav_path=dest_wav_path,
    ):
        return True

    budget_ms = read_cache_wait_ms() if wait_ms is None else max(0, int(wait_ms))
    if budget_ms <= 0:
        return False

    saw_local_inflight = prefetch_inflight(call_id)
    deadline = time.monotonic() + (budget_ms / 1000.0)
    logger.info(
        "IVR speech cache wait call_prefix=%s wait_ms=%s prefetch_inflight=%s",
        (call_id or "")[:8] or "none",
        budget_ms,
        saw_local_inflight,
    )
    while time.monotonic() < deadline:
        time.sleep(0.05)
        if copy_cached_wav_if_available(
            call_id,
            text,
            speech_engine=speech_engine,
            luvvoice_voice_id=luvvoice_voice_id,
            volume_percent=volume_percent,
            dest_wav_path=dest_wav_path,
        ):
            return True
        inflight_now = prefetch_inflight(call_id)
        if inflight_now:
            saw_local_inflight = True
        elif saw_local_inflight:
            # Same-process prefetch finished without this key — stop waiting.
            return copy_cached_wav_if_available(
                call_id,
                text,
                speech_engine=speech_engine,
                luvvoice_voice_id=luvvoice_voice_id,
                volume_percent=volume_percent,
                dest_wav_path=dest_wav_path,
            )
    return copy_cached_wav_if_available(
        call_id,
        text,
        speech_engine=speech_engine,
        luvvoice_voice_id=luvvoice_voice_id,
        volume_percent=volume_percent,
        dest_wav_path=dest_wav_path,
    )


def synthesize_spoken_wav_singleflight(
    text: str,
    wav_path: str,
    *,
    aiff_path: str,
    speech_engine: str,
    luvvoice_voice_id: Optional[str],
    volume_percent: int,
    call_id: str = "",
    allow_free_fallback: bool = True,
) -> bool:
    """Synthesize once per content key; concurrent callers reuse the cached WAV."""
    key, voice, volume = _resolve_cache_key(
        text,
        speech_engine=speech_engine,
        luvvoice_voice_id=luvvoice_voice_id,
        volume_percent=volume_percent,
    )
    lock = _singleflight_lock(key)
    with lock:
        if copy_cached_wav_if_available(
            call_id,
            text,
            speech_engine=speech_engine,
            luvvoice_voice_id=voice,
            volume_percent=volume,
            dest_wav_path=wav_path,
        ):
            return True
        ok = synthesize_spoken_wav(
            text,
            wav_path,
            aiff_path=aiff_path,
            speech_engine=speech_engine,
            luvvoice_voice_id=luvvoice_voice_id,
            volume_percent=volume,
            allow_free_fallback=allow_free_fallback,
        )
        if ok:
            store_cached_wav(call_id, key, wav_path)
        return ok


def prefetch_prompt_blocking(call_id: str, prompt_script_key: str = "consent_prompt") -> bool:
    engine, voice_id, volume = get_session_speech_prefs(call_id)
    if engine != "luvvoice":
        return False

    db = SessionLocal()
    try:
        sess = db.get(CallSession, call_id)
        if sess is None:
            return False
        text = speech_script_service.render_for_session(db, sess, prompt_script_key)
    except Exception as exc:
        logger.debug("IVR prefetch db lookup skipped call_prefix=%s prompt=%s: %s", call_id[:8], prompt_script_key, exc)
        return False
    finally:
        db.close()

    clean = _normalize_text(text)
    if not clean:
        return False

    key, voice, volume = _resolve_cache_key(
        clean,
        speech_engine=engine,
        luvvoice_voice_id=voice_id,
        volume_percent=volume,
    )
    dest = cached_wav_path(call_id, key)
    global_dest = global_cached_wav_path(key)
    if dest.is_file() and dest.stat().st_size > 0:
        logger.info("IVR speech cache already warm call_prefix=%s prompt=%s", call_id[:8], prompt_script_key)
        return True
    if global_dest.is_file() and global_dest.stat().st_size > 0:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(global_dest, dest)
        logger.info(
            "IVR speech cache warm from global content call_prefix=%s prompt=%s",
            call_id[:8],
            prompt_script_key,
        )
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_wav = tempfile.mkstemp(prefix="prefetch-", suffix=".wav", dir=str(dest.parent))
    os.close(fd)
    fd_aiff, tmp_aiff = tempfile.mkstemp(prefix="prefetch-", suffix=".aiff", dir=str(dest.parent))
    os.close(fd_aiff)
    try:
        ok = synthesize_spoken_wav_singleflight(
            clean,
            tmp_wav,
            aiff_path=tmp_aiff,
            speech_engine=engine,
            luvvoice_voice_id=voice,
            volume_percent=volume,
            call_id=call_id,
            allow_free_fallback=False,
        )
        if not ok:
            logger.warning("IVR LuvVoice prefetch failed call_prefix=%s prompt=%s", call_id[:8], prompt_script_key)
            return False
        if not dest.is_file():
            os.replace(tmp_wav, dest)
        elif os.path.exists(tmp_wav):
            with contextlib.suppress(OSError):
                os.remove(tmp_wav)
        logger.info(
            "IVR LuvVoice prefetch ready call_prefix=%s prompt=%s bytes=%s",
            call_id[:8],
            prompt_script_key,
            dest.stat().st_size if dest.is_file() else 0,
        )
        return True
    finally:
        for p in (tmp_wav, tmp_aiff):
            with contextlib.suppress(OSError):
                if p and os.path.exists(p):
                    os.remove(p)


def _prefetch_consent_blocking(call_id: str) -> bool:
    """Prefetch initial consent and follow-up prompts sequentially."""
    ok_consent = prefetch_prompt_blocking(call_id, "consent_prompt")
    prefetch_prompt_blocking(call_id, "code_sent_prompt")
    return ok_consent


def schedule_luvvoice_prefetch(call_id: str) -> None:
    """Warm LuvVoice consent and code_sent audio while the outbound leg is ringing."""
    safe_id = str(call_id or "").strip()
    if not safe_id or not luvvoice_tts.api_token_configured():
        return
    with _prefetch_lock:
        if safe_id in _prefetch_inflight:
            return
        _prefetch_inflight.add(safe_id)

    def _run() -> None:
        try:
            _prefetch_consent_blocking(safe_id)
        except Exception as exc:
            logger.warning("IVR LuvVoice prefetch error call_prefix=%s: %s", safe_id[:8], exc)
        finally:
            with _prefetch_lock:
                _prefetch_inflight.discard(safe_id)

    threading.Thread(target=_run, name=f"luvvoice-prefetch-{safe_id[:8]}", daemon=True).start()

