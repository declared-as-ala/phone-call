/**
 * Substitutes IVR speech placeholders to match backend `speech_script_service._subst_placeholders`
 * ({name}, {organization}, {code_length}, {code_segments}).
 */

export const DEFAULT_CODE_LENGTH = 6;
export const DEFAULT_OTP_DIGIT_COUNT = 6;
export const VALID_OTP_LENGTHS = [4, 6, 8, 10];
/** @deprecated use VALID_OTP_LENGTHS */
export const STUDENT_CARD_SEGMENTS = VALID_OTP_LENGTHS;

export function coerceOtpDigitCount(value) {
  const n = Number(value);
  if (Number.isFinite(n) && VALID_OTP_LENGTHS.includes(Math.trunc(n))) {
    return Math.trunc(n);
  }
  return DEFAULT_OTP_DIGIT_COUNT;
}

/** Mirror `call_sessions.expected_digits_count` for live UI previews. */
export function expectedDigits(session) {
  return coerceOtpDigitCount(session?.expected_digits_count);
}

export function formatCodeSegmentsLabel(segments = VALID_OTP_LENGTHS) {
  const parts = segments.map(String);
  if (parts.length === 1) return parts[0];
  if (parts.length === 2) return `${parts[0]} or ${parts[1]}`;
  return `${parts.slice(0, -1).join(", ")}, or ${parts[parts.length - 1]}`;
}

export function substituteSpeechTemplate(
  template,
  { name = "", university = "", codeLength } = {},
) {
  const n = coerceOtpDigitCount(codeLength ?? DEFAULT_CODE_LENGTH);
  const callee = String(name || "").trim() || "Recipient";
  const org = String(university || "").trim() || "Organization";
  const segments = formatCodeSegmentsLabel([n]);
  return String(template ?? "")
    .replaceAll("{name}", callee)
    .replaceAll("{organization}", org)
    .replaceAll("{code_length}", String(n))
    .replaceAll("{code_segments}", segments);
}
