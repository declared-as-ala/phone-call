import { useEffect, useState } from "react";
import { fetchLuvVoiceStatus } from "../api.js";
import { PrimaryButton, SecondaryButton } from "./ui.jsx";

const FIXED_SPEECH_VOLUME = 70;

export default function SpeechEngineSelectModal({
  open,
  providerLabel,
  destinationE164 = "",
  callerIdLabel,
  callerIdDigits = "",
  authorizedCallerId = "",
  onClose,
  onConfirm,
}) {
  const [engine, setEngine] = useState("free");
  const [luvvoiceOk, setLuvvoiceOk] = useState(true);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!open) return;
    setEngine("free");
    setChecking(true);
    fetchLuvVoiceStatus()
      .then((s) => setLuvvoiceOk(Boolean(s?.configured)))
      .catch(() => setLuvvoiceOk(false))
      .finally(() => setChecking(false));
  }, [open]);

  if (!open) return null;

  function startCall() {
    onConfirm({
      speech_engine: engine,
      luvvoice_voice_id: null,
      speech_volume_percent: FIXED_SPEECH_VOLUME,
    });
  }

  const luvvoiceBlocked = engine === "luvvoice" && !luvvoiceOk;
  const selectedCallerDigits = String(callerIdDigits || callerIdLabel || "").replace(/\D/g, "");
  const authorizedDigits = String(authorizedCallerId || "").replace(/\D/g, "");
  const callerIdUnverified =
    selectedCallerDigits &&
    authorizedDigits &&
    selectedCallerDigits !== authorizedDigits;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3"
      role="dialog"
      aria-modal="true"
      aria-labelledby="speech-engine-modal-title"
    >
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <h2 id="speech-engine-modal-title" className="text-lg font-semibold text-slate-900">
          Call speech
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Provider: <span className="font-medium">{providerLabel}</span>
          {callerIdLabel ? (
            <>
              {" "}
              · Caller ID: <span className="font-medium">{callerIdLabel}</span>
            </>
          ) : null}
        </p>
        {destinationE164 ? (
          <p className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-950">
            Calling recipient: <span className="font-mono font-semibold">{destinationE164}</span>
          </p>
        ) : null}
        {callerIdUnverified ? (
          <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">
            Caller ID <span className="font-mono">{callerIdLabel}</span> is not the account default (
            <span className="font-mono">{authorizedCallerId}</span>). SIP UP may accept the call but not
            ring the phone unless this CLI is authorized in their dashboard.
          </p>
        ) : null}

        <fieldset className="mt-5 space-y-2">
          <legend className="sr-only">Speech engine</legend>
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 ${
              engine === "luvvoice" ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"
            }`}
          >
            <input
              type="radio"
              name="speech-engine"
              className="mt-1"
              checked={engine === "luvvoice"}
              onChange={() => setEngine("luvvoice")}
            />
            <span>
              <span className="block text-sm font-semibold text-slate-900">LuvVoice (premium AI)</span>
              <span className="mt-0.5 block text-xs text-slate-600">
                Natural voice on the phone call. Speech is prepared while the phone rings (uses your
                default voice from backend settings).
              </span>
            </span>
          </label>
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 ${
              engine === "free" ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"
            }`}
          >
            <input
              type="radio"
              name="speech-engine"
              className="mt-1"
              checked={engine === "free"}
              onChange={() => setEngine("free")}
            />
            <span>
              <span className="block text-sm font-semibold text-slate-900">Free system voice</span>
              <span className="mt-0.5 block text-xs text-slate-600">
                Built-in macOS / server TTS. No LuvVoice API needed.
              </span>
            </span>
          </label>
        </fieldset>

        {checking ? (
          <p className="mt-3 text-xs text-slate-500">Checking LuvVoice…</p>
        ) : null}
        {!checking && !luvvoiceOk ? (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            LuvVoice API token is not set in <code className="font-mono">backend/.env</code>. Choose
            Free system voice or add <code className="font-mono">LUVVOICE_API_TOKEN</code>.
          </p>
        ) : null}

        <div className="mt-6 flex justify-end gap-2">
          <SecondaryButton type="button" className="px-4 py-2 text-sm" onClick={onClose}>
            Cancel
          </SecondaryButton>
          <PrimaryButton
            type="button"
            className="px-4 py-2 text-sm"
            onClick={startCall}
            disabled={luvvoiceBlocked}
          >
            Start call
          </PrimaryButton>
        </div>
      </div>
    </div>
  );
}
