import { EmptyState, cardClass } from "./ui.jsx";

const PIPELINE = [
  {
    key: "call_started",
    label: "Call started",
    test: (s) => {
      if (!s) return false;
      const idle = !s.simulator_step || s.simulator_step === "idle";
      if (!idle) return false;
      const st = (s.status || "").toLowerCase();
      return (
        ["dialing", "ringing", "pending", "connected"].includes(st) &&
        !["completed", "failed", "cancelled"].includes(st)
      );
    },
  },
  { key: "consent", label: "Consent", test: (s) => !!s && s.simulator_step === "consent" },
  {
    key: "waiting_admin_external",
    label: "Code sent externally",
    test: (s) => !!s && s.simulator_step === "waiting_admin_code_send",
  },
  {
    key: "verification_code_entry",
    label: "Code entry",
    test: (s) => !!s && s.simulator_step === "verification_code",
  },
  {
    key: "pending_admin_review",
    label: "Admin verification",
    test: (s) => !!s && s.simulator_step === "pending_admin_verification",
  },
  {
    key: "finished",
    label: "Completed / failed",
    test: (s) =>
      !!s &&
      (["completed", "failed", "cancelled"].includes(s.status) || s.simulator_step === "finished"),
  },
];

function deriveActiveIndex(session) {
  if (!session) return 0;
  for (let i = PIPELINE.length - 1; i >= 0; i -= 1) {
    if (PIPELINE[i].test(session)) return i;
  }
  return 0;
}

export default function CallStatesRail({ session }) {
  const activeIndex = deriveActiveIndex(session);

  return (
    <section className={`${cardClass} p-4`}>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Workflow</p>
        <h2 className="mt-1 text-base font-semibold text-slate-900">Call states</h2>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Highlights the coarse IVR milestone. Detailed timing lives in optional technical logs.
        </p>
      </div>
      {!session ? (
        <div className="mt-6">
          <EmptyState title="No session selected" description="Open a recent call above or start a new one." />
        </div>
      ) : (
        <ol className="mt-5 space-y-2">
          {PIPELINE.map((row, idx) => {
            const active = idx === activeIndex;
            const done = idx < activeIndex;
            return (
              <li key={row.key} className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-3">
                <span
                  className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold ${
                    active
                      ? "border-blue-600 bg-blue-600 text-white"
                      : done
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : "border-slate-200 bg-slate-50 text-slate-500"
                  }`}
                >
                  {idx + 1}
                </span>
                <div>
                  <p className={`text-sm ${active ? "font-semibold text-slate-900" : "text-slate-600"}`}>{row.label}</p>
                  {active ? <p className="mt-1 text-[11px] text-blue-700">Active state</p> : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
