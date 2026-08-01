let speechSequenceId = 0;
let pendingTimers = [];

function clearPendingTimers() {
  pendingTimers.forEach((timer) => window.clearTimeout(timer));
  pendingTimers = [];
}

export function canUseSpeechSynthesis() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speakText(text, { muted = false, volume = 1 } = {}) {
  if (muted || !text || !canUseSpeechSynthesis()) return false;
  speechSequenceId += 1;
  clearPendingTimers();
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.95;
  utterance.pitch = 1;
  utterance.volume = Math.min(1, Math.max(0.05, Number(volume) || 1));
  window.speechSynthesis.speak(utterance);
  return true;
}

export function speakDigitsSlowly(code, { muted = false, intro = "Your verification code is:" } = {}) {
  if (muted || !code || !canUseSpeechSynthesis()) return false;
  const digits = String(code).replace(/\D/g, "").split("");
  if (digits.length === 0) return false;

  window.speechSynthesis.cancel();
  speechSequenceId += 1;
  clearPendingTimers();
  const sequenceId = speechSequenceId;
  const phrases = [{ text: intro, rate: 0.7 }];
  digits.forEach((digit) => {
    phrases.push({ text: digit, rate: 0.38, delayAfterMs: 700 });
  });

  function speakAt(index) {
    if (sequenceId !== speechSequenceId) return;
    const item = phrases[index];
    if (!item) return;
    const utterance = new SpeechSynthesisUtterance(item.text);
    utterance.rate = item.rate;
    utterance.pitch = 1;
    utterance.volume = 1;
    utterance.onend = () => {
      if (sequenceId !== speechSequenceId) return;
      const timer = window.setTimeout(() => speakAt(index + 1), item.delayAfterMs || 250);
      pendingTimers.push(timer);
    };
    window.speechSynthesis.speak(utterance);
  }

  speakAt(0);
  return true;
}

export function stopSpeech() {
  speechSequenceId += 1;
  clearPendingTimers();
  if (canUseSpeechSynthesis()) {
    window.speechSynthesis.cancel();
  }
}

let previewAudio = null;
let previewObjectUrl = null;

export function stopLuvVoicePreview() {
  if (previewAudio) {
    previewAudio.pause();
    previewAudio.removeAttribute("src");
    previewAudio.load();
    previewAudio = null;
  }
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = null;
  }
}

/** Stop browser TTS and any in-flight LuvVoice preview audio. */
export function stopAllSpeechPreview() {
  stopSpeech();
  stopLuvVoicePreview();
}

export async function playLuvVoicePreviewBlob(blob) {
  if (!blob || typeof Audio === "undefined") return false;
  stopAllSpeechPreview();
  previewObjectUrl = URL.createObjectURL(blob);
  previewAudio = new Audio(previewObjectUrl);
  previewAudio.onended = () => {
    stopLuvVoicePreview();
  };
  try {
    await previewAudio.play();
    return true;
  } catch {
    stopLuvVoicePreview();
    return false;
  }
}
