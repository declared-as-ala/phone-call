import { useState } from "react";
import { simulatorAnswered, simulatorEnterCode, simulatorPress } from "../api.js";
import { SecondaryButton, cardClass } from "./ui.jsx";

const btnBase =
  "inline-flex items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-45";

export default function SimulatorPanel({ sessionId, disabled, onBeforeAnswer, onAnswered }) {
  const [codeDigits, setCodeDigits] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run(fn) {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const inactive = disabled || !sessionId;

  return (
    <section className={`${cardClass} p-5`}>
      <div className="border-b border-slate-200 pb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Recipient simulator</p>
        <h2 className="mt-1 text-base font-semibold text-slate-900">Call controls</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-500">
          Answer the local call and use the phone panel to enter an OTP code (4, 6, 8, or 10 digits).
        </p>
      </div>

      <div className="mt-4 space-y-4">
        <div className="flex flex-wrap gap-2">
          <SecondaryButton
            type="button"
            disabled={inactive || busy}
            onClick={() =>
              run(async () => {
                const mobileWindow = onBeforeAnswer?.();
                try {
                  await simulatorAnswered(sessionId);
                  await onAnswered?.(mobileWindow);
                } catch (err) {
                  if (mobileWindow && !mobileWindow.closed) {
                    mobileWindow.close();
                  }
                  throw err;
                }
              })
            }
          >
            Answer Call
          </SecondaryButton>
          <button
            type="button"
            disabled={inactive || busy}
            onClick={() => run(() => simulatorPress(sessionId, "1"))}
            title="Confirm (continue to OTP entry)"
            className={`${btnBase} border border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200`}
          >
            Confirm (1)
          </button>
          <button
            type="button"
            disabled={inactive || busy}
            onClick={() => run(() => simulatorPress(sessionId, "2"))}
            className={`${btnBase} border border-slate-300 bg-slate-100 text-slate-700 hover:bg-slate-200`}
          >
            Decline (2)
          </button>
        </div>

        <div>
          <label className="block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Student card number
          </label>
          <div className="mt-1.5 flex gap-2">
            <input
              className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 font-mono text-sm tracking-[0.16em] text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              value={codeDigits}
              onChange={(e) => setCodeDigits(e.target.value.replace(/\D/g, "").slice(0, 12))}
              placeholder="12 digits (6+4+2)"
              autoComplete="off"
              inputMode="numeric"
              maxLength={12}
            />
            <button
              type="button"
              disabled={inactive || busy || codeDigits.length !== 6}
              onClick={() =>
                run(async () => {
                  await simulatorEnterCode(sessionId, codeDigits);
                  setCodeDigits("");
                })
              }
              className={`${btnBase} shrink-0 bg-blue-600 px-4 text-white hover:bg-blue-700`}
            >
              Submit Code
            </button>
          </div>
        </div>
      </div>

      {error ? (
        <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
