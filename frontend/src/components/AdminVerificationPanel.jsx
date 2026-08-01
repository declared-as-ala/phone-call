import { useEffect, useState } from "react";
import { approveVerification, fetchAdminEnteredCode, rejectVerification } from "../api.js";
import { DangerButton, EmptyState, PrimaryButton, SectionHeader, cardClass } from "./ui.jsx";

export default function AdminVerificationPanel({ session, onResolved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [enteredCode, setEnteredCode] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setEnteredCode(null);
    setError(null);
    if (!session || session.simulator_step !== "pending_admin_verification") return undefined;

    fetchAdminEnteredCode(session.id)
      .then((data) => {
        if (!cancelled) setEnteredCode(data.entered_code);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load entered code");
      });

    return () => {
      cancelled = true;
    };
  }, [session?.id, session?.simulator_step]);

  if (!session || session.simulator_step !== "pending_admin_verification") {
    return (
      <section className={`${cardClass} p-5`}>
        <SectionHeader
          eyebrow="Admin review"
          title="Pending admin verification"
          description="Manual approval controls appear here when a recipient submits a code."
        />
        <div className="mt-4">
          <EmptyState
            title="No verification waiting for approval"
            description="The dashboard will surface the submitted code and decision controls when the call reaches admin verification."
          />
        </div>
      </section>
    );
  }

  async function run(action) {
    setBusy(true);
    setError(null);
    try {
      await action(session.id);
      await onResolved?.();
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <SectionHeader
          eyebrow="Action required"
          title="Pending admin verification"
          description="The recipient finished entering the OTP code. Review the full entry, then approve or reject."
        />
      </div>

      <div className="mt-5">
        <div className="rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            OTP code
          </p>
          <p className="mt-4 break-all font-mono text-5xl font-black tracking-[0.16em] text-slate-900">
            {enteredCode || "Loading..."}
          </p>
          <p className="mt-2 text-sm text-slate-500">
            Full digits shown for admin review.
          </p>
        </div>
      </div>

      <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
        Admin approves or rejects manually. No auto-verification or AI verification is used.
      </p>

      <div className="mt-4 flex flex-wrap gap-3">
        <PrimaryButton
          type="button"
          disabled={busy}
          onClick={() => run(approveVerification)}
        >
          Approve verification
        </PrimaryButton>
        <DangerButton
          type="button"
          disabled={busy}
          onClick={() => run(rejectVerification)}
        >
          Reject and retry
        </DangerButton>
      </div>

      {error ? (
        <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
