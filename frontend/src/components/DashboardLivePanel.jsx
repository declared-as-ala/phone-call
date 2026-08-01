import { useEffect, useMemo, useState } from "react";
import { DEFAULT_CODE_LENGTH, expectedDigits, substituteSpeechTemplate } from "../utils/speechTemplate.js";
import { EmptyState, PrimaryButton, StatusBadge, cardClass } from "./ui.jsx";

function deriveBigStep(session) {
  const digits = session ? expectedDigits(session) : DEFAULT_CODE_LENGTH;
  if (!session) return { title: "No call selected", sub: "Start a verification call to begin." };
  const st = session.status;
  const sp = session.simulator_step || "idle";

  if (st === "failed") return { title: "Call failed", sub: "Attempts exhausted or fatal error." };
  if (st === "cancelled") return { title: "Cancelled", sub: "" };
  if (st === "completed" && sp === "finished") {
    if (session.ivr_outcome === "declined") return { title: "Recipient declined", sub: "" };
    if (session.ivr_outcome === "verified") return { title: "Approved · completed", sub: "" };
    return { title: "Completed", sub: "" };
  }

  switch (sp) {
    case "idle":
      return { title: "Outbound dialing / ringing", sub: "Waiting for the callee to answer." };
    case "consent":
      return {
        title: "Consent",
        sub: "Callee hears the greeting on the phone; you monitor keypad 1 (accept) or 2 (decline).",
      };
    case "waiting_admin_code_send":
      return {
        title: "Waiting for administrator to send code externally",
        sub:
          "The recipient pressed 1. Send the verification code using the client's official external platform.",
      };
    case "verification_code":
      return {
        title: "Verification code entry",
        sub: `After you click Done — code sent, the callee hears instruct to enter the ${digits}-digit code on the keypad.`,
      };
    case "pending_admin_verification":
      return {
        title: "Waiting for admin verification",
        sub: `Review the keypad entry (${digits}-digit code below), then approve or reject.`,
      };
    default:
      return { title: formatRough(sp), sub: "" };
  }
}

function formatRough(step) {
  return String(step || "")
    .split("_")
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : ""))
    .join(" ");
}

function recipientUxLine(session) {
  if (!session) return "";
  const sp = session.simulator_step;
  switch (sp) {
    case "idle":
      return "Recipient action: waiting for answer.";
    case "consent":
      return "Recipient action: waiting for 1 / 2 (consent).";
    case "waiting_admin_code_send":
      return "Recipient action: on hold listening for admin readiness (speech: please wait…).";
    case "verification_code": {
      const d = expectedDigits(session);
      return `Recipient action: waiting for ${d}-digit keypad entry.`;
    }
    case "pending_admin_verification":
      return "Recipient action: waiting while administrator verifies.";
    default:
      if (session.status === "completed") return "Recipient action: ended.";
      return "";
  }
}

/** Which speech-script key best matches what the callee hears at this coarse step */
function speechKeyFor(session) {
  if (!session) return null;
  const sp = session.simulator_step;
  if (sp === "consent") return "consent_prompt";
  if (sp === "waiting_admin_code_send") return "admin_send_code_instruction_prompt";
  if (sp === "verification_code") return "code_sent_prompt";
  if (sp === "pending_admin_verification") return "pending_admin_verification_prompt";
  return null;
}

export default function DashboardLivePanel({
  session,
  runtime,
  speechScripts,
  onConfirmAdminCodeSent,
  onSessionsRefresh,
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const big = useMemo(() => deriveBigStep(session), [session]);

  useEffect(() => {
    if (session?.simulator_step !== "waiting_admin_code_send") {
      setBusy(false);
    }
  }, [session?.id, session?.simulator_step]);

  const currentSpeech =
    speechKeyFor(session) && speechScripts
      ? substituteSpeechTemplate(speechScripts[speechKeyFor(session)], {
          name: session?.name,
          university: session?.university,
          codeLength: expectedDigits(session),
        })
      : "";

  const keypadDigits = session ? expectedDigits(session) : DEFAULT_CODE_LENGTH;

  async function confirmSent() {
    if (!session || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await onConfirmAdminCodeSent(session.id);
      await onSessionsRefresh?.();
    } catch (e) {
      setErr(e.message || "Failed to confirm code sent");
      setBusy(false);
    }
  }

  return (
    <section className={`${cardClass} overflow-hidden shadow-sm ring-2 ring-offset-4 ring-transparent`}>
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 bg-gradient-to-r from-blue-950/95 to-blue-900/90 px-5 py-4 text-blue-50">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-100">Live call provider</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight text-white">Realtime session</h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-blue-50/95">
            Primary operations view. Voice prompts play on the phone via SIP UP in real-call mode, not in this browser UI.
          </p>
        </div>
        {session ? <StatusBadge status={session.status} size="lg" /> : null}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-semibold">
          <span className="rounded-full border border-white/20 bg-white/10 px-2.5 py-1 uppercase tracking-[0.12em] text-blue-100">
            Voice path:{" "}
            <span className="text-white">
              {runtime?.voice_mode === "sip_up_call_audio" ? "SIP UP call audio" : "Mock / simulated"}
            </span>
          </span>
          {runtime?.provider_label ? (
            <span className="rounded-full border border-white/20 bg-white/10 px-2.5 py-1 uppercase tracking-[0.12em]">
              Carrier / provider:{` `}
              <span className="text-white">{runtime.provider_label}</span>
              {runtime?.provider_mode === "sip_up" ? " · SIP UP" : ""}
            </span>
          ) : null}
        </div>
      </header>

      <div className="grid gap-4 p-5">
        {!session ? (
          <EmptyState title="No active selection" description="Pick a recent call from the sidebar or begin a new one." />
        ) : (
          <>
            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Contact</p>
              <p className="mt-2 text-xl font-semibold text-slate-950">{session.name}</p>
              <p className="text-sm text-slate-600">{session.university}</p>
              <p className="mt-3 break-all font-mono text-sm text-slate-800">{session.phone_number}</p>
              {session.outbound_caller_id ? (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-800">
                    Outbound caller ID
                  </p>
                  <p className="mt-1 font-mono text-sm font-semibold text-emerald-950">{session.outbound_caller_id}</p>
                </div>
              ) : null}
            </div>

            <div className="rounded-3xl border-2 border-blue-200 bg-white p-6 shadow-inner">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">Current step</p>
              <h3 className="mt-3 text-2xl font-bold tracking-tight text-slate-950 lg:text-[1.85rem]">{big.title}</h3>
              {big.sub ? <p className="mt-3 text-sm leading-relaxed text-slate-600">{big.sub}</p> : null}

              <div className="mt-6 border-t border-slate-100 pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Recipient / channel status
                </p>
                <p className="mt-2 text-sm font-medium text-slate-800">{recipientUxLine(session)}</p>
              </div>

              {speechKeyFor(session) ? (
                <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/90 p-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                    Speech prompt (template · placeholders filled for this recipient)
                  </p>
                  <p className="mt-3 text-base leading-relaxed text-slate-900">{currentSpeech}</p>
                  <p className="mt-3 text-[11px] text-slate-500">
                    Editable keys live under Speech scripts ({speechKeyFor(session)}). Vars: {"{name}"}, {"{organization}"}, {"{code_length}"}.
                  </p>
                </div>
              ) : null}
            </div>

            {session.simulator_step === "waiting_admin_code_send" ? (
              <div className="rounded-3xl border-2 border-amber-400 bg-amber-50 p-6 shadow-md">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-800">Send verification code</p>
                <h4 className="mt-3 text-lg font-bold text-slate-950">
                  Recipient accepted · send via the client&apos;s official platform
                </h4>
                <p className="mt-2 text-sm leading-relaxed text-amber-950/85">
                  Our stack only bridges the outbound phone call plus compliant prompts. Institution staff relay the credential
                  through the client's official external systems; nothing here sends unsolicited verification messages via social
                  or third-party messaging products.
                </p>
                <p className="mt-4 text-xs font-semibold text-amber-900/90">
                  When the code has been sent externally on that platform, continue the voice flow below.
                </p>
                <div className="mt-6">
                  <PrimaryButton type="button" disabled={busy} onClick={confirmSent} className="w-full px-6 py-3 text-sm">
                    {busy ? "Updating…" : "Done — code sent"}
                  </PrimaryButton>
                </div>
                {err ? (
                  <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{err}</p>
                ) : null}
              </div>
            ) : null}

            {session.simulator_step === "verification_code" ? (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                Admin task: awaiting keypad entry. After all digits arrive, the full code appears here for approve/reject.
              </div>
            ) : null}
          </>
        )}
      </div>

      {/* Progress timeline (readable, not tied to Asterisk internals) */}
      {session ? (
        <footer className="border-t border-slate-100 bg-slate-50/80 px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Call timeline (summary)</p>
          <ol className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
            <li>• Outbound originate / ring</li>
            <li>• Answer → consent greeting</li>
            <li>• Press 1 → admin sends code externally (you confirm Done)</li>
            <li>• Code entry ({keypadDigits}-digit keypad)</li>
            <li>• Admin approve / reject (no auto-verify)</li>
            <li>• Hangup</li>
          </ol>
          <p className="mt-4 text-[11px] text-slate-500">
            Registration readiness (SIP UP trunk) is surfaced in the runtime banner when the backend publishes it via
            /api/system/runtime.
          </p>
        </footer>
      ) : null}
    </section>
  );
}
