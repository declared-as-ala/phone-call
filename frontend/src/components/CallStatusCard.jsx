import { formatStepLabel } from "../utils/phone.js";
import { EmptyState, SectionHeader, StatusBadge, cardClass } from "./ui.jsx";

function formatCreated(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export default function CallStatusCard({ session }) {
  if (!session) {
    return (
      <section className={`${cardClass} p-5`}>
        <EmptyState
          title="No active call selected"
          description="Choose a session from the queue or start a new outbound verification call."
        />
      </section>
    );
  }

  const steps = [
    { key: "started", label: "Call started" },
    { key: "consent", label: "Consent" },
    { key: "code", label: "Code entry" },
    { key: "admin", label: "Admin verification" },
    { key: "completed", label: "Completed" },
  ];
  const currentIndex =
    session.simulator_step === "consent"
      ? 1
      : session.simulator_step === "verification_code"
        ? 2
        : session.simulator_step === "pending_admin_verification"
          ? 3
          : ["completed", "failed", "cancelled"].includes(session.status)
            ? 4
            : 0;

  return (
    <section className={`${cardClass} p-5`}>
      <SectionHeader
        eyebrow="Active call"
        title="Verification status"
        description="Real-time state for the selected recipient."
        action={<StatusBadge status={session.status} size="lg" />}
      />

      <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <p className="text-lg font-semibold text-slate-950">{session.name}</p>
        <p className="text-sm text-slate-500">{session.university}</p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <dt className="text-xs text-slate-500">Current step</dt>
          <dd className="mt-1 font-medium text-slate-900">
            {formatStepLabel(session.simulator_step ?? "idle")}
          </dd>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <dt className="text-xs text-slate-500">Attempts</dt>
          <dd className="mt-1 font-medium text-slate-900">{session.wrong_code_attempts ?? 0} / 3</dd>
        </div>
        <div className="col-span-2 rounded-xl border border-slate-200 bg-white p-3">
          <dt className="text-xs text-slate-500">Phone</dt>
          <dd className="mt-1 break-all font-mono text-sm tracking-wide text-slate-900">
            {session.phone_number}
          </dd>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <dt className="text-xs text-slate-500">Started</dt>
          <dd className="mt-1 text-xs text-slate-700">{formatCreated(session.created_at)}</dd>
        </div>
      </dl>

      <div className="mt-5 space-y-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Progress timeline</p>
        <div className="space-y-2">
          {steps.map((step, index) => {
            const active = index === currentIndex;
            const done = index < currentIndex;
            return (
              <div key={step.key} className="flex items-center gap-3">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-semibold ${
                    active
                      ? "border-blue-600 bg-blue-600 text-white"
                      : done
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-slate-300 bg-white text-slate-500"
                  }`}
                >
                  {index + 1}
                </span>
                <span className={active ? "text-sm font-semibold text-slate-900" : "text-sm text-slate-500"}>
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
