import { getGlobalCookie, removeGlobalCookie } from "./utils/globalCookies.js";
import { isLocalViteDevPage } from "./utils/devOrigin.js";

function isLocalDevApiUrl(url) {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
}

function isBrowserOnRemoteHost() {
  if (typeof window === "undefined" || !window.location?.hostname) return false;
  return !/^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname);
}

function resolveApiRoot() {
  // Deployed site: always same-origin API (nginx → backend). Runs before any baked dev URL.
  if (typeof window !== "undefined" && window.location?.origin && isBrowserOnRemoteHost()) {
    return `${window.location.origin}/api`;
  }
  // Vite dev: same-origin /api via proxy (avoids CORS and direct :8000 when backend is down).
  if (isLocalViteDevPage()) {
    return `${window.location.origin}/api`;
  }
  const raw = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  if (raw && !(isLocalDevApiUrl(raw) && isBrowserOnRemoteHost())) {
    const withApi = raw.endsWith("/api") ? raw : `${raw}/api`;
    return withApi;
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/api`;
  }
  return "http://localhost:8000/api";
}

let cachedApiRoot = null;

/** Resolved at call time in the browser so production builds never stick to baked localhost. */
export function getResolvedApiRoot() {
  if (import.meta.env.DEV) {
    return resolveApiRoot();
  }
  if (cachedApiRoot === null) {
    cachedApiRoot = resolveApiRoot();
  }
  return cachedApiRoot;
}

const AUTH_TOKEN_KEY = "ivr_admin_access_token";
const AUTH_SESSION_HINT = "ivr_auth_session";

/** Session auth uses HttpOnly global cookie + credentials (see purgeLegacyStorage). */
export function getAuthToken() {
  return getGlobalCookie(AUTH_TOKEN_KEY);
}

export function markAuthSessionActive() {
  try {
    sessionStorage.setItem(AUTH_SESSION_HINT, "1");
  } catch {
    /* private mode */
  }
}

export function hasAuthSessionHint() {
  try {
    return sessionStorage.getItem(AUTH_SESSION_HINT) === "1";
  } catch {
    return false;
  }
}

export function clearAuthToken() {
  removeGlobalCookie(AUTH_TOKEN_KEY);
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    sessionStorage.removeItem(AUTH_SESSION_HINT);
  } catch {
    /* */
  }
}

function authHeaders(extra = {}) {
  const token = getAuthToken();
  return {
    ...extra,
    "X-Requested-With": "XMLHttpRequest",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function parseError(res) {
  try {
    const t = await res.text();
    if (!t) return res.statusText;
    try {
      const j = JSON.parse(t);
      if (Array.isArray(j.detail)) {
        return j.detail.map((item) => (typeof item === "object" ? item.msg ?? JSON.stringify(item) : String(item))).join("; ");
      }
      if (typeof j.detail === "string") return j.detail;
    } catch {
      /* not JSON */
    }
    return t;
  } catch {
    return res.statusText;
  }
}

async function request(path, options = {}) {
  const r = await fetch(`${getResolvedApiRoot()}${path}`, {
    ...options,
    credentials: "include",
    headers: authHeaders(options.headers || {}),
  });
  if (r.status === 401) {
    clearAuthToken();
    window.dispatchEvent(new Event("ivr-auth-expired"));
  }
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function loginAdmin(body) {
  const data = await request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  markAuthSessionActive();
  return data;
}

/**
 * Create another admin account. Requires the caller to already be signed in as an
 * admin (backend: `POST /api/auth/register`, admin-gated). Does NOT sign the caller
 * in as the new admin — it returns the created admin's profile only, and the
 * caller's own session is left untouched. Intended for an "Administration" screen,
 * not the public login page.
 */
export async function createAdmin(body) {
  return request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchCurrentAdmin() {
  return request("/auth/me");
}

export async function logoutAdmin() {
  try {
    await request("/auth/logout", { method: "POST" });
  } finally {
    clearAuthToken();
  }
}

export async function fetchRuntimeConfig() {
  return request("/system/runtime");
}

export async function fetchSipUpAccount() {
  return request("/system/sip-up-account");
}

export async function updateSipUpAccount(body) {
  return request("/system/sip-up-account", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchCalls() {
  return request("/calls");
}

export async function fetchOutboundSpacing() {
  return request("/calls/outbound-spacing");
}

export async function fetchCall(sessionId) {
  return request(`/calls/${sessionId}`);
}

export async function startCall(body) {
  return request("/calls/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchEvents(sessionId) {
  return request(`/calls/${sessionId}/events`);
}

export async function fetchAdminEnteredCode(sessionId) {
  return request(`/calls/${sessionId}/admin/entered-code`);
}

export async function deleteCall(sessionId) {
  return request(`/calls/${sessionId}`, { method: "DELETE" });
}

export async function simulatorAction(sessionId, payload) {
  return request(`/simulator/${sessionId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function simulatorAnswered(callId) {
  return request(`/simulator/${callId}/answered`, { method: "POST" });
}

export async function simulatorPress(callId, digit) {
  return request(`/simulator/${callId}/press`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ digit: String(digit) }),
  });
}

export async function simulatorEnterCode(callId, digits) {
  return request(`/simulator/${callId}/enter-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ digits }),
  });
}

export async function approveVerification(callId) {
  return request(`/calls/${callId}/admin/approve-verification`, {
    method: "POST",
  });
}

export async function rejectVerification(callId) {
  return request(`/calls/${callId}/admin/reject-verification`, {
    method: "POST",
  });
}

export async function endActiveCall(callId) {
  return request(`/calls/${callId}/admin/end-call`, {
    method: "POST",
  });
}

const confirmCodeSentInFlight = new Map();

export async function confirmAdminCodeSent(callId) {
  const canonicalId = String(callId || "");
  const cid = encodeURIComponent(canonicalId);
  const path = `/calls/${cid}/admin/code-sent`;
  const url = `${getResolvedApiRoot()}${path}`;
  const prefix = canonicalId.slice(0, 8);

  console.info("[ivr] Done — code sent: clicked", {
    sessionIdPrefix: prefix,
  });

  const existing = confirmCodeSentInFlight.get(canonicalId);
  if (existing) {
    console.info("[ivr] Done — code sent: coalesced in-flight POST", {
      sessionIdPrefix: prefix,
    });
    return existing;
  }

  const promise = (async () => {
    console.info("[ivr] Done — code sent: POST starting", {
      resolvedApiRoot: getResolvedApiRoot(),
      path,
      sessionIdPrefix: prefix,
    });
    const r = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: authHeaders({}),
    });
    console.info("[ivr] Done — code sent: response status", r.status);
    if (r.status === 401) {
      clearAuthToken();
      window.dispatchEvent(new Event("ivr-auth-expired"));
    }
    if (!r.ok) throw new Error(await parseError(r));
    const body = await r.json();
    console.info("[ivr] Done — code sent: ok", {
      sessionIdPrefix: prefix,
      step: body?.step ?? null,
      idempotent: body?.idempotent ?? false,
    });
    return body;
  })();

  promise.finally(() => {
    confirmCodeSentInFlight.delete(canonicalId);
  });

  confirmCodeSentInFlight.set(canonicalId, promise);
  return promise;
}

export async function fetchLuvVoiceVoices() {
  return request("/tts/luvvoice/voices");
}

export async function fetchLuvVoiceStatus() {
  return request("/tts/luvvoice/status");
}

/** WAV bytes for dashboard preview (selected speaker + call volume). */
export async function fetchLuvVoicePreviewBlob(
  { text, voice_id, speech_volume_percent },
  signal,
) {
  const r = await fetch(`${getResolvedApiRoot()}/tts/luvvoice/preview`, {
    method: "POST",
    credentials: "include",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      text,
      voice_id,
      speech_volume_percent: speech_volume_percent,
    }),
    signal,
  });
  if (r.status === 401) {
    clearAuthToken();
    window.dispatchEvent(new Event("ivr-auth-expired"));
  }
  if (!r.ok) throw new Error(await parseError(r));
  return r.blob();
}

export async function fetchSpeechScripts() {
  return request("/speech-scripts");
}

export async function saveSpeechScripts(scripts, otpDigitCount) {
  const body = { scripts };
  if (otpDigitCount != null) body.otp_digit_count = otpDigitCount;
  return request("/speech-scripts", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function resetSpeechScripts() {
  return request("/speech-scripts/reset", {
    method: "POST",
  });
}
