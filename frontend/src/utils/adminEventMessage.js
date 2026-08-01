/**
 * Operator-facing summaries for audit / live UI (never callee instructions).
 */

export function summarizeAdminEventMessage(ev) {
  const type = String(ev?.event_type || "");
  const raw = String(ev?.message || "").trim();
  if (!raw) return "";

  if (type === "CALL_ANSWERED" || type === "IVR_PROMPT") {
    if (/^Callee answered/i.test(raw) || /^Consent prompt/i.test(raw)) return raw;
    return type === "CALL_ANSWERED"
      ? "Callee answered — consent step started."
      : "Consent audio playing on callee line.";
  }

  if (/You are receiving a verification call/i.test(raw)) {
    return "Callee answered — consent audio on phone.";
  }

  if (/To continue, press 1/i.test(raw) && /To decline, press 2/i.test(raw)) {
    return "Callee hearing consent prompt (keypad: 1 accept, 2 decline).";
  }

  if (/provider_call_id=|raw=\{/.test(raw)) {
    const base = raw.split(/\s*\(provider_call_id=/)[0].split(/\s*raw=\{/)[0].trim();
    if (/You are receiving|press 1/i.test(base)) {
      return "Callee answered — consent audio on phone.";
    }
    return base || "Telephony provider event.";
  }

  return raw;
}

/** Lines that must not appear in the operator terminal output. */
export function isCalleeFacingLine(text) {
  const t = String(text || "");
  return (
    /You are receiving a verification call/i.test(t) ||
    (/To continue, press 1/i.test(t) && /To decline, press 2/i.test(t)) ||
    /provider_call_id=/.test(t) ||
    /raw=\{/.test(t)
  );
}
