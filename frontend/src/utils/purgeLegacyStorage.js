import {
  getGlobalCookie,
  GLOBAL_COOKIE_PATH,
  removeGlobalCookie,
  setGlobalCookie,
} from "./globalCookies.js";

/** Bump when cookie/localStorage layout changes and old keys must be wiped. */
const STORAGE_GENERATION_KEY = "ivr_storage_generation";
const CURRENT_STORAGE_GENERATION = "4";

const LEGACY_LOCAL_STORAGE_KEYS = [
  "ivr_admin_access_token",
  "ivr_caller_id_presets",
  "ivr_caller_id_presets_v2",
  "ivr_recent_organizations",
  "ivr_luvvoice_voice_id",
];

const LEGACY_SESSION_STORAGE_KEYS = ["ivr_auth_session"];

/** Cookie names from older builds (localStorage era + v1 presets). */
const LEGACY_COOKIE_NAMES = [
  "ivr_admin_access_token",
  "ivr_caller_id_presets",
  "ivr_caller_id_presets_v2",
  "ivr_recent_organizations",
  "ivr_luvvoice_voice_id",
];

function cookieSecureFlag() {
  return typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
}

/** Expire a cookie on every path variant browsers may have used. */
function expireCookieEverywhere(name) {
  if (typeof document === "undefined") return;
  const expires = "Thu, 01 Jan 1970 00:00:00 GMT";
  const secure = cookieSecureFlag();
  const variants = [
    `${name}=; Path=/; Max-Age=0; Expires=${expires}; SameSite=Lax${secure}`,
    `${name}=; Path=${GLOBAL_COOKIE_PATH}; Max-Age=0; Expires=${expires}; SameSite=Lax${secure}`,
    `${name}=; Max-Age=0; Expires=${expires}; SameSite=Lax${secure}`,
  ];
  for (const line of variants) {
    document.cookie = line;
  }
}

/**
 * One-time wipe of legacy localStorage / old cookies so the app writes fresh global cookies.
 * Re-login required after purge (auth cookie cleared).
 */
export function purgeLegacyStorageIfNeeded() {
  if (typeof window === "undefined") return;
  if (getGlobalCookie(STORAGE_GENERATION_KEY) === CURRENT_STORAGE_GENERATION) {
    return;
  }

  try {
    for (const key of LEGACY_LOCAL_STORAGE_KEYS) {
      localStorage.removeItem(key);
    }
  } catch {
    /* private mode */
  }

  try {
    for (const key of LEGACY_SESSION_STORAGE_KEYS) {
      sessionStorage.removeItem(key);
    }
  } catch {
    /* */
  }

  for (const name of LEGACY_COOKIE_NAMES) {
    expireCookieEverywhere(name);
    removeGlobalCookie(name);
  }

  setGlobalCookie(STORAGE_GENERATION_KEY, CURRENT_STORAGE_GENERATION);
}
