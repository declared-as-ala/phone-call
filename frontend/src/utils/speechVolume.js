import { getGlobalCookie, setGlobalCookie } from "./globalCookies.js";

/** Default loudness for callee TTS (phone). 70% ≈ unity gain (1.0) on the server. */
export const DEFAULT_SPEECH_VOLUME_PERCENT = 70;

export const MIN_SPEECH_VOLUME_PERCENT = 40;
export const MAX_SPEECH_VOLUME_PERCENT = 150;

export const SPEECH_VOLUME_COOKIE = "ivr_speech_volume_percent";

/** Map UI percent (40–150) to linear gain for ffmpeg (≈1.0 at 70%). */
export function volumePercentToGain(percent) {
  const p = clampSpeechVolumePercent(percent);
  return Math.round((p / 70) * 1000) / 1000;
}

export function clampSpeechVolumePercent(percent) {
  const n = Number(percent);
  if (!Number.isFinite(n)) return DEFAULT_SPEECH_VOLUME_PERCENT;
  return Math.min(MAX_SPEECH_VOLUME_PERCENT, Math.max(MIN_SPEECH_VOLUME_PERCENT, Math.round(n)));
}

/** Browser SpeechSynthesis volume is capped at 1.0. */
export function volumePercentToBrowserVolume(percent) {
  const gain = volumePercentToGain(percent);
  return Math.min(1, Math.max(0.1, gain * 0.72));
}

export function loadStoredSpeechVolumePercent() {
  try {
    const raw = getGlobalCookie(SPEECH_VOLUME_COOKIE);
    if (raw == null || raw === "") return DEFAULT_SPEECH_VOLUME_PERCENT;
    return clampSpeechVolumePercent(raw);
  } catch {
    return DEFAULT_SPEECH_VOLUME_PERCENT;
  }
}

export function storeSpeechVolumePercent(percent) {
  try {
    setGlobalCookie(SPEECH_VOLUME_COOKIE, String(clampSpeechVolumePercent(percent)));
  } catch {
    /* ignore */
  }
}
