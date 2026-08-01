/** Site-wide cookies (Path=/). Prefer over localStorage for shared / persistent settings. */

export const GLOBAL_COOKIE_PATH = "/";
const MAX_COOKIE_BYTES = 3800;

function cookieSecureFlag() {
  return typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
}

export function setGlobalCookie(name, value, maxAgeSeconds = 60 * 60 * 24 * 365) {
  if (typeof document === "undefined") return;
  const encoded = encodeURIComponent(String(value ?? ""));
  if (encoded.length > MAX_COOKIE_BYTES) {
    console.warn(`[ivr] Cookie ${name} too large; not stored`);
    return;
  }
  document.cookie = `${name}=${encoded}; Path=${GLOBAL_COOKIE_PATH}; Max-Age=${maxAgeSeconds}; SameSite=Lax${cookieSecureFlag()}`;
}

export function getGlobalCookie(name) {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return null;
}

export function removeGlobalCookie(name) {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; Path=${GLOBAL_COOKIE_PATH}; Max-Age=0; SameSite=Lax${cookieSecureFlag()}`;
}

/** One-time copy from localStorage → cookie, then drop the local key. */
export function migrateLocalStorageToCookie(storageKey, cookieName, maxAgeSeconds) {
  if (typeof localStorage === "undefined") return;
  try {
    const existing = getGlobalCookie(cookieName);
    const legacy = localStorage.getItem(storageKey);
    if (!existing && legacy) {
      setGlobalCookie(cookieName, legacy, maxAgeSeconds);
    }
    if (legacy) localStorage.removeItem(storageKey);
  } catch {
    /* private mode */
  }
}
