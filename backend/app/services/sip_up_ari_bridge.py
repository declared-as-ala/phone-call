from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import inspect
import json
import os
import re
import time
import shutil
import subprocess
import tempfile
import uuid
import wave
import logging
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

from ..event_types import CallEventType
from ..schemas import TelephonyWebhookEventLiteral
from ..webhook_security import (
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    compute_signature,
)
from .speech_script_service import scrub_literal_speech_placeholders
from .speech_session_lookup import get_session_speech_prefs
from . import luvvoice_tts
from .speech_wav_cache import (
    clear_call_cache,
    read_cache_wait_ms,
    schedule_luvvoice_prefetch,
    synthesize_spoken_wav_singleflight,
    wait_for_cached_wav,
)
from .audio_convert import wav_duration_ms
from .telephony.sip_up_ari_provider import (
    ASTERISK_HOST,
    ASTERISK_PASSWORD,
    ASTERISK_PORT,
    ASTERISK_USERNAME,
    ASTERISK_ARI_PREFIX,
    SipUpAriProviderConfig,
)

logger = logging.getLogger(__name__)

IVR_DYN_SOUNDS_DIR_ENV = "IVR_DYN_SOUNDS_DIR"
IVR_POST_ANSWER_RTP_SETTLE_MS_ENV = "IVR_POST_ANSWER_RTP_SETTLE_MS"
IVR_TTS_COLD_STATIC_FALLBACK_ENV = "IVR_TTS_COLD_STATIC_FALLBACK"


def _cold_static_fallback_enabled() -> bool:
    """When TTS cache is cold after a short wait, prefer static Asterisk clips over ~10s silence."""
    raw = (os.getenv(IVR_TTS_COLD_STATIC_FALLBACK_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _dyn_sounds_dir() -> Path:
    override = (os.getenv(IVR_DYN_SOUNDS_DIR_ENV) or "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        root = Path(__file__).resolve().parents[3] / ".local" / "asterisk-ivr" / "dyn"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _install_dyn_wav_blocking(slug: str, wav_path: str, *, container: str) -> bool:
    """Copy synthesized WAV into Asterisk sounds (bind-mount preferred, docker cp fallback)."""
    dest = _dyn_sounds_dir() / f"{slug}.wav"
    shutil.copy2(wav_path, dest)
    if dest.stat().st_size < 100:
        logger.warning("IVR dyn WAV too small after copy slug=%s bytes=%s", slug, dest.stat().st_size)
        return False

    in_container = f"/var/lib/asterisk/sounds/ivr/dyn/{slug}.wav"
    verify = subprocess.run(
        ["docker", "exec", container, "test", "-f", in_container],
        capture_output=True,
        timeout=15,
    )
    if verify.returncode == 0:
        return True

    subprocess.run(
        ["docker", "exec", container, "mkdir", "-p", "/var/lib/asterisk/sounds/ivr/dyn"],
        capture_output=True,
        timeout=35,
    )
    cp = subprocess.run(
        ["docker", "cp", str(dest), f"{container}:{in_container}"],
        capture_output=True,
        timeout=35,
    )
    if cp.returncode != 0:
        err = (cp.stderr or b"").decode("utf-8", errors="replace")[:220]
        logger.warning("IVR docker cp dyn WAV failed slug=%s: %s", slug, err)
        return False
    return True

ASTERISK_ARI_APP = "ASTERISK_ARI_APP"
ASTERISK_ARI_SUBSCRIBE_ALL = "ASTERISK_ARI_SUBSCRIBE_ALL"
BACKEND_TELEPHONY_EVENTS_URL = "BACKEND_TELEPHONY_EVENTS_URL"
BACKEND_WS_URL = "BACKEND_WS_URL"
BACKEND_WS_TOKEN = "BACKEND_WS_TOKEN"
ASTERISK_PROMPT_CONSENT = "ASTERISK_PROMPT_CONSENT"
ASTERISK_PROMPT_VERIFICATION_CODE = "ASTERISK_PROMPT_VERIFICATION_CODE"
ASTERISK_PROMPT_PENDING_ADMIN = "ASTERISK_PROMPT_PENDING_ADMIN"
ASTERISK_PROMPT_APPROVED = "ASTERISK_PROMPT_APPROVED"
ASTERISK_PROMPT_REJECTED = "ASTERISK_PROMPT_REJECTED"
ASTERISK_PROMPT_FAILED = "ASTERISK_PROMPT_FAILED"
ASTERISK_PROMPT_DECLINED = "ASTERISK_PROMPT_DECLINED"
ASTERISK_PROMPT_PREROLL_MS = "ASTERISK_PROMPT_PREROLL_MS"
ASTERISK_PROMPT_SILENCE_MEDIA = "ASTERISK_PROMPT_SILENCE_MEDIA"
ASTERISK_PROMPT_INITIAL_SILENCE_MS = "ASTERISK_PROMPT_INITIAL_SILENCE_MS"
ASTERISK_PROMPT_TAIL_PADDING_MS = "ASTERISK_PROMPT_TAIL_PADDING_MS"
ASTERISK_SPOKEN_MIN_LEAD_MS = "ASTERISK_SPOKEN_MIN_LEAD_MS"

DEFAULT_ARI_APP = "ivr-bridge"
DEFAULT_BACKEND_EVENTS_URL = "http://127.0.0.1:8000/api/telephony/events"
DEFAULT_PROMPTS = {
    "consent": "ivr/consent",
    "verification_code": "ivr/verification-code",
    "admin_instruction": "ivr/admin-send-code-instruction",
    "code_sent": "ivr/code-sent",
    "pending_admin": "ivr/pending-admin",
    "approved": "ivr/approved",
    "rejected": "ivr/rejected",
    "failed": "ivr/failed",
    "declined": "ivr/declined",
    "goodbye": "ivr/goodbye",
}

CALL_ID_VARIABLE_NAMES = ("CALL_ID", "__CALL_ID", "__CALL_ID__", "call_id")
FAILED_DIAL_STATUSES = {"BUSY", "CANCEL", "CHANUNAVAIL", "CONGESTION", "FAILED", "NOANSWER"}
NORMAL_HANGUP_CAUSES = {16, "16", "normal", "NORMAL_CLEARING"}

# WebSocket `type`: at most one prompt playback per call for these payloads (handles double-clicks).
_WS_IVR_VOICE_ONCE_PER_SESSION_ID: frozenset[str] = frozenset(
    {
        CallEventType.ADMIN_CODE_SENT_CONFIRMED.value,
        CallEventType.ADMIN_VERIFICATION_APPROVED.value,
        CallEventType.ADMIN_VERIFICATION_REJECTED.value,
        CallEventType.VERIFICATION_SUCCESS.value,
        CallEventType.VERIFICATION_FAILED.value,
        CallEventType.MAX_ATTEMPTS_EXCEEDED.value,
        CallEventType.CALL_FAILED.value,
    }
)

# Prompts applied from /api/telephony/events responses on the SIP UP bridge; skipping WS avoids double audio.
_WS_SKIP_FANOUT_PROMPT_PLAYBACK: frozenset[str] = frozenset(
    {
        CallEventType.CALL_ANSWERED.value,
        CallEventType.IVR_PROMPT.value,
        CallEventType.RECIPIENT_ACCEPTED.value,
        CallEventType.RECIPIENT_DECLINED.value,
    }
)


def _read_prompt_preroll_ms() -> int:
    raw = os.getenv(ASTERISK_PROMPT_PREROLL_MS, "200").strip() or "200"
    try:
        v = int(raw)
    except ValueError:
        v = 200
    # Small nominal delay for RTP warmup; capped for safety.
    return max(0, min(5000, v))


def _read_prompt_initial_silence_ms() -> int:
    """Lead-in silence prepended to synthesized WAV (first RTP prompt) to avoid clipped words."""
    raw = os.getenv(ASTERISK_PROMPT_INITIAL_SILENCE_MS, "700").strip() or "700"
    try:
        v = int(raw)
    except ValueError:
        v = 700
    return max(0, min(1500, v))


def _read_spoken_min_lead_ms() -> int:
    """Applied to every spoken (TTS) prompt so mid-call cues do not truncate initial consonants (e.g. 'Hello'→'ello')."""
    raw = os.getenv(ASTERISK_SPOKEN_MIN_LEAD_MS, "380").strip() or "380"
    try:
        v = int(raw)
    except ValueError:
        v = 380
    return max(0, min(1200, v))


def _read_prompt_tail_padding_ms() -> int:
    """Extra silence after terminal prompt playback completes, before ARI hangup (lets final words finish)."""
    raw = os.getenv(ASTERISK_PROMPT_TAIL_PADDING_MS, "300").strip() or "300"
    try:
        v = int(raw)
    except ValueError:
        v = 300
    return max(0, min(5000, v))


def _prepend_silence_pcm_wav_inplace(path: str, silence_ms: int) -> None:
    """Prepend uncompressed PCM silence compatible with Asterisk playback (typically 8kHz mono LE)."""
    if silence_ms <= 0:
        return
    outp = path + ".lead.wav"
    with wave.open(path, "rb") as w_in:
        params = w_in.getparams()
        pcm = w_in.readframes(w_in.getnframes())
    nchannels, sampwidth, framerate = params.nchannels, params.sampwidth, params.framerate
    extra_frames = int(framerate * silence_ms / 1000)
    silence = b"\x00" * (extra_frames * nchannels * sampwidth)
    with wave.open(outp, "wb") as w_out:
        w_out.setparams(params)
        w_out.writeframes(silence + pcm)
    os.replace(outp, path)


@dataclass(frozen=True)
class SipUpAriBridgeConfig:
    host: str
    port: int
    username: str
    password: str
    ari_prefix: str = "/asterisk/ari"
    app: str = DEFAULT_ARI_APP
    backend_events_url: str = DEFAULT_BACKEND_EVENTS_URL
    backend_webhook_secret: Optional[str] = None
    backend_ws_url: Optional[str] = None
    backend_ws_token: Optional[str] = None
    prompts: Optional[dict[str, str]] = None
    subscribe_all: bool = True
    prompt_preroll_ms: int = 200
    prompt_preroll_silence_media: Optional[str] = None
    prompt_initial_silence_ms: int = 700

    @classmethod
    def from_env(cls) -> "SipUpAriBridgeConfig":
        provider = SipUpAriProviderConfig.from_env()
        missing = [
            name
            for name, val in (
                (ASTERISK_HOST, provider.host),
                (ASTERISK_USERNAME, provider.username),
                (ASTERISK_PASSWORD, provider.password),
            )
            if not val
        ]
        if missing:
            raise RuntimeError("SIP UP media bridge requires: " + ", ".join(missing))

        raw_subscribe_all = os.getenv(ASTERISK_ARI_SUBSCRIBE_ALL, "true").strip().lower()
        prompts = {
            "consent": os.getenv(ASTERISK_PROMPT_CONSENT, DEFAULT_PROMPTS["consent"]).strip(),
            "verification_code": os.getenv(
                ASTERISK_PROMPT_VERIFICATION_CODE,
                DEFAULT_PROMPTS["verification_code"],
            ).strip(),
            "admin_instruction": os.getenv(
                "ASTERISK_PROMPT_ADMIN_INSTRUCTION", DEFAULT_PROMPTS["admin_instruction"]
            ).strip(),
            "code_sent": os.getenv("ASTERISK_PROMPT_CODE_SENT", DEFAULT_PROMPTS["code_sent"]).strip(),
            "goodbye": os.getenv("ASTERISK_PROMPT_GOODBYE", DEFAULT_PROMPTS["goodbye"]).strip(),
            "pending_admin": os.getenv(ASTERISK_PROMPT_PENDING_ADMIN, DEFAULT_PROMPTS["pending_admin"]).strip(),
            "approved": os.getenv(ASTERISK_PROMPT_APPROVED, DEFAULT_PROMPTS["approved"]).strip(),
            "rejected": os.getenv(ASTERISK_PROMPT_REJECTED, DEFAULT_PROMPTS["rejected"]).strip(),
            "failed": os.getenv(ASTERISK_PROMPT_FAILED, DEFAULT_PROMPTS["failed"]).strip(),
            "declined": os.getenv(ASTERISK_PROMPT_DECLINED, DEFAULT_PROMPTS["declined"]).strip(),
        }
        silence_media = os.getenv(ASTERISK_PROMPT_SILENCE_MEDIA, "").strip() or None
        return cls(
            host=str(provider.host),
            port=provider.port,
            username=str(provider.username),
            password=str(provider.password),
            ari_prefix=provider.ari_prefix,
            app=os.getenv(ASTERISK_ARI_APP, DEFAULT_ARI_APP).strip() or DEFAULT_ARI_APP,
            backend_events_url=os.getenv(BACKEND_TELEPHONY_EVENTS_URL, DEFAULT_BACKEND_EVENTS_URL).strip()
            or DEFAULT_BACKEND_EVENTS_URL,
            backend_webhook_secret=os.getenv("TELEPHONY_WEBHOOK_SECRET", "").strip() or None,
            backend_ws_url=os.getenv(BACKEND_WS_URL, "").strip() or None,
            backend_ws_token=os.getenv(BACKEND_WS_TOKEN, "").strip() or None,
            prompts=prompts,
            subscribe_all=raw_subscribe_all not in {"0", "false", "no"},
            prompt_preroll_ms=_read_prompt_preroll_ms(),
            prompt_preroll_silence_media=silence_media,
            prompt_initial_silence_ms=_read_prompt_initial_silence_ms(),
        )


class SipUpAriEventMapper:
    """Translate ARI events into the existing /api/telephony/events payload."""

    def __init__(self) -> None:
        self.channel_call_ids: dict[str, str] = {}
        self.call_channels: dict[str, str] = {}
        self.answered_channels: set[str] = set()
        self.ringing_channels: set[str] = set()
        self.closed_channels: set[str] = set()

    def remember_call_id(self, channel_id: str, call_id: str) -> None:
        if channel_id and call_id:
            self.channel_call_ids[channel_id] = call_id
            self.call_channels[call_id] = channel_id

    def resolve_call_id_for_channel(self, channel_id: str) -> Optional[str]:
        """Return backend call UUID for this ARI channel (forward or reverse map); repair forward link if needed."""
        if not channel_id:
            return None
        cid = self.channel_call_ids.get(channel_id)
        if cid:
            return cid
        for rid, chan in self.call_channels.items():
            if chan == channel_id:
                self.channel_call_ids[channel_id] = rid
                return rid
        return None

    def map_event(self, event: dict[str, Any], *, call_id_override: Optional[str] = None) -> Optional[dict[str, Any]]:
        event_type = str(event.get("type") or "")
        channel_id = self._channel_id(event)
        call_id = call_id_override or self._call_id_from_event(event) or self.channel_call_ids.get(channel_id)
        if channel_id and call_id:
            self.remember_call_id(channel_id, call_id)
        if not call_id or not channel_id:
            return None

        backend_event_type: Optional[TelephonyWebhookEventLiteral] = None
        digit: Optional[str] = None

        if event_type == "StasisStart":
            if self._channel_state(event).lower() != "up":
                return None
            backend_event_type = "ANSWERED"
        elif event_type == "ChannelStateChange":
            state = self._channel_state(event).lower()
            if state == "ringing":
                backend_event_type = "RINGING"
            elif state == "up":
                backend_event_type = "ANSWERED"
            else:
                return None
        elif event_type == "ChannelDtmfReceived":
            digit = self._dtmf_digit(event)
            if not digit:
                return None
            backend_event_type = "DTMF"
        elif event_type in {"ChannelHangupRequest", "StasisEnd"}:
            backend_event_type = "HANGUP"
        elif event_type == "ChannelDestroyed":
            backend_event_type = "HANGUP" if self._is_normal_hangup(event) else "FAILED"
        elif event_type == "Dial" and self._dial_failed(event):
            backend_event_type = "FAILED"

        if backend_event_type is None:
            return None
        if backend_event_type == "RINGING":
            if channel_id in self.ringing_channels or channel_id in self.answered_channels:
                return None
            self.ringing_channels.add(channel_id)
        if backend_event_type == "ANSWERED":
            if channel_id in self.answered_channels:
                return None
            self.answered_channels.add(channel_id)
        if backend_event_type in {"HANGUP", "FAILED"}:
            if channel_id in self.closed_channels:
                return None
            self.closed_channels.add(channel_id)

        payload: dict[str, Any] = {
            "provider": "sip_up",
            "provider_call_id": channel_id,
            "provider_event_id": self._provider_event_id(event, channel_id, backend_event_type, digit),
            "call_id": call_id,
            "event_type": backend_event_type,
            "raw_payload": self._safe_raw_payload(event),
        }
        if digit is not None:
            payload["digit"] = digit
        return payload

    def _channel_id(self, event: dict[str, Any]) -> str:
        channel = event.get("channel") or event.get("peer") or {}
        return str(channel.get("id") or event.get("channel_id") or "")

    def _channel_state(self, event: dict[str, Any]) -> str:
        channel = event.get("channel") or {}
        return str(channel.get("state") or event.get("state") or "")

    def _dtmf_digit(self, event: dict[str, Any]) -> Optional[str]:
        raw = event.get("digit")
        if raw is None and isinstance(event.get("dtmf"), dict):
            raw = event["dtmf"].get("digit")
        digit = str(raw or "").strip()
        return digit if len(digit) == 1 else None

    def _call_id_from_event(self, event: dict[str, Any]) -> Optional[str]:
        for key in ("call_id", "CALL_ID"):
            value = event.get(key)
            if value:
                return str(value)
        args = event.get("args")
        if isinstance(args, list):
            for item in args:
                text = str(item or "")
                if text.startswith("call_id="):
                    return text.split("=", 1)[1]
                if text:
                    return text
        channel = event.get("channel") or {}
        variables = channel.get("channelvars") or channel.get("variables") or {}
        if isinstance(variables, dict):
            for name in CALL_ID_VARIABLE_NAMES:
                if variables.get(name):
                    return str(variables[name])
        return None

    def _provider_event_id(
        self,
        event: dict[str, Any],
        channel_id: str,
        backend_event_type: str,
        digit: Optional[str],
    ) -> str:
        explicit = event.get("id") or event.get("event_id")
        if explicit:
            return str(explicit)[:128]
        source = "|".join(
            [
                str(event.get("type") or ""),
                str(event.get("timestamp") or ""),
                channel_id,
                backend_event_type,
                digit or "",
                str(event.get("dialstatus") or event.get("dial_status") or ""),
                str(event.get("cause") or ""),
            ]
        )
        return "ari-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:48]

    def _safe_raw_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        channel = event.get("channel") or {}
        cause = event.get("cause")
        if cause in {None, "", 0, "0"}:
            cause = channel.get("cause")
        cause_txt = event.get("cause_txt") or channel.get("cause_txt")
        payload: dict[str, Any] = {
            "type": event.get("type"),
            "timestamp": event.get("timestamp"),
            "channel_id": channel.get("id"),
            "channel_name": channel.get("name"),
            "channel_state": channel.get("state"),
            "digit": event.get("digit"),
            "cause": cause,
            "cause_txt": cause_txt,
            "dialstatus": event.get("dialstatus") or event.get("dial_status"),
        }
        if self._is_recipient_busy(event):
            payload["failure_kind"] = "recipient_busy"
        elif self._is_ring_timeout(event):
            payload["failure_kind"] = "ring_timeout"
        return payload

    def _is_recipient_busy(self, event: dict[str, Any]) -> bool:
        channel = event.get("channel") or {}
        cause = event.get("cause")
        if cause in {None, "", 0, "0"}:
            cause = channel.get("cause")
        if cause in {17, "17"}:
            return True
        dialstatus = str(event.get("dialstatus") or event.get("dial_status") or "").upper()
        if dialstatus == "BUSY":
            return True
        cause_txt = str(event.get("cause_txt") or channel.get("cause_txt") or "").lower()
        return "busy" in cause_txt

    def _is_ring_timeout(self, event: dict[str, Any]) -> bool:
        state = self._channel_state(event).lower()
        cause = event.get("cause")
        dialstatus = str(event.get("dialstatus") or event.get("dial_status") or "").upper()
        if dialstatus in {"NOANSWER", "CANCEL"}:
            return True
        return state in {"ringing", "ring", "early", "progress"} and cause in {0, "0", 19, "19", None}

    def _is_normal_hangup(self, event: dict[str, Any]) -> bool:
        cause = event.get("cause") or event.get("cause_txt")
        return cause in NORMAL_HANGUP_CAUSES

    def _dial_failed(self, event: dict[str, Any]) -> bool:
        status = str(event.get("dialstatus") or event.get("dial_status") or "").upper()
        return status in FAILED_DIAL_STATUSES


class SipUpAriBridge:
    def __init__(
        self,
        config: SipUpAriBridgeConfig,
        *,
        mapper: Optional[SipUpAriEventMapper] = None,
    ) -> None:
        self.config = config
        self.mapper = mapper or SipUpAriEventMapper()
        self._generation_lock = threading.Lock()
        self._playback_generation: dict[str, int] = {}
        self._http_locks: dict[str, threading.Lock] = {}

        self._ws_ivr_seen_lock = threading.Lock()
        self._ws_ivr_play_markers: set[str] = set()
        self._ivr_play_once_by_call: dict[str, set[str]] = {}
        # At most one ANSWERED→IVR enqueue per backend call UUID (guards duplicate ARI answered edges).
        self._answered_ivr_spawn_by_call: set[str] = set()
        self._playback_tasks: dict[str, asyncio.Task] = {}
        self.bridge_instance_id: str = uuid.uuid4().hex[:12]
        ws_tok = (config.backend_ws_token or "").strip()
        if config.backend_ws_url and not ws_tok:
            logger.warning(
                "ARI bridge: BACKEND_WS_URL is set but BACKEND_WS_TOKEN is empty — "
                "no backend WebSocket subscription; admin Done — code sent will not interrupt "
                "or play callee prompts. Set BACKEND_WS_TOKEN to the same value as backend "
                "WS_BROADCAST_BRIDGE_TOKEN (recommended) or rotate an admin JWT."
            )

    def _cancel_active_playback_task(self, channel_id: str) -> None:
        task = self._playback_tasks.pop(channel_id, None)
        if task is not None and not task.done():
            task.cancel()
            logger.info("IVR active playback task cancelled channel=%s", channel_id[:16])


    def _http_channel_lock(self, channel_id: str) -> threading.Lock:
        lock = self._http_locks.get(channel_id)
        if lock is None:
            lock = threading.Lock()
            self._http_locks[channel_id] = lock
        return lock

    def _playback_generation_read(self, channel_id: str) -> int:
        with self._generation_lock:
            return self._playback_generation.get(channel_id, 0)

    def _playback_generation_bump(self, channel_id: str) -> int:
        """Invalidate any in-flight waiter and mark this channel's prompt leg as superseded."""
        with self._generation_lock:
            n = self._playback_generation.get(channel_id, 0) + 1
            self._playback_generation[channel_id] = n
            return n

    def _channel_exists_quick(self, channel_id: str) -> bool:
        """True if channel resource still exists on ARI (404 => gone)."""
        url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}")
        req = request.Request(url, headers={"Authorization": self._basic_auth_header()})
        try:
            with request.urlopen(req, timeout=4) as resp:
                return resp.status < 400
        except error.HTTPError as e:
            if e.code == 404:
                return False
            logger.warning(
                "IVR channel_exists_quick HTTP error %s channel=%s",
                e.code,
                channel_id[:16],
            )
        except Exception as e:
            logger.warning(
                "IVR channel_exists_quick failed channel=%s: %s",
                channel_id[:16],
                e,
            )
        return True

    @staticmethod
    def _playback_once_lane(*, speech_script_key: Optional[str], fallback_logical: str) -> str:
        script = str(speech_script_key or "").strip()
        if script:
            return f"script:{script}"
        lk = str(fallback_logical or "").strip() or "_"
        return f"media:{lk}"

    def _spoken_body_playback_lane(self, text: str, fallback_logical: str) -> str:
        """One playback per call per rendered script body — catches mismatched prompt_key vs speech_script_key."""
        raw = scrub_literal_speech_placeholders(text).strip()
        if not raw:
            lk = str(fallback_logical or "").strip() or "_"
            return f"media:{lk}"
        norm = re.sub(r"\s+", " ", raw).strip().lower()
        digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:28]
        return f"spoken_body:{digest}"

    def _resolve_voice_scope_blocking(self, channel_id: str) -> str:
        """Stable per-call UUID for playback dedupe; avoids @chan:{id} vs real call_id splitting (double audio)."""
        cid = self.mapper.resolve_call_id_for_channel(channel_id)
        if cid:
            return cid
        try:
            fetched = self._get_channel_call_id(channel_id)
        except Exception:
            fetched = None
        if fetched:
            self.mapper.remember_call_id(channel_id, fetched)
            return fetched
        return f"@chan:{channel_id}"

    def _try_begin_playback_once(self, voice_scope: str, channel_id: str, playback_lane: str) -> bool:
        """Claim one playback of playback_lane under voice_scope; merge stray @chan bucket into real call UUID."""
        lane = str(playback_lane or "").strip() or "_"
        stale = f"@chan:{channel_id}"
        with self._ws_ivr_seen_lock:
            if voice_scope != stale and stale in self._ivr_play_once_by_call:
                migrating = self._ivr_play_once_by_call.pop(stale, set())
                if migrating:
                    into = self._ivr_play_once_by_call.setdefault(voice_scope, set())
                    into |= migrating
                    logger.info(
                        "IVR playback_once_scope_merged stale=%s into_prefix=%s lanes=%s",
                        stale[:32],
                        voice_scope[:20],
                        len(migrating),
                    )
            bucket = self._ivr_play_once_by_call.setdefault(voice_scope, set())
            if lane in bucket:
                logger.info(
                    "IVR playback_once_skip scope_prefix=%s lane=%s channel=%s",
                    voice_scope[:20],
                    lane[:96],
                    channel_id[:16],
                )
                return False
            bucket.add(lane)
            return True

    def clear_playback_once_state_for_call_id(self, call_id: str) -> None:
        if not call_id:
            return
        pref = f"{call_id}:"
        with self._ws_ivr_seen_lock:
            self._ivr_play_once_by_call.pop(call_id, None)
            self._answered_ivr_spawn_by_call.discard(call_id)
            self._ws_ivr_play_markers = {
                marker for marker in self._ws_ivr_play_markers if not str(marker).startswith(pref)
            }

    def _ws_prompt_is_duplicate(self, call_id: str, ws_type: str, event: dict[str, Any], ivr: Any) -> bool:
        """Return True if we've already handled this WebSocket prompt (skip replay / loops)."""
        if ws_type in _WS_IVR_VOICE_ONCE_PER_SESSION_ID:
            key = f"{call_id}:{ws_type}"
            with self._ws_ivr_seen_lock:
                if key in self._ws_ivr_play_markers:
                    return True
                self._ws_ivr_play_markers.add(key)
            return False
        ev_id = str(event.get("id") or "").strip()
        script = ""
        if isinstance(ivr, dict):
            script = str(ivr.get("speech_script_key") or ivr.get("prompt_key") or "")
        marker = f"evt:{ev_id}" if ev_id else f"fallback:{ws_type}:{script}"
        key = f"{call_id}:{marker}"
        with self._ws_ivr_seen_lock:
            if key in self._ws_ivr_play_markers:
                return True
            self._ws_ivr_play_markers.add(key)
        return False

    async def _finalize_terminal_hangup(
        self,
        channel_id: str,
        terminal_prompt_key: str,
        playback_finished_mono: Optional[float],
    ) -> None:
        post_ms = float(os.getenv("ASTERISK_POST_PROMPT_HANGUP_DELAY_MS", "200").strip() or "200")
        post_sec = max(0.05, min(5.0, post_ms / 1000.0))
        tail_sec = max(0.0, _read_prompt_tail_padding_ms() / 1000.0)
        t_before_sleep = time.perf_counter()
        await asyncio.sleep(post_sec + tail_sec)
        hang_timing_ms = (time.perf_counter() - t_before_sleep) * 1000.0
        since_play_ms = (
            (time.perf_counter() - playback_finished_mono) * 1000.0
            if playback_finished_mono is not None
            else None
        )
        exists = await asyncio.to_thread(self._channel_exists_quick, channel_id)
        if not exists:
            logger.warning(
                "IVR early_hangup_warning terminal_prompt_key=%s channel=%s "
                "hang_scheduled_pause_ms=%.1f elapsed_since_playback_finished_ms=%s",
                terminal_prompt_key[:48],
                channel_id[:16],
                hang_timing_ms,
                f"{since_play_ms:.1f}" if since_play_ms is not None else "n/a",
            )
            return
        await asyncio.to_thread(self._hangup_channel, channel_id)
        logger.info(
            "IVR hangup_after_playback terminal_prompt_key=%s channel=%s "
            "hang_scheduled_pause_ms=%.1f elapsed_since_playback_finished_ms=%s",
            terminal_prompt_key[:48],
            channel_id[:16],
            hang_timing_ms,
            f"{since_play_ms:.1f}" if since_play_ms is not None else "n/a",
        )

    def _log_ivr_timing(
        self,
        *,
        channel_id: str,
        phase: str,
        prompt_key: str = "",
        anchor_gen: Optional[int] = None,
        dtmf_at: Optional[float] = None,
        post_started_at: Optional[float] = None,
        post_completed_at: Optional[float] = None,
        playback_started_at: Optional[float] = None,
        next_prompt_started_at: Optional[float] = None,
        extra_ms: Optional[float] = None,
    ) -> None:
        now = time.perf_counter()
        pairs: dict[str, float] = {}
        if dtmf_at is not None:
            pairs["dtmf_to_now_ms"] = (now - dtmf_at) * 1000.0
        if post_started_at is not None and post_completed_at is not None:
            pairs["post_ms"] = (post_completed_at - post_started_at) * 1000.0
        if post_completed_at is not None and next_prompt_started_at is not None:
            pairs["to_next_prompt_ms"] = (next_prompt_started_at - post_completed_at) * 1000.0
        if post_completed_at is not None and playback_started_at is not None:
            pairs["to_play_start_ms"] = (playback_started_at - post_completed_at) * 1000.0
        if extra_ms is not None:
            pairs["extra_ms"] = extra_ms
        detail = " ".join(f"{k}={v:.1f}" for k, v in pairs.items())
        ag = "" if anchor_gen is None else f" gen={anchor_gen}"
        logger.info(
            "ivr_perf phase=%s channel=%s%s prompt_key=%s %s",
            phase,
            channel_id[:16],
            ag,
            (prompt_key or "")[:48],
            detail,
        )

    def _stop_channel_media_sync(self, channel_id: str) -> None:
        """Stop any live playback on the channel (barge-in / admin preempt)."""
        url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}/play")
        req = request.Request(url, method="DELETE", headers={"Authorization": self._basic_auth_header()})
        with self._http_channel_lock(channel_id):
            try:
                with request.urlopen(req, timeout=6):
                    logger.info(
                        "IVR channel playback DELETE channel=%s (stop/barge-in)",
                        channel_id[:16],
                    )
            except error.HTTPError as e:
                if e.code != 404:
                    logger.warning("IVR channel playback DELETE HTTP %s channel=%s", e.code, channel_id[:16])
            except Exception as e:
                logger.warning("IVR channel playback DELETE failed channel=%s: %s", channel_id[:16], e)

    def _interrupt_playback_barge_in_sync(self, channel_id: str, *, reason: str) -> None:
        self._cancel_active_playback_task(channel_id)
        self._playback_generation_bump(channel_id)
        self._stop_channel_media_sync(channel_id)
        logger.info("IVR barge-in channel=%s reason=%s", channel_id[:16], reason[:80])

    async def apply_spoken_prompt(
        self,
        channel_id: str,
        fallback_key: str,
        text: str,
        should_hangup: bool,
        *,
        preroll_ms: Optional[int] = None,
        log_prompt_key: Optional[str] = None,
        timing: Optional[dict[str, Any]] = None,
        prepend_initial_silence_ms: Optional[int] = None,
        speech_script_key: Optional[str] = None,
        first_call_prompt: bool = False,
    ) -> None:
        """Play synthesized or static prompts. Barge-in is handled via generation bumps + channel DELETE /play."""
        _ = speech_script_key  # dedupe lane uses normalized spoken text; callers may still pass the script key for API symmetry
        text = scrub_literal_speech_placeholders(text)
        lk = log_prompt_key or fallback_key
        ms = max(0, preroll_ms or 0)
        is_first = first_call_prompt or (log_prompt_key or fallback_key) in ("consent", "ivr/consent")
        if prepend_initial_silence_ms is not None:
            eff_prepend = max(0, prepend_initial_silence_ms)
        elif is_first:
            configured = max(0, getattr(self.config, "prompt_initial_silence_ms", 0))
            eff_prepend = max(configured, _read_spoken_min_lead_ms())
        else:
            eff_prepend = min(_read_spoken_min_lead_ms(), 380)

        channel_alive = await asyncio.to_thread(self._answer_channel, channel_id)
        play_finished_mono: Optional[float] = None

        if not channel_alive:
            logger.info(
                "Skipping spoken prompt playback on missing channel=%s fallback_key=%s",
                channel_id,
                fallback_key,
            )
            if should_hangup:
                logger.warning(
                    "IVR early_hangup_warning terminal_prompt_key=%s channel=%s reason=no_channel_before_spoken_prompt",
                    (log_prompt_key or fallback_key)[:48],
                    channel_id[:16],
                )
            return

        if first_call_prompt:
            rtp_settle_ms = max(0, int(os.getenv(IVR_POST_ANSWER_RTP_SETTLE_MS_ENV, "400") or "400"))
            if rtp_settle_ms:
                logger.info(
                    "IVR RTP settle wait channel=%s ms=%s prompt_key=%s",
                    channel_id[:16],
                    rtp_settle_ms,
                    lk,
                )
                anchor_settle = self._playback_generation_read(channel_id)
                await asyncio.sleep(rtp_settle_ms / 1000.0)
                if self._playback_generation_read(channel_id) != anchor_settle:
                    logger.info(
                        "IVR RTP settle aborted (superseded) channel=%s prompt_key=%s",
                        channel_id[:16],
                        lk,
                    )
                    return

        voice_scope = await asyncio.to_thread(self._resolve_voice_scope_blocking, channel_id)
        playback_lane = self._spoken_body_playback_lane(text, lk)
        if not self._try_begin_playback_once(voice_scope, channel_id, playback_lane):
            return

        await asyncio.to_thread(self._stop_channel_media_sync, channel_id)

        anchor = self._playback_generation_read(channel_id)
        silence = getattr(self.config, "prompt_preroll_silence_media", None)
        if ms > 0:
            logger.info(
                "IVR playback preroll channel=%s prompt_key=%s waiting_ms=%s anchor_gen=%s",
                channel_id[:16],
                lk,
                ms,
                anchor,
            )
            await asyncio.sleep(ms / 1000.0)
            if self._playback_generation_read(channel_id) != anchor:
                logger.info(
                    "IVR preroll aborted (superseded) channel=%s prompt_key=%s",
                    channel_id[:16],
                    lk,
                )
                return

        if silence and ms > 0:
            media = (
                silence
                if silence.startswith(("sound:", "tone:", "digits:", "number:"))
                else f"sound:{silence}"
            )
            logger.info(
                "IVR preroll silence channel=%s media=%s anchor_gen=%s",
                channel_id[:16],
                media[:80],
                anchor,
            )
            await asyncio.to_thread(
                self._play_media_string_wait,
                channel_id,
                media,
                lk + ":silence-preroll",
                anchor_gen_snapshot=anchor,
            )
            if self._playback_generation_read(channel_id) != anchor:
                return

        if timing is not None:
            mono = time.perf_counter()
            timing.setdefault("playback_started_at", mono)
            timing.setdefault("first_prompt_start_at", mono)

        if should_hangup:
            logger.info(
                "IVR terminal_prompt playback_started terminal_prompt_key=%s channel=%s mode=spoken_playback",
                lk[:48],
                channel_id[:16],
            )

        logger.info(
            "IVR playing prompt_key=%s channel=%s (spoken) anchor_gen=%s prepend_silence_ms=%s",
            lk,
            channel_id[:16],
            anchor,
            eff_prepend,
        )
        await asyncio.to_thread(
            self._tts_or_static_prompt_blocking,
            channel_id,
            fallback_key,
            text,
            lk,
            anchor_gen_snapshot=anchor,
            prepend_silence_ms=eff_prepend,
            prefer_static_if_cold=is_first,
        )
        play_finished_mono = time.perf_counter()
        if is_first:
            await asyncio.to_thread(self._warn_if_no_inbound_rtp, channel_id)
        elapsed_wall = ""
        if timing is not None and timing.get("playback_started_at"):
            elapsed_wall = f"{(play_finished_mono - float(timing['playback_started_at'])) * 1000.0:.1f}"
        if should_hangup:
            logger.info(
                "IVR terminal_prompt playback_finished terminal_prompt_key=%s channel=%s playback_wall_ms=%s mode=spoken",
                lk[:48],
                channel_id[:16],
                elapsed_wall or "n/a",
            )
            await self._finalize_terminal_hangup(channel_id, lk, play_finished_mono)

    async def apply_prompt_action(
        self,
        channel_id: str,
        prompt_key: Optional[str],
        should_hangup: bool,
        *,
        preroll_ms: Optional[int] = None,
        timing: Optional[dict[str, Any]] = None,
    ) -> None:
        play_finished_mono_inner: Optional[float] = None
        lk: str = ""

        if prompt_key:
            lk = prompt_key
            ms = max(0, preroll_ms or 0)
            silence = getattr(self.config, "prompt_preroll_silence_media", None)
            channel_alive = await asyncio.to_thread(self._answer_channel, channel_id)
            if not channel_alive:
                logger.info(
                    "Skipping playback for prompt %s on channel %s: channel no longer exists",
                    prompt_key,
                    channel_id,
                )
                if should_hangup:
                    logger.warning(
                        "IVR early_hangup_warning terminal_prompt_key=%s channel=%s reason=no_channel_before_media_terminal",
                        lk[:48],
                        channel_id[:16],
                    )
                return

            voice_scope = await asyncio.to_thread(self._resolve_voice_scope_blocking, channel_id)
            playback_lane = self._playback_once_lane(speech_script_key=None, fallback_logical=lk)
            if not self._try_begin_playback_once(voice_scope, channel_id, playback_lane):
                return

            await asyncio.to_thread(self._stop_channel_media_sync, channel_id)

            anchor = self._playback_generation_read(channel_id)
            if ms > 0:
                logger.info(
                    "IVR playback preroll channel=%s prompt_key=%s waiting_ms=%s anchor_gen=%s",
                    channel_id[:16],
                    lk,
                    ms,
                    anchor,
                )
                await asyncio.sleep(ms / 1000.0)
                if self._playback_generation_read(channel_id) != anchor:
                    logger.info(
                        "IVR preroll aborted (superseded) channel=%s prompt_key=%s",
                        channel_id[:16],
                        lk,
                    )
                    return

            if silence and ms > 0:
                media = (
                    silence
                    if silence.startswith(("sound:", "tone:", "digits:", "number:"))
                    else f"sound:{silence}"
                )
                await asyncio.to_thread(
                    self._play_media_string_wait,
                    channel_id,
                    media,
                    lk + ":silence-preroll",
                    anchor_gen_snapshot=anchor,
                )
                if self._playback_generation_read(channel_id) != anchor:
                    return

            if timing is not None:
                mono = time.perf_counter()
                timing.setdefault("playback_started_at", mono)
                timing.setdefault("first_prompt_start_at", mono)

            if should_hangup:
                logger.info(
                    "IVR terminal_prompt playback_started terminal_prompt_key=%s channel=%s mode=media_playback",
                    lk[:48],
                    channel_id[:16],
                )
            logger.info(
                "IVR playing prompt_key=%s channel=%s anchor_gen=%s",
                lk,
                channel_id[:16],
                anchor,
            )
            await asyncio.to_thread(
                self._play_prompt_blocking,
                channel_id,
                prompt_key,
                lk,
                anchor_gen_snapshot=anchor,
            )
            play_finished_mono_inner = time.perf_counter()

        if should_hangup and play_finished_mono_inner is not None:
            lk_log = lk if prompt_key else "hangup_followup"
            elapsed_wall = ""
            if timing is not None and timing.get("playback_started_at"):
                elapsed_wall = f"{(play_finished_mono_inner - float(timing['playback_started_at'])) * 1000.0:.1f}"
            logger.info(
                "IVR terminal_prompt playback_finished terminal_prompt_key=%s channel=%s playback_wall_ms=%s mode=media",
                lk_log[:48],
                channel_id[:16],
                elapsed_wall or "n/a",
            )
            await self._finalize_terminal_hangup(channel_id, lk_log[:48], play_finished_mono_inner)

    def prompt_for_backend_result(
        self,
        *,
        payload: dict[str, Any],
        backend_response: dict[str, Any],
    ) -> tuple[Optional[str], bool]:
        event_type = payload.get("event_type")
        if event_type == "ANSWERED":
            return "consent", False
        if event_type == "DTMF":
            step = backend_response.get("simulator_step")
            if backend_response.get("detail") == "pending_admin_verification":
                return "pending_admin", False
            if step == "waiting_admin_code_send":
                return "admin_instruction", False
            if step == "verification_code":
                return None, False
        if event_type == "FAILED":
            return "failed", True
        if event_type == "HANGUP":
            return None, False
        return None, False

    def prompt_for_backend_ws_event(self, event: dict[str, Any]) -> tuple[Optional[str], bool]:
        event_type = event.get("event_type")
        message = str(event.get("message") or "")
        if event_type == "ADMIN_VERIFICATION_APPROVED":
            return "approved", True
        if event_type == "ADMIN_CODE_SENT_CONFIRMED":
            return "code_sent", False
        if event_type == "VERIFICATION_SUCCESS":
            return None, False
        if event_type == "ADMIN_VERIFICATION_REJECTED":
            if "maximum attempts" in message.lower():
                return "declined", True
            return "rejected", False
        if event_type == "VERIFICATION_FAILED":
            return "failed", True
        return None, False

    async def run_forever(self) -> None:
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError("Install the 'websockets' package to run the SIP UP media bridge") from e

        while True:
            try:
                connect_kwargs = {
                    "ping_interval": 20,
                    "ping_timeout": 20,
                }
                header_arg = (
                    "additional_headers"
                    if "additional_headers" in inspect.signature(websockets.connect).parameters
                    else "extra_headers"
                )
                connect_kwargs[header_arg] = {"Authorization": self._basic_auth_header()}
                async with websockets.connect(
                    self._websocket_url(),
                    **connect_kwargs,
                ) as websocket:
                    logger.info(
                        "SIP UP media websocket connected bridge_instance=%s pid=%s app=%s host=%s port=%s",
                        self.bridge_instance_id,
                        os.getpid(),
                        self.config.app,
                        self.config.host,
                        self.config.port,
                    )
                    backend_task = None
                    ws_tok_present = bool((self.config.backend_ws_token or "").strip())
                    if self.config.backend_ws_url and ws_tok_present:
                        logger.info(
                            "ARI bridge starting backend_ws listener for prompt preemption app=%s",
                            self.config.app,
                        )
                        backend_task = asyncio.create_task(self.run_backend_websocket())
                    try:
                        async for message in websocket:
                            await self.handle_raw_message(message)
                    finally:
                        if backend_task is not None:
                            backend_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await backend_task
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("SIP UP media bridge disconnected: %s", e)
                await asyncio.sleep(3)

    async def handle_raw_message(self, message: str) -> Optional[dict[str, Any]]:
        event = json.loads(message)
        event_type = str(event.get("type") or "")
        payload = self.mapper.map_event(event)
        if payload is None:
            channel_id = self.mapper._channel_id(event)
            if channel_id:
                call_id = await asyncio.to_thread(self._get_channel_call_id, channel_id)
                if call_id:
                    payload = self.mapper.map_event(event, call_id_override=call_id)
            if payload is None and event_type == "ChannelDtmfReceived":
                digit = self.mapper._dtmf_digit(event)
                logger.warning(
                    "ARI ChannelDtmfReceived dropped (no call_id mapping) channel=%s digit=%s "
                    "— check CALL_ID channel var / bridge channel map",
                    (channel_id or "")[:16],
                    digit or "?",
                )
                return None
        if payload is not None:
            channel_id = str(payload["provider_call_id"])
            timing: dict[str, Any] = {}
            if payload.get("event_type") == "ANSWERED":
                timing["answered_at"] = time.perf_counter()

            if payload.get("event_type") == "DTMF":
                timing["dtmf_received_at"] = time.perf_counter()
                await asyncio.to_thread(
                    self._interrupt_playback_barge_in_sync,
                    channel_id,
                    reason=f"dtmf digit={payload.get('digit')}",
                )
                logger.info(
                    "DTMF received digit=%s call_id=%s channel=%s (playback stopped for barge-in)",
                    payload.get("digit"),
                    payload.get("call_id"),
                    channel_id[:16],
                )

            timing["backend_post_started_at"] = time.perf_counter()
            try:
                backend_response = await asyncio.to_thread(self._post_backend_event, payload)
            except Exception as e:
                logger.error(
                    "Failed to post telephony event %s to backend: %s. Continuing call session.",
                    payload.get("event_type"),
                    e,
                )
                backend_response = {}
            timing["backend_post_completed_at"] = time.perf_counter()

            if isinstance(backend_response, dict):
                if backend_response.get("status") == "duplicate_ignored":
                    logger.info(
                        "telephony webhook duplicate_ignored provider=%s channel=%s",
                        payload.get("provider"),
                        channel_id[:16],
                    )
                    return payload
                ivr_pre = backend_response.get("ivr_speech")
                has_iv = isinstance(ivr_pre, dict) and bool((ivr_pre.get("text") or "").strip())
                if backend_response.get("noop") and not has_iv:
                    logger.info(
                        "telephony webhook noop skipping playback channel=%s detail=%s",
                        channel_id[:16],
                        (backend_response.get("detail") or "")[:160],
                    )
                    return payload

            if payload.get("event_type") == "DTMF":
                dtmf_mono = timing.get("dtmf_received_at")
                post_done = timing.get("backend_post_completed_at")
                if isinstance(dtmf_mono, float) and isinstance(post_done, float):
                    self._log_ivr_timing(
                        channel_id=channel_id,
                        phase="dtmf_backend",
                        prompt_key=str(payload.get("digit") or ""),
                        dtmf_at=dtmf_mono,
                        post_started_at=timing.get("backend_post_started_at"),
                        post_completed_at=post_done,
                    )

            if isinstance(backend_response, dict) and backend_response.get("detail") == "invalid_consent_digit":
                voice_scope = await asyncio.to_thread(self._resolve_voice_scope_blocking, channel_id)
                with self._ws_ivr_seen_lock:
                    bucket = self._ivr_play_once_by_call.get(voice_scope)
                    if bucket is not None:
                        to_remove = {lane for lane in bucket if "consent" in lane or "spoken_body" in lane or "script:consent" in lane}
                        bucket -= to_remove

            prompt_key, should_hangup = self.prompt_for_backend_result(
                payload=payload,
                backend_response=backend_response,
            )
            if isinstance(backend_response, dict):
                logger.info(
                    "IVR backend response step=%s prompt_key=%s hangup=%s",
                    backend_response.get("simulator_step"),
                    prompt_key,
                    should_hangup,
                )
            ivr = backend_response.get("ivr_speech") if isinstance(backend_response, dict) else None

            preroll = self.config.prompt_preroll_ms if payload.get("event_type") == "ANSWERED" else 0
            spawn = payload.get("event_type") == "ANSWERED"
            is_first_call_prompt = payload.get("event_type") == "ANSWERED"

            async def _playback_task() -> None:
                cur_task = asyncio.current_task()
                if cur_task is not None:
                    self._playback_tasks[channel_id] = cur_task
                try:
                    timing["next_prompt_started_at"] = time.perf_counter()
                    fk_local = ""
                    if isinstance(ivr, dict) and (ivr.get("text") or "").strip():
                        fk_local = str(ivr.get("prompt_key") or prompt_key or "consent")
                        s_raw = ivr.get("speech_script_key")
                        script_sk = str(s_raw).strip() if s_raw else None
                        await self.apply_spoken_prompt(
                            channel_id,
                            fk_local,
                            str(ivr["text"]).strip(),
                            should_hangup,
                            preroll_ms=preroll,
                            log_prompt_key=fk_local,
                            timing=timing,
                            speech_script_key=script_sk,
                            first_call_prompt=is_first_call_prompt,
                        )
                    elif prompt_key:
                        await self.apply_prompt_action(
                            channel_id, prompt_key, should_hangup, preroll_ms=preroll, timing=timing
                        )
                    elif should_hangup:
                        await self._finalize_terminal_hangup(channel_id, "immediate_hangup", None)
                    post_done = timing.get("backend_post_completed_at")
                    play_start = timing.get("playback_started_at")
                    next_start = timing.get("next_prompt_started_at")
                    pk = prompt_key or fk_local
                    if isinstance(post_done, float) and isinstance(play_start, float) and isinstance(next_start, float):
                        self._log_ivr_timing(
                            channel_id=channel_id,
                            phase="prompt_chain",
                            prompt_key=str(pk or ""),
                            post_completed_at=post_done,
                            playback_started_at=play_start,
                            next_prompt_started_at=next_start,
                        )
                except asyncio.CancelledError:
                    logger.info("IVR playback task cancelled channel=%s", channel_id[:16])
                    raise
                except Exception as e:
                    logger.warning(
                        "ARI playback dispatch failed safely channel=%s: %s",
                        channel_id[:16],
                        e,
                    )
                finally:
                    if self._playback_tasks.get(channel_id) == cur_task:
                        self._playback_tasks.pop(channel_id, None)

            if spawn:
                spawn_key = str(payload.get("call_id") or "").strip() or channel_id
                do_spawn = False
                with self._ws_ivr_seen_lock:
                    if spawn_key not in self._answered_ivr_spawn_by_call:
                        self._answered_ivr_spawn_by_call.add(spawn_key)
                        do_spawn = True
                    else:
                        logger.info(
                            "IVR answered_playback_already_enqueued call_prefix=%s channel=%s (no duplicate enqueue)",
                            spawn_key[:20],
                            channel_id[:16],
                        )
                if do_spawn:
                    task = asyncio.create_task(_playback_task())
                    self._playback_tasks[channel_id] = task
            else:
                await _playback_task()

            et = payload.get("event_type")
            if et in {"HANGUP", "FAILED"}:
                clr = str(payload.get("call_id") or "").strip()
                if clr:
                    self.clear_playback_once_state_for_call_id(clr)
                    clear_call_cache(clr)
        return payload

    async def handle_backend_ws_broadcast(
        self,
        data: dict[str, Any],
        *,
        ws_received_mono: Optional[float] = None,
    ) -> None:
        """Apply one backend fan-out websocket payload (call_event + optional ivr_speech).

        Covered by unit tests — keep idempotent playback rules here in sync with run_backend_websocket.
        """
        ws_received_mono = time.perf_counter() if ws_received_mono is None else ws_received_mono
        event = data.get("event")
        if not event:
            return
        session_id_raw = str(event.get("session_id") or "")
        session_prefix = session_id_raw[:8] + "…" if session_id_raw else ""
        ws_type = str(data.get("type") or "")
        ev_type = str(event.get("event_type") or "")
        channel_id = self.mapper.call_channels.get(session_id_raw) or self._channel_for_call_id(
            session_id_raw
        )
        admin_code = ws_type == CallEventType.ADMIN_CODE_SENT_CONFIRMED.value

        if session_id_raw and (
            ws_type
            in {
                CallEventType.CALL_CREATED.value,
                CallEventType.CALL_INITIATED.value,
            }
            or ev_type
            in {
                CallEventType.CALL_CREATED.value,
                CallEventType.CALL_INITIATED.value,
            }
        ):
            schedule_luvvoice_prefetch(session_id_raw)

        if not channel_id:
            if admin_code:
                logger.error(
                    "No active channel for code_sent_prompt call_id=%s event_type=%s bridge_instance=%s",
                    session_id_raw or "(missing)",
                    ev_type,
                    self.bridge_instance_id,
                )
            else:
                logger.warning(
                    "ARI WS event dropped (no active channel mapping) session_prefix=%s type=%s",
                    session_prefix,
                    ws_type,
                )
            return

        # Operator / dashboard end-call: tear down the live Asterisk channel (session already terminal).
        if ws_type == CallEventType.CALL_HANGUP.value or ev_type == CallEventType.CALL_HANGUP.value:
            logger.info(
                "ARI WS operator hangup channel=%s session_prefix=%s",
                channel_id[:16],
                session_prefix,
            )
            await asyncio.to_thread(
                self._interrupt_playback_barge_in_sync,
                channel_id,
                reason="ws:CALL_HANGUP",
            )
            await self._finalize_terminal_hangup(channel_id, "operator_hangup", None)
            if session_id_raw:
                self.clear_playback_once_state_for_call_id(session_id_raw)
                clear_call_cache(session_id_raw)
            return

        if ws_type in _WS_SKIP_FANOUT_PROMPT_PLAYBACK:
            logger.info(
                "ARI WS skipping ivr playback (telephony webhook is canonical on bridge) "
                "session_prefix=%s type=%s channel=%s",
                session_prefix,
                ws_type,
                channel_id[:16],
            )
            return
        if ws_type == "call_event":
            nested = str(event.get("event_type") or "")
            if nested in _WS_SKIP_FANOUT_PROMPT_PLAYBACK and isinstance(data.get("ivr_speech"), dict):
                logger.info(
                    "ARI WS skipping ivr (nested call_event replays webhook-canonical prompt) "
                    "nested_event=%s channel=%s session_prefix=%s",
                    nested,
                    channel_id[:16],
                    session_prefix,
                )
                return
        if ws_type == CallEventType.PENDING_ADMIN_VERIFICATION.value:
            # Same prompt was already dispatched from handle_raw_message→telephony webhook
            # after digit 6; playing again here repeats "please wait for the administrator…".
            logger.info(
                "ARI WS skipping pending-admin ivr playback (canonical path=telephony webhook) "
                "session_prefix=%s channel=%s",
                session_prefix,
                channel_id[:16],
            )
            return
        prompt_key, should_hangup = self.prompt_for_backend_ws_event(event)
        ivr = data.get("ivr_speech")
        if admin_code:
            ivr_dbg = ivr if isinstance(ivr, dict) else {}
            has_spoken = isinstance(ivr, dict) and bool((str(ivr.get("text") or "").strip()))
            logger.info(
                "code_sent_ws_received ws_wall_utc=%s call_id=%s step=verification_code "
                "event_type=%s prompt_key_static=%s speech_script_key=%s has_spoken_iv=%s "
                "active_channel_found=yes channel_prefix=%s bridge_instance=%s",
                datetime.now(timezone.utc).isoformat(),
                session_id_raw,
                ev_type,
                prompt_key or "",
                (ivr_dbg.get("speech_script_key") or "")[:40],
                has_spoken,
                channel_id[:16],
                self.bridge_instance_id,
            )
        needs_playback = (
            (isinstance(ivr, dict) and bool((ivr.get("text") or "").strip()))
            or bool(prompt_key)
            or should_hangup
        )
        is_dup = needs_playback and self._ws_prompt_is_duplicate(session_id_raw, ws_type, event, ivr)
        if is_dup:
            if admin_code:
                logger.info(
                    "Skipping duplicate prompt playback duplicate_prompt=yes call_id=%s "
                    "step=verification_code prompt=code_sent_prompt "
                    "event_id_prefix=%s bridge_instance=%s",
                    session_id_raw,
                    str(event.get("id") or "")[:12] or "(none)",
                    self.bridge_instance_id,
                )
            else:
                logger.info(
                    "IVR duplicate_prompt_skipped session_prefix=%s ws_type=%s event_id_prefix=%s",
                    session_prefix,
                    ws_type,
                    str(event.get("id") or "")[:12],
                )
            return
        ws_timing: dict[str, Any] = {"ws_received_mono": ws_received_mono}
        interrupt_old = False
        interrupt_ms: Optional[float] = None
        if needs_playback:
            await asyncio.to_thread(
                self._interrupt_playback_barge_in_sync,
                channel_id,
                reason=f"ws:{ws_type}",
            )
            interrupt_old = True
            t_after_interrupt = time.perf_counter()
            interrupt_ms = (t_after_interrupt - ws_received_mono) * 1000.0
        if isinstance(ivr, dict) and (ivr.get("text") or "").strip():
            fk = str(ivr.get("prompt_key") or prompt_key or "consent")
            txt = str(ivr["text"]).strip()
            ws_audio_mode = os.getenv(
                "ASTERISK_ADMIN_CODE_SENT_AUDIO_MODE",
                "tts",
            ).strip().lower()
            if admin_code and ws_audio_mode == "sip_up":
                logger.info(
                    "ARI WS code_sent_using_prerecorded channel=%s prompt_key_static=%s",
                    channel_id[:16],
                    (prompt_key or "code_sent"),
                )
                await self.apply_prompt_action(
                    channel_id,
                    str(prompt_key or "code_sent"),
                    should_hangup,
                    timing=ws_timing,
                )
            else:
                logger.info(
                    "ARI WS playing spoken ivr prompt channel=%s ari_prompt_key=%s chars=%s",
                    channel_id[:16],
                    fk[:32],
                    len(txt),
                )
                s_raw = ivr.get("speech_script_key")
                sk = str(s_raw).strip() if s_raw else None
                await self.apply_spoken_prompt(
                    channel_id,
                    fk,
                    txt,
                    should_hangup,
                    timing=ws_timing,
                    speech_script_key=sk,
                )
        elif prompt_key:
            logger.info(
                "ARI WS playing static/media prompt channel=%s key=%s hangup_after=%s",
                channel_id[:16],
                prompt_key,
                should_hangup,
            )
            await self.apply_prompt_action(
                channel_id, prompt_key, should_hangup, timing=ws_timing
            )
        elif should_hangup:
            await self._finalize_terminal_hangup(channel_id, "ws_hangup_followup", None)

        if admin_code and needs_playback:
            pb = ws_timing.get("playback_started_at")
            if isinstance(pb, float):
                elapsed = (pb - ws_received_mono) * 1000.0
                logger.info(
                    "code_sent_prompt_playback_handled call_id=%s step=verification_code "
                    "event_type=%s prompt_key=code_sent_prompt active_channel_found=yes "
                    "interrupt_old_playback=%s interrupt_elapsed_ms=%.1f "
                    "playback_started_at_mono=%s elapsed_ms_ws_to_playback_start=%.1f "
                    "duplicate_prompt=no bridge_instance=%s",
                    session_id_raw,
                    ev_type,
                    "yes" if interrupt_old else "no",
                    interrupt_ms or 0.0,
                    pb,
                    elapsed,
                    self.bridge_instance_id,
                )

    async def run_backend_websocket(self) -> None:
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError("Install the 'websockets' package to run backend WebSocket prompt actions") from e

        url = self._backend_ws_url_with_token()
        logger.info(
            "ARI backend WS subscriber connecting for admin-driven prompts endpoint_has_token=%s",
            "token=" in url,
        )
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as websocket:
                    logger.info(
                        "ARI backend WS subscribed bridge_instance=%s pid=%s channel_map_entries=%s "
                        "(single instance: ps aux | grep run_sip_up_ari_bridge | grep -v grep)",
                        self.bridge_instance_id,
                        os.getpid(),
                        len(self.mapper.call_channels),
                    )
                    async for message in websocket:
                        data = json.loads(message)
                        await self.handle_backend_ws_broadcast(
                            data,
                            ws_received_mono=time.perf_counter(),
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Backend WebSocket prompt listener disconnected: %s", e)
                await asyncio.sleep(3)

    def _websocket_url(self) -> str:
        query = {
            "app": self.config.app,
        }
        if self.config.subscribe_all:
            query["subscribeAll"] = "true"
        prefix = "/" + self.config.ari_prefix.strip("/")
        return f"ws://{self.config.host}:{self.config.port}{prefix}/events?{parse.urlencode(query)}"

    def _http_url(self, path: str, query: Optional[dict[str, str]] = None) -> str:
        suffix = path if path.startswith("/") else f"/{path}"
        prefix = "/" + self.config.ari_prefix.strip("/")
        url = f"http://{self.config.host}:{self.config.port}{prefix}{suffix}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        return url

    def _basic_auth_header(self) -> str:
        raw = f"{self.config.username}:{self.config.password}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _backend_ws_url_with_token(self) -> str:
        assert self.config.backend_ws_url
        assert self.config.backend_ws_token
        separator = "&" if "?" in self.config.backend_ws_url else "?"
        return f"{self.config.backend_ws_url}{separator}token={parse.quote(self.config.backend_ws_token)}"

    def _get_channel_call_id(self, channel_id: str) -> Optional[str]:
        for variable in CALL_ID_VARIABLE_NAMES:
            url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}/variable", {"variable": variable})
            req = request.Request(url, headers={"Authorization": self._basic_auth_header()})
            try:
                with request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8") or "{}")
                    value = data.get("value")
                    if value:
                        self.mapper.remember_call_id(channel_id, str(value))
                        return str(value)
            except error.HTTPError as e:
                if e.code == 404:
                    continue
                logger.warning("Could not read ARI channel variable %s for channel %s: HTTP %s", variable, channel_id, e.code)
            except Exception as e:
                logger.warning("Could not read ARI channel variable %s for channel %s: %s", variable, channel_id, e)
        return None

    def _channel_for_call_id(self, call_id: str) -> Optional[str]:
        return self.mapper.call_channels.get(call_id)

    def _resolve_speech_prefs_blocking(self, channel_id: str) -> tuple[str, Optional[str], int]:
        call_id = self._resolve_voice_scope_blocking(channel_id)
        if call_id.startswith("@chan:"):
            from ..speech_volume import DEFAULT_SPEECH_VOLUME_PERCENT

            return "luvvoice", luvvoice_tts.default_voice_id(), DEFAULT_SPEECH_VOLUME_PERCENT
        return get_session_speech_prefs(call_id)

    def _tts_or_static_prompt_blocking(
        self,
        channel_id: str,
        fallback_key: str,
        text: str,
        prompt_key_for_log: str,
        *,
        anchor_gen_snapshot: int,
        prepend_silence_ms: int = 0,
        prefer_static_if_cold: bool = False,
    ) -> None:
        if os.getenv("DISABLE_ARI_SPEECH_TTS", "").strip().lower() in {"1", "true", "yes"}:
            lead = max(0, int(prepend_silence_ms or 0))
            if lead:
                logger.info(
                    "IVR TTS-disabled lead-in silence channel=%s prompt_key=%s sleep_ms=%s",
                    channel_id[:16],
                    prompt_key_for_log[:48],
                    lead,
                )
                time.sleep(lead / 1000.0)
            if self._playback_generation_read(channel_id) != anchor_gen_snapshot:
                return
            self._play_prompt_blocking(
                channel_id,
                fallback_key,
                prompt_key_for_log,
                anchor_gen_snapshot=anchor_gen_snapshot,
            )
            return

        slug = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        container = os.getenv("ASTERISK_CONTAINER_NAME", "ivr-asterisk-dev").strip() or "ivr-asterisk-dev"
        fd, tmp_base = tempfile.mkstemp(prefix="ivr-tts-", suffix=".base")
        os.close(fd)
        wav_path = tmp_base + ".wav"
        aiff_path = tmp_base + ".aiff"
        speech_engine, luvvoice_voice_id, volume_percent = self._resolve_speech_prefs_blocking(
            channel_id
        )
        call_id = self._resolve_voice_scope_blocking(channel_id)
        if call_id.startswith("@chan:"):
            call_id = ""
        voice_id = (luvvoice_voice_id or luvvoice_tts.default_voice_id()).strip()
        try:
            wait_ms = read_cache_wait_ms()
            synth_ok = wait_for_cached_wav(
                call_id,
                text,
                speech_engine=speech_engine,
                luvvoice_voice_id=voice_id,
                volume_percent=volume_percent,
                dest_wav_path=wav_path,
                wait_ms=wait_ms,
            )
            if not synth_ok and prefer_static_if_cold and _cold_static_fallback_enabled():
                # Cold LuvVoice after answer causes ~10s dead air; callers hang up and
                # playback then hits ARI 404 Channel not found. Prefer audible static.
                logger.warning(
                    "IVR TTS cache cold after wait_ms=%s; static fallback key=%s channel=%s "
                    "(set %s=0 to force blocking LuvVoice synth)",
                    wait_ms,
                    fallback_key,
                    channel_id[:16],
                    IVR_TTS_COLD_STATIC_FALLBACK_ENV,
                )
                self._play_prompt_blocking(
                    channel_id,
                    fallback_key,
                    prompt_key_for_log,
                    anchor_gen_snapshot=anchor_gen_snapshot,
                )
                return
            if not synth_ok:
                synth_ok = synthesize_spoken_wav_singleflight(
                    text,
                    wav_path,
                    aiff_path=aiff_path,
                    speech_engine=speech_engine,
                    luvvoice_voice_id=luvvoice_voice_id,
                    volume_percent=volume_percent,
                    call_id=call_id,
                )
            if not synth_ok:
                logger.info("TTS synth unavailable — static Asterisk clip key=%s", fallback_key)
                self._play_prompt_blocking(
                    channel_id,
                    fallback_key,
                    prompt_key_for_log,
                    anchor_gen_snapshot=anchor_gen_snapshot,
                )
                return
            wav_bytes = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
            wav_ms = wav_duration_ms(wav_path)
            logger.info(
                "IVR synthesized WAV channel=%s prompt_key=%s bytes=%s duration_ms=%s engine=%s",
                channel_id[:16],
                prompt_key_for_log[:48],
                wav_bytes,
                f"{wav_ms:.0f}" if wav_ms is not None else "?",
                speech_engine,
            )
            if wav_ms is not None and wav_ms < 400:
                logger.warning(
                    "IVR synthesized WAV unusually short channel=%s prompt_key=%s duration_ms=%.0f",
                    channel_id[:16],
                    prompt_key_for_log[:48],
                    wav_ms,
                )
            if self._playback_generation_read(channel_id) != anchor_gen_snapshot:
                logger.info(
                    "IVR abort TTS (superseded) after synth prompt_key=%s channel=%s",
                    prompt_key_for_log[:48],
                    channel_id[:16],
                )
                return
            lead_ms = max(0, int(prepend_silence_ms or 0))
            if lead_ms:
                try:
                    _prepend_silence_pcm_wav_inplace(wav_path, lead_ms)
                    logger.info(
                        "IVR prepended synthesized lead-in silence channel=%s prompt_key=%s ms=%s",
                        channel_id[:16],
                        prompt_key_for_log[:48],
                        lead_ms,
                    )
                except Exception as exc:
                    logger.warning(
                        "IVR could not prepend lead-in silence channel=%s: %s",
                        channel_id[:16],
                        exc,
                    )
            if not _install_dyn_wav_blocking(slug, wav_path, container=container):
                logger.warning("IVR dyn WAV install failed; static fallback key=%s", fallback_key)
                self._play_prompt_blocking(
                    channel_id,
                    fallback_key,
                    prompt_key_for_log,
                    anchor_gen_snapshot=anchor_gen_snapshot,
                )
                return
            if self._playback_generation_read(channel_id) != anchor_gen_snapshot:
                return
            played = self._play_media_string_wait(
                channel_id,
                f"sound:ivr/dyn/{slug}",
                prompt_key_for_log,
                anchor_gen_snapshot=anchor_gen_snapshot,
            )
            if not played:
                logger.warning("IVR dyn playback failed; static fallback key=%s", fallback_key)
                self._play_prompt_blocking(
                    channel_id,
                    fallback_key,
                    prompt_key_for_log,
                    anchor_gen_snapshot=anchor_gen_snapshot,
                )
        finally:
            for p in (wav_path, aiff_path):
                with contextlib.suppress(OSError):
                    if os.path.exists(p):
                        os.remove(p)
            with contextlib.suppress(OSError):
                if os.path.exists(tmp_base):
                    os.remove(tmp_base)

    def _playback_rest_start(self, channel_id: str, media: str) -> Optional[str]:
        with self._http_channel_lock(channel_id):
            url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}/play", {"media": media})
            req = request.Request(url, method="POST", headers={"Authorization": self._basic_auth_header()})
            try:
                with request.urlopen(req, timeout=8) as resp:
                    body = resp.read().decode("utf-8", errors="replace") or "{}"
                    if resp.status >= 400:
                        logger.warning(
                            "IVR playback start HTTP status=%s channel=%s (%s)",
                            resp.status,
                            channel_id[:16],
                            media[:96],
                        )
                        return None
                    pdata = json.loads(body)
                    pid = str(pdata.get("id") or "").strip()
                    logger.info(
                        "IVR ARI playback rest started channel=%s playback_id=%s",
                        channel_id[:16],
                        pid or "missing",
                    )
                    return pid or None
            except error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    pass
                logger.warning(
                    "IVR playback start HTTP error %s on channel %s for media %s: %s",
                    e.code,
                    channel_id[:16],
                    media[:96],
                    body,
                )
            except Exception as e:
                logger.warning("Could not start Asterisk audio on channel %s: %s", channel_id[:16], e)
            return None

    def _wait_playback_finished(
        self,
        playback_id: str,
        channel_id: str,
        prompt_key_for_log: str,
        anchor_gen_snapshot: int,
    ) -> None:
        """Block until Asterisk destroys the Playback resource or generation changes (stale)."""
        deadline = time.monotonic() + 180.0
        quoted = parse.quote(playback_id, safe="")
        while time.monotonic() < deadline:
            if self._playback_generation_read(channel_id) != anchor_gen_snapshot:
                logger.info(
                    "IVR playback finished (superseded / barge-in) prompt_key=%s channel=%s",
                    prompt_key_for_log[:48],
                    channel_id[:16],
                )
                return
            url = self._http_url(f"/playbacks/{quoted}")
            req = request.Request(url, headers={"Authorization": self._basic_auth_header()})
            try:
                with request.urlopen(req, timeout=5) as resp:
                    pdata = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                    state = str(pdata.get("state") or "").lower()
                    if state in {"playing", "queued", "continuing"}:
                        time.sleep(0.08)
                        continue
                    logger.info(
                        "IVR playback finished prompt_key=%s channel=%s state=%s",
                        prompt_key_for_log[:48],
                        channel_id[:16],
                        state or "unknown",
                    )
                    return
            except error.HTTPError as e:
                if e.code == 404:
                    if self._playback_generation_read(channel_id) == anchor_gen_snapshot:
                        logger.info(
                            "IVR playback finished prompt_key=%s channel=%s (playback object gone)",
                            prompt_key_for_log[:48],
                            channel_id[:16],
                        )
                    return
                logger.warning("IVR playback poll HTTP %s playback_id=%s", e.code, playback_id[:12])
            except Exception as e:
                logger.warning("IVR playback poll error: %s", e)
            time.sleep(0.08)

        logger.warning(
            "IVR playback wait timed out prompt_key=%s playback_id_prefix=%s",
            prompt_key_for_log[:48],
            playback_id[:16],
        )

    def _play_media_string_wait(
        self,
        channel_id: str,
        media: str,
        prompt_key_for_log: str,
        *,
        anchor_gen_snapshot: int,
    ) -> bool:
        if self._playback_generation_read(channel_id) != anchor_gen_snapshot:
            logger.info(
                "IVR skip play start stale prompt_key=%s channel=%s",
                prompt_key_for_log[:48],
                channel_id[:16],
            )
            return False
        playback_id = self._playback_rest_start(channel_id, media)
        if playback_id:
            self._wait_playback_finished(playback_id, channel_id, prompt_key_for_log, anchor_gen_snapshot)
            return True
        logger.warning(
            "IVR playback start failed prompt_key=%s channel=%s media=%s",
            prompt_key_for_log[:48],
            channel_id[:16],
            media[:96],
        )
        return False

    def _play_prompt_blocking(
        self,
        channel_id: str,
        prompt_key: str,
        prompt_key_for_log: Optional[str] = None,
        *,
        anchor_gen_snapshot: int,
    ) -> None:
        lk = prompt_key_for_log or prompt_key
        prompts = self.config.prompts or DEFAULT_PROMPTS
        sound = prompts.get(prompt_key)
        if not sound:
            logger.warning(
                "No prompt mapping for key %s; skipping playback on channel %s",
                prompt_key,
                channel_id[:16],
            )
            return
        media = sound if sound.startswith("sound:") else f"sound:{sound}"
        self._play_media_string_wait(channel_id, media, lk, anchor_gen_snapshot=anchor_gen_snapshot)

    def _play_media_string(self, channel_id: str, media: str) -> None:
        """Non-waiting start (compat); prefers wait path for new code."""
        self._playback_rest_start(channel_id, media)

    def _answer_channel(self, channel_id: str) -> bool:
        """Answer the channel via ARI.

        Returns True if the channel is alive and either was answered or is already
        answered (HTTP 2xx or 409). Returns False when the channel no longer exists
        (HTTP 404), so callers can skip subsequent operations like playback.
        """
        url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}/answer")
        req = request.Request(url, method="POST", headers={"Authorization": self._basic_auth_header()})
        try:
            with request.urlopen(req, timeout=5) as resp:
                if resp.status < 300:
                    logger.info(
                        "channel answered (ARI) channel=%s",
                        channel_id[:16],
                    )
                    return True
        except error.HTTPError as e:
            if e.code == 404:
                return False
            if e.code == 409:
                logger.info(
                    "channel answered (ARI, already-up) channel=%s",
                    channel_id[:16],
                )
                # Already answered / in valid-but-non-answerable state — channel is alive.
                return True
            logger.warning("ARI Answer returned HTTP %s on channel %s", e.code, channel_id)
        except Exception as e:
            logger.warning("Could not answer channel %s via ARI: %s", channel_id, e)
        return True

    def _hangup_channel(self, channel_id: str) -> None:
        url = self._http_url(f"/channels/{parse.quote(channel_id, safe='')}")
        req = request.Request(url, method="DELETE", headers={"Authorization": self._basic_auth_header()})
        try:
            with request.urlopen(req, timeout=8):
                return
        except error.HTTPError as e:
            if e.code == 404:
                return
            raise

    def _fetch_live_public_ip(self) -> Optional[str]:
        for url in ("https://ifconfig.me/ip", "https://api.ipify.org"):
            try:
                req = request.Request(url, headers={"User-Agent": "ivr-bridge/1.0"})
                with request.urlopen(req, timeout=5) as resp:
                    ip = resp.read().decode("utf-8").strip()
                    if ip:
                        return ip
            except Exception:
                continue
        return None

    def _read_asterisk_externaddr(self, container: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["docker", "exec", container, "grep", "-E", "^externaddr=", "/etc/asterisk/rtp.conf"],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
        except Exception:
            return None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("externaddr="):
                return line.split("=", 1)[1].strip() or None
        return None

    def _warn_if_no_inbound_rtp(self, channel_id: str) -> None:
        """Log a clear warning when SIP UP return RTP is missing (RFC4733 DTMF cannot work)."""
        container = os.getenv("ASTERISK_CONTAINER_NAME", "ivr-asterisk-dev").strip() or "ivr-asterisk-dev"
        externaddr = self._read_asterisk_externaddr(container)
        try:
            proc = subprocess.run(
                ["docker", "exec", container, "asterisk", "-rx", "pjsip show channelstats"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except Exception as e:
            logger.debug("IVR RTP health check skipped channel=%s err=%s", channel_id[:16], e)
            return
        out = (proc.stdout or "") + (proc.stderr or "")
        rx_total = 0
        matched = False
        codecs = {"ulaw", "alaw", "g722", "g729", "opus", "slin", "slin16"}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0] in {"BridgeId", "===="}:
                continue
            for idx, tok in enumerate(parts):
                if tok.lower() in codecs and idx + 1 < len(parts) and parts[idx + 1].isdigit():
                    rx_total += int(parts[idx + 1])
                    matched = True
                    break
        if matched and rx_total <= 0:
            extern_note = f" externaddr={externaddr}" if externaddr else ""
            live_ip = self._fetch_live_public_ip()
            ip_mismatch = bool(
                externaddr and live_ip and externaddr != live_ip
            )
            if ip_mismatch:
                logger.warning(
                    "IVR inbound RTP is ZERO channel=%s — public IP mismatch: Asterisk advertises "
                    "externaddr=%s but live public IP is %s. SIP UP sends return RTP to the wrong "
                    "address. Update infra/sipup/.env ASTERISK_EXTERNAL_IP=%s then run: "
                    "cd infra/sipup && docker compose up -d --force-recreate. "
                    "Or run: .\\infra\\sipup\\scripts\\fix-rtp-dtmf.ps1",
                    channel_id[:16],
                    externaddr,
                    live_ip,
                    live_ip,
                )
            else:
                logger.warning(
                    "IVR inbound RTP is ZERO channel=%s%s — RFC4733 DTMF cannot arrive (SIP UP uses "
                    "telephone-event in RTP, not SIP INFO). Fix: (1) run infra/sipup/scripts/open-rtp-firewall.ps1 "
                    "as Admin, (2) router port-forward UDP 10000-10100 to this PC's LAN IP (192.168.x.x), "
                    "(3) if your ISP IP changed, run .\\infra\\sipup\\scripts\\fix-rtp-dtmf.ps1. "
                    "Verify during a call: docker exec %s asterisk -rx \"pjsip show channelstats\" "
                    "(Receive Count must be > 0).",
                    channel_id[:16],
                    extern_note,
                    container,
                )
        elif matched:
            logger.info(
                "IVR inbound RTP ok channel=%s rx_packets≈%s (DTMF path alive)",
                channel_id[:16],
                rx_total,
            )

    def _post_backend_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        secret = (self.config.backend_webhook_secret or "").strip()
        if secret:
            ts = str(int(time.time()))
            headers[WEBHOOK_TIMESTAMP_HEADER] = ts
            headers[WEBHOOK_SIGNATURE_HEADER] = compute_signature(secret, ts, body)
        req = request.Request(
            self.config.backend_events_url,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                blob = resp.read().decode("utf-8") or "{}"
                if resp.status >= 400:
                    raise RuntimeError(f"backend webhook returned HTTP {resp.status}")
                parsed = json.loads(blob)
                if isinstance(parsed, dict):
                    logger.info(
                        "telephony webhook HTTP status=%s simulator_step=%s noop=%s status_field=%s",
                        resp.status,
                        parsed.get("simulator_step"),
                        parsed.get("noop"),
                        parsed.get("status"),
                    )
                return parsed if isinstance(parsed, dict) else {}
        except error.HTTPError as e:
            logger.warning("telephony webhook HTTP failure status=%s", e.code)
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"backend webhook returned HTTP {e.code}: {detail}") from e
