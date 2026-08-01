import { createId } from "./createId.js";
import { getGlobalCookie, setGlobalCookie } from "./globalCookies.js";

const COOKIE_KEY = "ivr_caller_id_presets_v2";

export const DEFAULT_CALLER_ID_PRESETS = [
  {
    id: "preset-sipup-tn-account",
    label: "SIP UP — Ala (Tunisia)",
    number: "2165543124",
    providers: ["sip_up"],
  },
  {
    id: "preset-sipup-it",
    label: "SIP UP — Italy",
    number: "393888736444",
    providers: ["sip_up"],
  },
  {
    id: "preset-sipup-de",
    label: "SIP UP — Allemagne",
    number: "4930123456789",
    providers: ["sip_up"],
  },
  {
    id: "preset-sipup-kw",
    label: "SIP UP — Kuwait",
    number: "96550001234",
    providers: ["sip_up"],
  },
  {
    id: "preset-sipup-us",
    label: "SIP UP — USA",
    number: "18005551234",
    providers: ["sip_up"],
  },
  {
    id: "preset-sipup-tn",
    label: "SIP UP — Tunisia",
    number: "21626565725",
    providers: ["sip_up"],
  },
];

function normalizeNumber(raw) {
  return String(raw || "").replace(/\D/g, "");
}

export function loadCallerIdPresets() {
  try {
    const parsed = JSON.parse(getGlobalCookie(COOKIE_KEY) || "[]");
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return [...DEFAULT_CALLER_ID_PRESETS];
    }
    return parsed
      .filter((p) => p && typeof p.label === "string" && normalizeNumber(p.number).length >= 3)
      .map((p) => ({
        id: String(p.id || createId()),
        label: p.label.trim(),
        number: normalizeNumber(p.number),
        providers: ["sip_up"],
      }));
  } catch {
    return [...DEFAULT_CALLER_ID_PRESETS];
  }
}

export function saveCallerIdPresets(presets) {
  setGlobalCookie(COOKIE_KEY, JSON.stringify(presets));
}

export function addCallerIdPreset({ label, number }) {
  const clean = normalizeNumber(number);
  if (!label?.trim() || clean.length < 3) {
    throw new Error("Label and caller ID (3+ digits) are required");
  }
  const next = [
    ...loadCallerIdPresets(),
    {
      id: createId(),
      label: label.trim(),
      number: clean,
      providers: ["sip_up"],
    },
  ];
  saveCallerIdPresets(next);
  return next;
}

export function removeCallerIdPreset(id) {
  const next = loadCallerIdPresets().filter((p) => p.id !== id);
  saveCallerIdPresets(next);
  return next;
}

export function presetsForProvider(presets) {
  return presets.filter((p) => !p.providers?.length || p.providers.includes("sip_up"));
}

/** Inject the backend-configured SIP UP caller ID so it always appears in the picker. */
export function presetsWithConfiguredCallerId(presets, configuredCallerId, configuredLabel) {
  const clean = normalizeNumber(configuredCallerId);
  if (clean.length < 3) return presetsForProvider(presets);
  const base = presetsForProvider(presets);
  const label = (configuredLabel || "").trim() || "SIP UP account (configured)";
  const existing = base.find((p) => normalizeNumber(p.number) === clean);
  if (existing) {
    return base.map((p) =>
      normalizeNumber(p.number) === clean
        ? { ...p, label, configured: true, id: p.id || "preset-sipup-configured" }
        : p,
    );
  }
  return [
    {
      id: "preset-sipup-configured",
      label,
      number: clean,
      providers: ["sip_up"],
      configured: true,
    },
    ...base,
  ];
}
