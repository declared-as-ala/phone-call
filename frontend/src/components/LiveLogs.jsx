import { useEffect, useMemo, useRef, useState } from "react";
import { summarizeAdminEventMessage } from "../utils/adminEventMessage.js";
import { ActorBadge, EmptyState, cardClass } from "./ui.jsx";

function formatTimestamp(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

const TYPE_BADGE = {
  CALL_CREATED: "bg-blue-50 text-blue-700 ring-blue-200",
  CALL_INITIATED: "bg-blue-50 text-blue-700 ring-blue-200",
  CALL_ANSWERED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  RECIPIENT_ACCEPTED: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  ADMIN_CODE_SENT_CONFIRMED: "bg-teal-50 text-teal-800 ring-teal-200",
  RECIPIENT_DECLINED: "bg-amber-50 text-amber-700 ring-amber-200",
  PENDING_ADMIN_VERIFICATION: "bg-amber-50 text-amber-700 ring-amber-200",
  ADMIN_VERIFICATION_APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ADMIN_VERIFICATION_REJECTED: "bg-rose-50 text-rose-700 ring-rose-200",
  VERIFICATION_SUCCESS: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  VERIFICATION_FAILED: "bg-rose-50 text-rose-700 ring-rose-200",
  DIAL_STARTED: "bg-sky-50 text-sky-700 ring-sky-200",
  CALL_RINGING: "bg-sky-50 text-sky-700 ring-sky-200",
  RINGING: "bg-sky-50 text-sky-700 ring-sky-200",
  ANSWERED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  IVR_PROMPT: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  DIGIT_RECEIVED: "bg-amber-50 text-amber-700 ring-amber-200",
  DIGITS_RECEIVED: "bg-amber-50 text-amber-700 ring-amber-200",
  DTMF_RECEIVED: "bg-amber-50 text-amber-700 ring-amber-200",
  MAX_ATTEMPTS_EXCEEDED: "bg-rose-50 text-rose-700 ring-rose-200",
  CALL_FAILED: "bg-rose-50 text-rose-700 ring-rose-200",
  CALL_HANGUP: "bg-slate-100 text-slate-600 ring-slate-200",
  CALL_COMPLETED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  NOOP_TERMINAL_EVENT: "bg-slate-100 text-slate-600 ring-slate-200",
  VERIFICATION_OK: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  VERIFICATION_FAIL: "bg-rose-50 text-rose-700 ring-rose-200",
  HANGUP: "bg-slate-100 text-slate-600 ring-slate-200",
  FAILED: "bg-rose-50 text-rose-700 ring-rose-200",
  AUDIT_STATE_CHANGE: "bg-slate-100 text-slate-600 ring-slate-200",
};

const FILTERS = [
  { id: "all", label: "All" },
  { id: "admin", label: "Admin" },
  { id: "user", label: "User" },
  { id: "system", label: "System" },
  { id: "telephony_provider", label: "Telephony" },
];

const IMPORTANT_EVENTS = new Set([
  "CALL_CREATED",
  "CALL_INITIATED",
  "DIAL_STARTED",
  "CALL_ANSWERED",
  "RECIPIENT_ACCEPTED",
  "RECIPIENT_DECLINED",
  "ADMIN_CODE_SENT_CONFIRMED",
  "DIGITS_RECEIVED",
  "PENDING_ADMIN_VERIFICATION",
  "ADMIN_VERIFICATION_APPROVED",
  "ADMIN_VERIFICATION_REJECTED",
  "VERIFICATION_SUCCESS",
  "VERIFICATION_FAILED",
  "CALL_COMPLETED",
  "CALL_HANGUP",
  "CALL_FAILED",
]);

function displayEventType(type) {
  if (type === "CALL_CREATED" || type === "CALL_INITIATED") return "CALL_STARTED";
  if (type === "DIGITS_RECEIVED") return "CODE_ENTERED";
  return type;
}

function displayMessage(ev) {
  return summarizeAdminEventMessage(ev);
}

export default function LiveLogs({ events, filterSessionId }) {
  const bottomRef = useRef(null);
  const [actorFilter, setActorFilter] = useState("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const [showTechnical, setShowTechnical] = useState(false);

  const visible = useMemo(() => {
    return events
      .filter((e) => !filterSessionId || e.session_id === filterSessionId)
      .filter((e) => showTechnical || IMPORTANT_EVENTS.has(e.event_type))
      .filter((e) => actorFilter === "all" || e.actor_type === actorFilter);
  }, [actorFilter, events, filterSessionId, showTechnical]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [autoScroll, visible.length]);

  return (
    <section className={`${cardClass} flex min-h-[520px] flex-col overflow-hidden`}>
      <header className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Activity</p>
            <h2 className="mt-1 text-base font-semibold text-slate-900">Simple activity feed</h2>
            <p className="mt-1 text-sm text-slate-500">Important call events only by default.</p>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="accent-cyan-400"
            />
            Auto-scroll
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setShowTechnical((value) => !value)}
            className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
              showTechnical
                ? "border-blue-300 bg-blue-50 text-blue-700"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            Show technical logs
          </button>
          {FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              onClick={() => setActorFilter(filter.id)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                actorFilter === filter.id
                  ? "border-blue-300 bg-blue-50 text-blue-700"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-auto premium-scrollbar">
        {visible.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No audit events yet"
              description="Live call, keypad, admin, and telephony events will appear here as the workflow progresses."
            />
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {visible.map((ev) => {
              const badge = TYPE_BADGE[ev.event_type] || "bg-slate-100 text-slate-600 ring-slate-200";
              return (
                <article key={ev.id} className="px-5 py-4 transition hover:bg-slate-50">
                  <div className="flex items-start justify-between gap-3">
                    <span
                      className={`inline-flex max-w-[230px] truncate rounded-full px-2.5 py-1 font-mono text-[10px] font-semibold ring-1 ring-inset ${badge}`}
                      title={ev.event_type}
                    >
                      {displayEventType(ev.event_type)}
                    </span>
                    <time className="whitespace-nowrap font-mono text-[11px] text-slate-500">
                      {formatTimestamp(ev.created_at)}
                    </time>
                  </div>
                  <div className="mt-2">
                    <ActorBadge actor={ev.actor_type} />
                  </div>
                  <p className="mt-2 break-words text-sm leading-relaxed text-slate-600">
                    {displayMessage(ev)}
                  </p>
                </article>
              );
            })}
          </div>
        )}
        <div ref={bottomRef} className="h-px" />
      </div>
    </section>
  );
}
