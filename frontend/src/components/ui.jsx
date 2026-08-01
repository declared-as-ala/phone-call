import { formatStepLabel } from "../utils/phone.js";

export const cardClass = "app-card";

export const labelClass =
  "block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500";

export const inputClass =
  "mt-2 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-100";

const STATUS_STYLES = {
  pending: "border-amber-200 bg-amber-50 text-amber-800",
  dialing: "border-sky-200 bg-sky-50 text-sky-800",
  ringing: "border-sky-200 bg-sky-50 text-sky-800",
  connected: "border-emerald-200 bg-emerald-50 text-emerald-800",
  collecting: "border-indigo-200 bg-indigo-50 text-indigo-800",
  pending_admin_verification: "border-amber-200 bg-amber-50 text-amber-800",
  completed: "border-emerald-200 bg-emerald-50 text-emerald-800",
  verified: "border-emerald-200 bg-emerald-50 text-emerald-800",
  failed: "border-rose-200 bg-rose-50 text-rose-800",
  cancelled: "border-slate-200 bg-slate-100 text-slate-600",
};

const ACTOR_STYLES = {
  admin: "border-sky-200 bg-sky-50 text-sky-800",
  user: "border-indigo-200 bg-indigo-50 text-indigo-800",
  system: "border-slate-200 bg-slate-100 text-slate-600",
  telephony_provider: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

export function StatusBadge({ status, children, size = "md" }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
  const padding = size === "lg" ? "px-3 py-1.5 text-xs" : "px-2.5 py-1 text-[11px]";
  return (
    <span className={`inline-flex items-center rounded-full border font-semibold capitalize ${padding} ${style}`}>
      {children || formatStepLabel(status || "pending")}
    </span>
  );
}

export function ActorBadge({ actor }) {
  const style = ACTOR_STYLES[actor] || ACTOR_STYLES.system;
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${style}`}>
      {(actor || "system").replace("_", " ")}
    </span>
  );
}

export function EmptyState({ title, description, icon = "◎" }) {
  return (
    <div className="flex min-h-44 flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed border-slate-300/80 bg-gradient-to-b from-white to-slate-50/80 p-8 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 to-indigo-500 text-lg text-white shadow-glow">
        {icon}
      </div>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      {description ? <p className="mt-2 max-w-sm text-xs leading-relaxed text-slate-500">{description}</p> : null}
    </div>
  );
}

export function SectionHeader({ eyebrow, title, description, action }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        {eyebrow ? <p className="app-eyebrow">{eyebrow}</p> : null}
        <h2 className="mt-1 text-base font-semibold tracking-tight text-slate-900">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-relaxed text-slate-500">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function PrimaryButton({ className = "", ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:from-teal-500 hover:to-teal-400 hover:shadow-glow disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    />
  );
}

export function SecondaryButton({ className = "", ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    />
  );
}

export function DangerButton({ className = "", ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...props}
    />
  );
}

export function ConnectionBadge({ connected }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold ${
        connected
          ? "border-emerald-300/40 bg-emerald-500/10 text-emerald-100"
          : "border-rose-300/40 bg-rose-500/10 text-rose-100"
      }`}
    >
      <span
        className={`app-pulse-dot ${connected ? "bg-emerald-400 text-emerald-400" : "bg-rose-400 text-rose-400"}`}
        aria-hidden="true"
      />
      {connected ? "Live feed connected" : "Live feed disconnected"}
    </span>
  );
}
