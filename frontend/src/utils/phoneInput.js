/** Helpers for country + national phone input in CallForm. */

const NANP_ISOS = new Set(["US", "CA", "PR", "VI", "GU", "AS", "AI", "AG", "BS", "BB", "BM", "VG", "KY", "DM", "DO", "GD", "JM", "KN", "LC", "MS", "MP", "SX", "TT", "TC", "VC"]);

function digitsOnly(value) {
  return String(value || "").replace(/\D/g, "");
}

function dialCodesSorted(countries) {
  return [...countries].sort((a, b) => b.dialCode.length - a.dialCode.length);
}

function pickIsoForDialCode(countries, dialCode, nationalDigits) {
  const matches = countries.filter((c) => c.dialCode === dialCode);
  if (matches.length <= 1) return matches[0]?.iso || null;
  if (dialCode === "+1" && nationalDigits.length === 10) {
    const us = matches.find((c) => c.iso === "US");
    if (us) return us.iso;
  }
  return matches[0]?.iso || null;
}

/**
 * Parse pasted / typed international input into country ISO + national digits.
 * Returns null when the value looks like a plain national number.
 */
export function parseInternationalPhoneInput(raw, countries) {
  const text = String(raw || "").trim();
  if (!text) return null;

  let e164 = "";
  if (text.startsWith("+")) {
    e164 = `+${digitsOnly(text)}`;
  } else if (text.startsWith("00") && digitsOnly(text).length > 4) {
    e164 = `+${digitsOnly(text).slice(2)}`;
  } else {
    const d = digitsOnly(text);
    // 11+ digits without + often means full international pasted without plus.
    if (d.length >= 11) {
      e164 = `+${d}`;
    } else {
      return null;
    }
  }

  for (const country of dialCodesSorted(countries)) {
    const dc = country.dialCode;
    if (!e164.startsWith(dc)) continue;
    const nationalDigits = digitsOnly(e164.slice(dc.length));
    if (!nationalDigits) return null;
    const iso = pickIsoForDialCode(countries, dc, nationalDigits);
    return { iso, nationalDigits, e164: `${dc}${nationalDigits}` };
  }
  return null;
}

export function composeDestinationE164(country, nationalDigits) {
  const dc = String(country?.dialCode || "").trim();
  const national = digitsOnly(nationalDigits);
  if (!dc || !national) return "";
  return `${dc}${national}`;
}

export function destinationCountryMismatch(selectedIso, destinationE164) {
  const dest = String(destinationE164 || "").trim();
  if (!dest.startsWith("+")) return null;
  if (selectedIso === "IT" && dest.startsWith("+1")) {
    return "Country is Italy (+39) but this number will dial the USA (+1). Change the country dropdown to match the recipient.";
  }
  if (selectedIso === "US" && dest.startsWith("+39")) {
    return "Country is USA (+1) but this number will dial Italy (+39). Change the country dropdown to match the recipient.";
  }
  if (selectedIso === "TN" && dest.startsWith("+1")) {
    return "Country is Tunisia (+216) but this number will dial +1. Check the country dropdown.";
  }
  return null;
}

export function isNanpIso(iso) {
  return NANP_ISOS.has(iso);
}
