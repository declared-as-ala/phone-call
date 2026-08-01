import { hasAuthSessionHint } from "./api.js";
import { isLocalViteDevPage } from "./utils/devOrigin.js";

const DEFAULT_WS = "ws://localhost:8000/ws";

function isLocalDevWsUrl(url) {
  return /^wss?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url);
}

function isBrowserOnRemoteHost() {
  if (typeof window === "undefined" || !window.location?.hostname) return false;
  return !/^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname);
}

/** Build default WS when VITE_WS_URL is omitted: reuse API host/port if parseable */
function websocketUrlFromEnv() {
  if (typeof window !== "undefined" && window.location?.host && isBrowserOnRemoteHost()) {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${window.location.host}/ws`;
  }
  if (isLocalViteDevPage()) {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${window.location.host}/ws`;
  }
  const explicit = import.meta.env.VITE_WS_URL?.trim();
  if (explicit && !(isLocalDevWsUrl(explicit) && isBrowserOnRemoteHost())) return explicit;
  if (typeof window !== "undefined" && window.location?.host) {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${window.location.host}/ws`;
  }
  try {
    let api = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "").replace(/\/api$/, "");
    if (!api || (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(api) && isBrowserOnRemoteHost())) {
      if (typeof window !== "undefined" && window.location?.host) {
        const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
        return `${wsProto}//${window.location.host}/ws`;
      }
      api = "http://localhost:8000";
    }
    if (!api) return DEFAULT_WS;
    const u = new URL(api.includes("://") ? api : `http://${api}`);
    const wsProto = u.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${u.hostname}:${u.port || (u.protocol === "https:" ? "443" : "80")}/ws`;
  } catch {
    return DEFAULT_WS;
  }
}

function buildWsUrl() {
  return websocketUrlFromEnv();
}

/**
 * Subscribe to backend live broadcasts (calls + sessions). Reconnects after drops when a token exists.
 *
 * @param {(data: unknown) => void} onMessage
 * @param {{ onConnectionChange?: (open: boolean) => void }} [options]
 * @returns {{ close: () => void }}
 */
export function connectLiveFeed(onMessage, options = {}) {
  const onConnectionChange = options.onConnectionChange;
  let manualClose = false;
  let retryTimer = null;
  let attempt = 0;
  let ws = /** @type {WebSocket | null} */ (null);

  function clearRetry() {
    if (retryTimer != null) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
  }

  function scheduleReconnect() {
    clearRetry();
    if (manualClose || !hasAuthSessionHint()) return;
    const delayMs = Math.min(30_000, Math.round(750 * Math.pow(1.6, Math.min(attempt, 12))));
    attempt++;
    retryTimer = window.setTimeout(open, delayMs);
  }

  function open() {
    if (manualClose || !hasAuthSessionHint()) {
      onConnectionChange?.(false);
      return;
    }
    clearRetry();
    let url;
    try {
      url = buildWsUrl();
    } catch {
      scheduleReconnect();
      return;
    }
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        onMessage(data);
      } catch {
        /* ignore malformed */
      }
    };

    ws.onopen = () => {
      attempt = 0;
      onConnectionChange?.(true);
    };

    ws.onerror = () => {
      onConnectionChange?.(false);
    };

    ws.onclose = () => {
      onConnectionChange?.(false);
      if (!manualClose && hasAuthSessionHint()) {
        scheduleReconnect();
      }
    };
  }

  open();

  return {
    close() {
      manualClose = true;
      clearRetry();
      try {
        ws?.close();
      } catch {
        /* */
      }
      ws = null;
    },
  };
}
