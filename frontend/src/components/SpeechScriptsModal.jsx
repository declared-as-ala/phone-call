import { useEffect, useMemo, useState } from "react";
import { canUseSpeechSynthesis, speakText, stopSpeech } from "../utils/speech.js";
import { loadStoredSpeechVolumePercent, volumePercentToBrowserVolume } from "../utils/speechVolume.js";
import { substituteSpeechTemplate } from "../utils/speechTemplate.js";
import { DangerButton, PrimaryButton, SecondaryButton } from "./ui.jsx";

/** Internal API keys unchanged — labels are client-facing only. */
const STEPS = [
  {
    key: "consent_prompt",
    title: "When the call is answered",
    helper: "Opening greeting. Both keypad 1 and 2 continue to the next step (admin wait).",
  },
  {
    key: "declined_prompt",
    title: "Declined farewell",
    helper:
      "Not played on keypad 2 at consent. Used after three administrator rejections or other terminal decline paths.",
  },
  {
    key: "admin_send_code_instruction_prompt",
    title: "After caller presses 1 or 2",
    helper:
      'Played right after consent (either key). Example: "Please wait while the administrator sends your verification code."',
  },
  {
    key: "code_sent_prompt",
    title: "After admin clicks Done",
    helper: "Now caller can enter the code.",
  },
  {
    key: "pending_admin_verification_prompt",
    title: "While admin reviews the code",
    helper: "Played after caller enters all digits.",
  },
  {
    key: "approved_prompt",
    title: "If admin accepts",
    helper: "Final success message.",
  },
  {
    key: "rejected_retry_prompt",
    title: "If admin denies and retry is allowed",
    helper: "Caller can try again.",
  },
  {
    key: "failed_prompt",
    title: "Other fatal failures",
    helper:
      "Used for abrupt session failures (not the triple reject path—that uses Declined farewell above).",
  },
  {
    key: "goodbye_prompt",
    title: "Goodbye",
    helper: "Optional final hangup message.",
  },
];

const SAMPLE_BASE = {
  name: "Test User",
  university: "Test University",
  codeLength: 6,
};

export default function SpeechScriptsModal({ open, onClose, api, onApplied }) {
  const { fetchSpeechScripts, saveSpeechScripts, resetSpeechScripts } = api;

  const [scripts, setScripts] = useState(null);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  /** Echoes persisted `call_sessions.expected_digits_count` default (editable for preview-only). */
  const [digitsPreview, setDigitsPreview] = useState(6);

  const substitutePreview = (template) =>
    substituteSpeechTemplate(template, {
      ...SAMPLE_BASE,
      codeLength: digitsPreview,
    });

  useEffect(() => {
    if (!open) {
      stopSpeech();
      setPreviewOpen(false);
      return undefined;
    }
    let cancel = false;
    (async () => {
      setErr(null);
      try {
        const data = await fetchSpeechScripts();
        if (!cancel) {
          setScripts(data.scripts);
          setDraft(data.scripts);
          onApplied?.(data.scripts);
        }
      } catch (e) {
        if (!cancel) setErr(e.message || "Could not load");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [open, fetchSpeechScripts, onApplied]);

  const previewText = useMemo(() => {
    if (!draft) return "";
    const sub = (tpl) =>
      substituteSpeechTemplate(tpl, {
        ...SAMPLE_BASE,
        codeLength: digitsPreview,
      });
    return STEPS.map((row, i) => `${i + 1}. ${sub(draft[row.key])}`).join("\n\n");
  }, [draft, digitsPreview]);

  function updateField(key, value) {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    setErr(null);
  }

  function handlePlaySample() {
    if (!previewText || !canUseSpeechSynthesis()) return;
    speakText(STEPS.map((row) => substitutePreview(draft[row.key])).filter(Boolean).join(". — "), {
      muted: false,
      volume: volumePercentToBrowserVolume(loadStoredSpeechVolumePercent()),
    });
  }

  async function handleSave() {
    if (!draft) return;
    setBusy(true);
    setErr(null);
    try {
      const data = await saveSpeechScripts(draft);
      setScripts(data.scripts);
      setDraft(data.scripts);
      onApplied?.(data.scripts);
      onClose();
    } catch (e) {
      setErr(e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    if (!window.confirm("Reset all messages to the original defaults?")) return;
    setBusy(true);
    setErr(null);
    try {
      const data = await resetSpeechScripts();
      setScripts(data.scripts);
      setDraft(data.scripts);
      onApplied?.(data.scripts);
    } catch (e) {
      setErr(e.message || "Reset failed");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3" role="dialog" aria-modal="true">
      <div className="flex max-h-[92vh] w-full max-w-md flex-col rounded-xl border border-slate-200 bg-white shadow-xl">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold text-slate-900">Call speech</h2>
          <p className="mt-1 text-xs text-slate-600">Edit what the caller hears during each step.</p>
          <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
            Placeholders: {"{name}"}, {"{organization}"}, {"{code_length}"} (digits 1–32; default 6 matches keypad
            length). SIP UP substitutes these when each prompt is rendered for a live call.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {!draft ? (
            <p className="text-sm text-slate-600">{err || "Loading…"}</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <SecondaryButton type="button" className="px-2 py-1 text-[11px]" onClick={() => setPreviewOpen((v) => !v)}>
                  {previewOpen ? "Hide preview" : "Preview sample"}
                </SecondaryButton>
                <label className="flex items-center gap-1.5 text-[10px] text-slate-600">
                  {"{code_length}"} demo
                  <select
                    className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[10px]"
                    value={digitsPreview}
                    disabled={busy}
                    onChange={(e) => setDigitsPreview(Number(e.target.value))}
                  >
                    {[4, 5, 6, 8, 10].map((n) => (
                      <option key={n} value={n}>
                        {n} digits
                      </option>
                    ))}
                  </select>
                </label>
                {canUseSpeechSynthesis() ? (
                  <SecondaryButton
                    type="button"
                    className="px-2 py-1 text-[11px]"
                    disabled={busy || !draft}
                    onClick={handlePlaySample}
                  >
                    Play sample
                  </SecondaryButton>
                ) : null}
              </div>
              {previewOpen ? (
                <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-2 py-2">
                  <p className="text-[10px] font-medium text-slate-600">Preview only — no real call</p>
                  <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap font-sans text-[11px] leading-snug text-slate-700">
                    {previewText}
                  </pre>
                </div>
              ) : null}

              <div className="mt-4 space-y-4">
                {STEPS.map((row) => (
                  <div key={row.key}>
                    <p className="text-sm font-medium text-slate-900">{row.title}</p>
                    <p className="mt-0.5 text-[11px] text-slate-500">{row.helper}</p>
                    <textarea
                      className="mt-1.5 block min-h-[3.25rem] w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-800 outline-none transition focus:border-slate-400"
                      rows={3}
                      value={draft[row.key] || ""}
                      spellCheck
                      onChange={(e) => updateField(row.key, e.target.value)}
                    />
                    <p
                      className="mt-1.5 whitespace-pre-wrap break-words rounded bg-slate-50 px-2 py-1 font-sans text-[10px] leading-snug text-slate-600"
                      title={substitutePreview(draft[row.key] || "")}
                    >
                      <span className="font-semibold text-slate-500">Sample (substituted):</span>{" "}
                      {substitutePreview(draft[row.key] || "")}
                    </p>
                  </div>
                ))}
              </div>

              {err ? <p className="mt-3 text-[11px] text-rose-700">{String(err)}</p> : null}
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-2 border-t border-slate-100 px-4 py-3">
          <PrimaryButton type="button" disabled={busy || !draft} className="px-4 py-2 text-sm" onClick={handleSave}>
            Save
          </PrimaryButton>
          <DangerButton type="button" disabled={busy} className="px-4 py-2 text-sm" onClick={handleReset}>
            Reset to defaults
          </DangerButton>
          <SecondaryButton
            type="button"
            className="ml-auto px-4 py-2 text-sm"
            onClick={() => {
              stopSpeech();
              onClose();
            }}
          >
            Cancel
          </SecondaryButton>
        </div>
      </div>
    </div>
  );
}
