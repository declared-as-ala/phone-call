import { useEffect, useState } from "react";
import { substituteSpeechTemplate, VALID_OTP_LENGTHS, coerceOtpDigitCount, DEFAULT_OTP_DIGIT_COUNT } from "../utils/speechTemplate.js";
import { DangerButton, PrimaryButton, SectionHeader, SecondaryButton, cardClass } from "./ui.jsx";

const SAMPLE_PREVIEW = {
  name: "Sample recipient",
  university: "Sample service",
  codeLength: DEFAULT_OTP_DIGIT_COUNT,
};

/** Four main paragraphs the operator edits; other keys stay in sync on load/save. */
const PART_ORDER = [
  {
    key: "consent_prompt",
    label: "Part 1 — Greeting & confirm / decline",
    helper: "Played when the callee answers. Press 1 confirms; press 2 declines.",
  },
  {
    key: "code_sent_prompt",
    label: "Part 2 — OTP entry",
    helper: "Played after the callee presses 1 or 2. Callee enters the configured digit count; submission is automatic.",
  },
  {
    key: "pending_admin_verification_prompt",
    label: "Part 3 — Waiting for administrator",
    helper: "Played after all digits are entered while you review on the dashboard.",
  },
  {
    key: "approved_prompt",
    label: "Part 4 — Final thank you",
    helper: "Played when you click Accept after verification.",
  },
];

const SECONDARY_KEYS = [
  "rejected_retry_prompt",
  "declined_prompt",
  "goodbye_prompt",
  "failed_prompt",
  "admin_send_code_instruction_prompt",
];

export default function SpeechScriptsPanel({ api, onApplied }) {
  const { fetchSpeechScripts, saveSpeechScripts, resetSpeechScripts } = api;

  const [scripts, setScripts] = useState(null);
  const [draft, setDraft] = useState(null);
  const [otpDigitCount, setOtpDigitCount] = useState(DEFAULT_OTP_DIGIT_COUNT);
  const [draftOtpDigitCount, setDraftOtpDigitCount] = useState(DEFAULT_OTP_DIGIT_COUNT);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [okMsg, setOkMsg] = useState(null);

  useEffect(() => {
    let cancel = false;
    (async () => {
      setErr(null);
      try {
        const data = await fetchSpeechScripts();
        if (!cancel) {
          setScripts(data.scripts);
          setDraft(data.scripts);
          const count = coerceOtpDigitCount(data.otp_digit_count);
          setOtpDigitCount(count);
          setDraftOtpDigitCount(count);
          onApplied?.(data.scripts);
        }
      } catch (e) {
        if (!cancel) setErr(e.message || "Could not load speech scripts");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [fetchSpeechScripts, onApplied]);

  if (!draft) {
    return (
      <section className={`${cardClass} p-4 text-sm text-slate-600`}>{err ? err : "Loading speech scripts…"}</section>
    );
  }

  function updateField(key, value) {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setOkMsg(null);
  }

  async function onSave() {
    setBusy(true);
    setErr(null);
    setOkMsg(null);
    try {
      const data = await saveSpeechScripts(draft, draftOtpDigitCount);
      setScripts(data.scripts);
      setDraft(data.scripts);
      const count = coerceOtpDigitCount(data.otp_digit_count);
      setOtpDigitCount(count);
      setDraftOtpDigitCount(count);
      onApplied?.(data.scripts);
      setOkMsg("Speech scripts saved.");
    } catch (e) {
      setErr(e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    if (!window.confirm("Reset all speech prompts to packaged defaults?")) return;
    setBusy(true);
    setErr(null);
    setOkMsg(null);
    try {
      const data = await resetSpeechScripts();
      setScripts(data.scripts);
      setDraft(data.scripts);
      const count = coerceOtpDigitCount(data.otp_digit_count);
      setOtpDigitCount(count);
      setDraftOtpDigitCount(count);
      onApplied?.(data.scripts);
      setOkMsg("Templates reset to defaults.");
    } catch (e) {
      setErr(e.message || "Reset failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className={`${cardClass} overflow-hidden`}>
      <summary className="cursor-pointer list-none px-4 py-3 marker:content-none [&::-webkit-details-marker]:hidden">
        <SectionHeader
          eyebrow="Configuration"
          title="Speech scripts (4 parts)"
          description="Edit every paragraph the callee hears on the phone"
        />
      </summary>
      <div className="border-t border-slate-100 px-4 py-4">
        <div className="mb-4 rounded-2xl border border-teal-100 bg-teal-50/60 px-4 py-3">
          <label className="block">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-900">
              Verification code length
            </span>
            <p className="mt-0.5 text-[11px] text-teal-800/80">
            Callees must enter exactly this many digits; submission happens automatically.
            </p>
            <select
              className="mt-2 w-full rounded-xl border border-teal-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800"
              value={draftOtpDigitCount}
              onChange={(e) => {
                setDraftOtpDigitCount(coerceOtpDigitCount(Number(e.target.value)));
                setOkMsg(null);
              }}
            >
              {VALID_OTP_LENGTHS.map((n) => (
                <option key={n} value={n}>
                  {n} digits
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid gap-4">
          {PART_ORDER.map(({ key, label, helper }) => (
            <label key={key} className="block">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-700">{label}</span>
              <p className="mt-0.5 text-[11px] text-slate-500">{helper}</p>
              <textarea
                className="mt-1.5 block min-h-[4.5rem] w-full resize-y rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-inner"
                spellCheck="false"
                value={draft[key] || ""}
                onChange={(e) => updateField(key, e.target.value)}
              />
              {(draft[key] || "").includes("{") ? (
                <p className="mt-1.5 whitespace-pre-wrap break-words rounded-lg bg-slate-50 px-2 py-1.5 text-[10px] leading-snug text-slate-600">
                  <span className="font-semibold text-slate-500">Sample:</span>{" "}
                  {substituteSpeechTemplate(draft[key] || "", {
                    ...SAMPLE_PREVIEW,
                    codeLength: draftOtpDigitCount,
                  })}
                </p>
              ) : null}
            </label>
          ))}
        </div>

        <button
          type="button"
          className="mt-3 text-[11px] font-semibold text-slate-500 hover:text-slate-800"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? "Hide" : "Show"} retry / decline / other prompts
        </button>

        {showAdvanced ? (
          <div className="mt-3 grid gap-2 border-t border-slate-100 pt-3">
            {SECONDARY_KEYS.map((key) => (
              <label key={key} className="block">
                <span className="font-mono text-[10px] text-slate-400">{key}</span>
                <textarea
                  className="mt-1 block min-h-[3rem] w-full resize-y rounded-xl border border-slate-200 px-2 py-1.5 text-xs"
                  value={draft[key] || ""}
                  onChange={(e) => updateField(key, e.target.value)}
                />
              </label>
            ))}
          </div>
        ) : null}

        <p className="mt-4 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
          Variables: {"{name}"}, {"{organization}"}, {"{code_length}"} (currently {draftOtpDigitCount}),{" "}
          {"{code_segments}"} (same as code length).
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <PrimaryButton type="button" disabled={busy} onClick={onSave}>
            Save templates
          </PrimaryButton>
          <SecondaryButton
            type="button"
            disabled={busy || !scripts}
            onClick={() => {
              if (!draft || !scripts) return;
              setDraft({ ...scripts });
              setDraftOtpDigitCount(otpDigitCount);
            }}
          >
            Revert
          </SecondaryButton>
          <DangerButton type="button" disabled={busy} onClick={onReset}>
            Reset defaults
          </DangerButton>
        </div>
        {okMsg ? <p className="mt-3 text-xs font-semibold text-emerald-700">{okMsg}</p> : null}
        {err ? <pre className="mt-3 max-h-48 overflow-auto rounded-xl bg-rose-50 p-2 text-[11px] text-rose-800">{err}</pre> : null}
      </div>
    </details>
  );
}
