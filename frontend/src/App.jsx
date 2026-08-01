import { useCallback, useEffect, useMemo, useState } from "react";
import {
  clearAuthToken,
  confirmAdminCodeSent,
  fetchCall,
  fetchCalls,
  fetchCurrentAdmin,
  fetchEvents,
  fetchRuntimeConfig,
  fetchSpeechScripts,
  markAuthSessionActive,
  logoutAdmin,
  resetSpeechScripts,
  saveSpeechScripts,
} from "./api.js";
import { connectLiveFeed } from "./socket.js";
import CallForm from "./components/CallForm.jsx";
import LiveProviderPanel from "./components/LiveProviderPanel.jsx";
import SimpleWorkflow from "./components/SimpleWorkflow.jsx";
import SpeechScriptsPanel from "./components/SpeechScriptsPanel.jsx";
import LoginScreen from "./components/LoginScreen.jsx";
import MobileCallSimulator from "./components/MobileCallSimulator.jsx";
import { PrimaryButton, SecondaryButton, ConnectionBadge } from "./components/ui.jsx";

const ENABLE_MOBILE_SIMULATOR = import.meta.env.VITE_ENABLE_MOBILE_SIMULATOR === "true";

/** Authoritative snapshot from GET /calls or WS session_update — avoid stale merged fields */
function mergeSessions(prev, incoming) {
  const map = new Map(prev.map((s) => [s.id, s]));
  map.set(incoming.id, incoming);
  return Array.from(map.values()).sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  );
}

/** After GET /events, keep any WebSocket events for this session not yet returned by the API (avoids wiping live UI). */
function mergeSessionEventsFromFetch(prev, sessionId, fetched) {
  const fetchedIds = new Set(fetched.map((e) => e.id));
  const wsAhead = prev.filter((e) => e.session_id === sessionId && !fetchedIds.has(e.id));
  const others = prev.filter((e) => e.session_id !== sessionId);
  const merged = [...others, ...wsAhead, ...fetched];
  merged.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  return merged;
}

function getMobileCallId() {
  const match = window.location.pathname.match(/^\/mobile-call\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function MobileCallRoute({ callId }) {
  const [session, setSession] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [call, evs] = await Promise.all([fetchCall(callId), fetchEvents(callId)]);
      setSession(call);
      setEvents(evs);
    } catch (err) {
      setError(err.message || "Failed to load mobile call");
    }
  }, [callId]);

  useEffect(() => {
    if (!callId) return;
    refresh();
    const client = connectLiveFeed((msg) => {
      if (msg.type === "session_update" && msg.session?.id === callId) {
        setSession((prev) => ({ ...prev, ...msg.session }));
      }
      if (msg.event?.session_id === callId) {
        setEvents((prev) => {
          if (prev.some((ev) => ev.id === msg.event.id)) return prev;
          return [...prev, msg.event].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        });
      }
    });
    return () => client.close();
  }, [callId, refresh]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4 text-rose-700">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm">{error}</div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
        Loading mobile call...
      </div>
    );
  }

  return (
    <MobileCallSimulator
      open
      standalone
      session={session}
      events={events}
      onRefresh={refresh}
      onClose={() => window.close()}
    />
  );
}

export default function App() {
  const mobileCallId = getMobileCallId();
  const [admin, setAdmin] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [lastStart, setLastStart] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [runtime, setRuntime] = useState(null);
  const [techLogsOpen, setTechLogsOpen] = useState(false);
  /** When false, fetching calls may auto-select the newest active session. Default true → first load / refresh starts on blank "New call". */
  const [suppressAutoSelect, setSuppressAutoSelect] = useState(true);
  /** Bumped to reset CallForm fields and live panel internal state */
  const [newCallNonce, setNewCallNonce] = useState(0);

  const selected = useMemo(
    () => sessions.find((s) => s.id === selectedId) || null,
    [sessions, selectedId]
  );

  const startConfirmMessage = useMemo(() => {
    if (runtime?.provider_mode !== "sip_up") return null;
    const a = runtime.sip_up;
    if (!a) return null;
    if (a.ari_unreachable === true) return "Cannot reach SIP UP media service. Start anyway?";
    if (a.sip_trunk_endpoint_online === false) {
      const trunk = (a.endpoint || "").toLowerCase();
      if (trunk.includes("sip-up")) {
        return "SIP UP trunk may not be registered. Check pjsip show registrations and whitelist your public IP in the SIP UP dashboard.";
      }
      return "SIP UP trunk is not registered. Start anyway?";
    }
    return null;
  }, [runtime]);

  useEffect(() => {
    let cancelled = false;
    async function restoreAuth() {
      try {
        const row = await fetchCurrentAdmin();
        if (!cancelled) {
          setAdmin(row);
          markAuthSessionActive();
        }
      } catch {
        clearAuthToken();
        if (!cancelled) setAdmin(null);
      } finally {
        if (!cancelled) setAuthChecked(true);
      }
    }
    restoreAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function handleExpired() {
      setAdmin(null);
      setAuthChecked(true);
    }
    window.addEventListener("ivr-auth-expired", handleExpired);
    return () => window.removeEventListener("ivr-auth-expired", handleExpired);
  }, []);

  const refreshSessions = useCallback(async () => {
    setLoadError(null);
    try {
      const rows = await fetchCalls();
      setSessions(rows);
      if (!selectedId && rows.length > 0 && !suppressAutoSelect) {
        const active = rows.find((row) => !["completed", "failed", "cancelled"].includes(row.status));
        setSelectedId((active || rows[0]).id);
      }
    } catch (e) {
      setLoadError(e.message || "Failed to load sessions");
    }
  }, [selectedId, suppressAutoSelect]);

  const syncLiveForCall = useCallback(
    async (callId) => {
      if (!callId) return;
      try {
        const [row, evs] = await Promise.all([fetchCall(callId), fetchEvents(callId)]);
        setSessions((prev) => mergeSessions(prev, row));
        setLiveEvents((prev) => mergeSessionEventsFromFetch(prev, callId, evs));
      } catch {
        await refreshSessions();
      }
    },
    [refreshSessions]
  );

  useEffect(() => {
    if (!admin || mobileCallId) return;
    refreshSessions();
  }, [admin, mobileCallId, refreshSessions]);

  useEffect(() => {
    if (!admin || mobileCallId) return;
    let cancelled = false;
    (async () => {
      try {
        const cfg = await fetchRuntimeConfig();
        if (!cancelled) setRuntime(cfg);
      } catch {
        if (!cancelled) setRuntime(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [admin, mobileCallId]);

  useEffect(() => {
    if (!admin || mobileCallId || runtime?.provider_mode !== "sip_up") return undefined;
    const t = window.setInterval(() => {
      fetchRuntimeConfig().then(setRuntime).catch(() => {});
    }, 25000);
    return () => window.clearInterval(t);
  }, [admin, mobileCallId, runtime?.provider_mode]);

  const handleConfirmAdminCodeSent = useCallback(
    async (callId) => {
      await confirmAdminCodeSent(callId);
      await syncLiveForCall(callId);
    },
    [syncLiveForCall]
  );

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const evs = await fetchEvents(selectedId);
        if (!cancelled) {
          setLiveEvents((prev) => mergeSessionEventsFromFetch(prev, selectedId, evs));
        }
      } catch {
        /* keep websocket-only events */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    if (!admin || mobileCallId) return undefined;
    const client = connectLiveFeed(
      (msg) => {
        const ev = msg.event;
        if (ev && msg.type !== "session_update") {
          setLiveEvents((prev) => {
            if (prev.some((e) => e.id === ev.id)) return prev;
            return [...prev, ev].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
          });
        }
        if (msg.type === "session_update" && msg.session) {
          setSessions((prev) => mergeSessions(prev, msg.session));
        }
      },
      { onConnectionChange: setWsConnected }
    );
    return () => {
      client.close();
    };
  }, [admin, mobileCallId]);

  async function handleCreated(row, mobileWindow) {
    setSuppressAutoSelect(false);
    setSelectedId(row.call_id);
    setLastStart({
      call_id: row.call_id,
      demo_code: row.demo_code,
    });
    await refreshSessions();
    if (!ENABLE_MOBILE_SIMULATOR) return;
    const mobileUrl = `/mobile-call/${encodeURIComponent(row.call_id)}`;
    if (mobileWindow && !mobileWindow.closed) {
      mobileWindow.location.href = mobileUrl;
      mobileWindow.focus();
    } else {
      window.open(mobileUrl, "ivr-recipient-mobile");
    }
  }

  async function handleLogout() {
    await logoutAdmin();
    setAdmin(null);
    setSessions([]);
    setSelectedId(null);
    setLiveEvents([]);
    setLastStart(null);
    setSuppressAutoSelect(true);
    setNewCallNonce(0);
  }

  function handleNewCall() {
    setSuppressAutoSelect(true);
    setSelectedId(null);
    setLastStart(null);
    setTechLogsOpen(false);
    setLiveEvents([]);
    setNewCallNonce((n) => n + 1);
  }

  const speechApi = useMemo(
    () => ({ fetchSpeechScripts, saveSpeechScripts, resetSpeechScripts }),
    [],
  );

  const showStartBanner =
    lastStart &&
    selectedId === lastStart.call_id &&
    lastStart.call_id;

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Checking admin session...
      </div>
    );
  }

  if (!admin) {
    return <LoginScreen onAuthenticated={setAdmin} />;
  }

  if (mobileCallId && ENABLE_MOBILE_SIMULATOR) {
    return <MobileCallRoute callId={mobileCallId} />;
  }

  return (
    <div className="app-shell">
      <header className="app-header sticky top-0 z-30">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center justify-between gap-4 px-4 py-4 lg:px-6">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-400 to-indigo-500 text-sm font-bold text-white shadow-glow">
                IV
              </div>
              <div>
                <h1 className="text-sm font-semibold tracking-tight text-white">IVR Verification Console</h1>
                <p className="text-[11px] text-slate-400">Outbound identity verification operations</p>
              </div>
            </div>
            <SecondaryButton
              type="button"
              className="border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white hover:bg-white/10"
              onClick={handleNewCall}
            >
              + New call
            </SecondaryButton>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium text-slate-200">
              {runtime?.provider_label || "Provider pending"}
            </span>
            <ConnectionBadge connected={wsConnected} />
            {admin?.email ? (
              <span className="hidden rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-slate-300 sm:inline">
                {admin.email}
              </span>
            ) : null}
            <SecondaryButton
              type="button"
              className="border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white hover:bg-white/10"
              onClick={handleLogout}
            >
              Logout
            </SecondaryButton>
          </div>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1800px] gap-5 px-4 py-5 lg:grid-cols-12 lg:px-6 lg:py-6">
        <section className="animate-slide-up space-y-4 lg:col-span-3">
          {loadError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{loadError}</div>
          ) : null}
          {runtime?.provider_mode === "sip_up" && runtime?.sip_up?.ari_unreachable === true ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
              Cannot reach SIP UP media service. Check host, port, and credentials.
            </div>
          ) : null}
          {runtime?.provider_mode === "sip_up" && runtime?.sip_up?.sip_trunk_endpoint_online === false ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-900">
              Provider not registered. On the SIP UP stack run{" "}
              <code className="rounded bg-white/80 px-1">pjsip show registrations</code> — it must show Registered.
            </div>
          ) : null}

          <CallForm
            simple
            resetSignal={newCallNonce}
            startConfirmMessage={startConfirmMessage}
            onCreated={handleCreated}
            enableMobileSimulator={ENABLE_MOBILE_SIMULATOR}
            runtime={runtime}
            onRuntimeRefresh={async () => {
              const cfg = await fetchRuntimeConfig();
              setRuntime(cfg);
            }}
            onResumeActiveCall={(callId) => {
              setSuppressAutoSelect(false);
              setSelectedId(callId);
              syncLiveForCall(callId);
            }}
            onActiveCallEnded={async () => {
              await refreshSessions();
            }}
          />

          {showStartBanner ? (
            <div className="rounded-xl border border-emerald-200/80 bg-gradient-to-r from-emerald-50 to-teal-50 px-4 py-3 text-xs font-medium text-emerald-900 shadow-sm">
              Call initiated — monitor live activity in the center panel.
            </div>
          ) : null}

        </section>

        <section className="animate-slide-up lg:col-span-6" style={{ animationDelay: "60ms" }}>
          <LiveProviderPanel
            key={`live-${selectedId ?? "none"}-${newCallNonce}`}
            session={selected}
            runtime={runtime}
            events={liveEvents}
            techLogsOpen={techLogsOpen}
            onTechLogsToggle={() => setTechLogsOpen((v) => !v)}
            onConfirmAdminCodeSent={handleConfirmAdminCodeSent}
            onSyncLiveForCall={syncLiveForCall}
          />
        </section>

        <section className="animate-slide-up space-y-4 lg:col-span-3" style={{ animationDelay: "120ms" }}>
          <SimpleWorkflow session={selected} />
          <SpeechScriptsPanel api={speechApi} />
        </section>
      </main>

    </div>
  );
}
