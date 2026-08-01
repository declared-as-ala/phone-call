const STEPS = [
  { key: "1", label: "Call & greeting", hint: "Dial and play consent prompt" },
  { key: "2", label: "OTP entry", hint: "Callee enters code, then #" },
  { key: "3", label: "Admin verification", hint: "Review and approve or deny" },
  { key: "4", label: "Completed", hint: "Call outcome recorded" },
];

function stepIndex(session) {
  if (!session) return 0;
  const st = session.status;
  const sp = session.simulator_step || "idle";

  if (["failed", "cancelled"].includes(st)) return -1;
  if (st === "completed" && sp === "finished") return 3;

  if (
    ["dialing", "ringing", "pending"].includes(st) &&
    (!sp || sp === "idle")
  )
    return 0;
  if (st === "connected" && (!sp || sp === "idle")) return 0;
  if (sp === "consent") return 0;
  if (sp === "verification_code") return 1;
  if (sp === "pending_admin_verification") return 2;
  if (sp === "waiting_admin_code_send") return 1;

  return 0;
}

export default function SimpleWorkflow({ session }) {
  const active = stepIndex(session);
  const failed = Boolean(session && ["failed", "cancelled"].includes(session.status));

  return (
    <div className="app-card overflow-hidden">
      <div className="border-b border-slate-100 bg-gradient-to-r from-slate-50 to-teal-50/40 px-4 py-3">
        <p className="app-eyebrow">Workflow</p>
        <h3 className="mt-0.5 text-sm font-semibold text-slate-900">Call progress</h3>
      </div>

      <div className="p-4">
        {failed ? (
          <p className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-900">
            This call did not complete successfully.
          </p>
        ) : null}

        <ol className="space-y-0">
          {STEPS.map((row, i) => {
            const on = failed ? false : i === active;
            const done = !failed && i < active;
            const isLast = i === STEPS.length - 1;

            return (
              <li key={row.key} className="relative flex gap-3 pb-4 last:pb-0">
                {!isLast ? (
                  <span
                    className={`absolute left-[15px] top-8 h-[calc(100%-12px)] w-px ${
                      done ? "bg-teal-300" : "bg-slate-200"
                    }`}
                    aria-hidden="true"
                  />
                ) : null}
                <span
                  className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition ${
                    on
                      ? "bg-gradient-to-br from-teal-500 to-indigo-500 text-white shadow-glow"
                      : done
                        ? "bg-teal-100 text-teal-800 ring-2 ring-teal-200"
                        : "bg-slate-100 text-slate-500 ring-1 ring-slate-200"
                  }`}
                >
                  {done ? "✓" : row.key}
                </span>
                <div className={`min-w-0 pt-0.5 ${on ? "" : "opacity-80"}`}>
                  <p className={`text-xs font-semibold ${on ? "text-slate-900" : "text-slate-700"}`}>
                    {row.label}
                  </p>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{row.hint}</p>
                  {on ? (
                    <span className="mt-1.5 inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-2 py-0.5 text-[10px] font-semibold text-teal-700">
                      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-teal-500" />
                      In progress
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
