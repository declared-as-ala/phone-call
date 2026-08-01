import { useEffect, useMemo, useState } from "react";
import { approveVerification, fetchAdminEnteredCode, rejectVerification } from "../api.js";
import { expectedDigits } from "../utils/speechTemplate.js";
import { buildLiveOutputLines, formatPhoneForLiveOutput } from "../utils/liveOutputLines.js";
import { formatStepLabel } from "../utils/phone.js";
import { DangerButton, PrimaryButton, SecondaryButton, StatusBadge } from "./ui.jsx";
import LiveLogs from "./LiveLogs.jsx";

/** Derive UX state bucket for admin action copy */
function adminActionBucket(session, runtime) {
  if (!session) return "none";

  const ax = runtime?.sip_up || {};
  const earlyCall =
    (!session.simulator_step || session.simulator_step === "idle") &&
    ["dialing", "ringing", "pending", "connected"].includes(session.status);
  if (runtime?.provider_mode === "sip_up" && earlyCall) {
    if (ax.ari_unreachable === true) return "sip_up_unreachable";
    if (ax.sip_trunk_endpoint_online === false) return "sip_not_registered";
  }

  const st = session.status;
  const sp = session.simulator_step;

  if (st === "failed") return "failed";
  if (st === "completed" && sp === "finished") {
    if (session.ivr_outcome === "declined") return "declined_done";
    if (session.ivr_outcome === "verified") return "completed_ok";
    return "completed_ok";
  }
  if (st === "cancelled") return "failed";

  if (sp === "idle" && ["dialing", "ringing", "pending"].includes(st)) return "dialing";
  if (sp === "idle" && st === "connected") return "dialing";
  if (sp === "consent") return "consent";
  if (sp === "waiting_admin_code_send") return "send_code";
  if (sp === "verification_code") return "waiting_code";
  if (sp === "pending_admin_verification") return "pending_admin";
  if (["completed", "failed"].includes(st)) return st === "failed" ? "failed" : "completed_ok";

  return "idle";
}

export default function LiveProviderPanel({
  session,
  runtime,
  events,
  techLogsOpen,
  onTechLogsToggle,
  onConfirmAdminCodeSent,
  onSyncLiveForCall,
}) {
  const [clearedCutoff, setClearedCutoff] = useState(null);
  const [busyCode, setBusyCode] = useState(false);
  const [busyReview, setBusyReview] = useState(false);
  const [codeErr, setCodeErr] = useState(null);
  const [codeSentKickoffHint, setCodeSentKickoffHint] = useState(false);
  const [revealedCode, setRevealedCode] = useState(null);
  const [revealError, setRevealError] = useState(null);

  useEffect(() => {
    setBusyCode(false);
    setCodeErr(null);
    setCodeSentKickoffHint(false);
    setRevealedCode(null);
    setRevealError(null);
  }, [session?.id]);

  // Full plaintext code is fetched on demand from the dedicated, audited admin
  // endpoint only once the call actually reaches admin review — never carried on
  // the general session object, and every fetch is logged server-side against the
  // signed-in admin (see backend GET /api/calls/{id}/admin/entered-code).
  useEffect(() => {
    if (!session?.id || session.simulator_step !== "pending_admin_verification") {
      return;
    }
    let cancelled = false;
    setRevealError(null);
    fetchAdminEnteredCode(session.id)
      .then((data) => {
        if (!cancelled) setRevealedCode(data.entered_code || "");
      })
      .catch((err) => {
        if (!cancelled) setRevealError(err?.message || "Could not load the entered code.");
      });
    return () => {
      cancelled = true;
    };
  }, [session?.id, session?.simulator_step]);

  useEffect(() => {
    if (session?.simulator_step !== "waiting_admin_code_send") {
      setBusyCode(false);
    }
  }, [session?.id, session?.simulator_step]);

  const visibleEvents = useMemo(() => {
    if (!clearedCutoff) return events;
    return events.filter((e) => new Date(e.created_at) > clearedCutoff);
  }, [events, clearedCutoff]);

  const lines = useMemo(
    () => buildLiveOutputLines(visibleEvents, session),
    [visibleEvents, session]
  );

  const bucket = adminActionBucket(session, runtime);

  const failureDetail = useMemo(() => {
    if (!visibleEvents?.length) return null;
    for (let i = visibleEvents.length - 1; i >= 0; i -= 1) {
      const ev = visibleEvents[i];
      if (ev?.event_type === "CALL_HANGUP" || ev?.event_type === "CALL_FAILED") {
        return String(ev.message || "").trim() || null;
      }
    }
    return null;
  }, [visibleEvents]);

  const recipientBusy = useMemo(() => {
    const msg = (failureDetail || "").toLowerCase();
    return (
      msg.includes("already on another call") ||
      (msg.includes("dialstatus") && msg.includes("busy"))
    );
  }, [failureDetail]);

  function clearOutput() {
    setClearedCutoff(new Date());
  }

  async function onDoneCodeSent() {
    if (!session || busyCode) return;
    setBusyCode(true);
    setCodeErr(null);
    try {
      await onConfirmAdminCodeSent(session.id);
      setCodeSentKickoffHint(true);
    } catch (e) {
      setCodeErr(e.message || "Could not confirm");
      setBusyCode(false);
    }
  }

  async function onApprove() {
    if (!session) return;
    setBusyReview(true);
    try {
      await approveVerification(session.id);
      await onSyncLiveForCall?.(session.id);
    } finally {
      setBusyReview(false);
    }
  }

  async function onDeny() {
    if (!session) return;
    setBusyReview(true);
    try {
      await rejectVerification(session.id);
      await onSyncLiveForCall?.(session.id);
    } finally {
      setBusyReview(false);
    }
  }

  const providerLabel =
    session?.outbound_trunk === "sip_up"
      ? "SIP UP"
      : runtime?.provider_label ||
        (runtime?.provider_mode === "sip_up" ? "SIP UP" : "Mock");

  const maxVerifyAttempts = 3;
  const attemptRound =
    session && bucket === "pending_admin"
      ? Math.min((session.wrong_code_attempts || 0) + 1, maxVerifyAttempts)
      : null;

  const keypadN = session ? expectedDigits(session) : 6;

  return (
    <div className="app-card flex h-full min-h-[24rem] flex-col overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-gradient-to-r from-white to-slate-50/80 px-5 py-4">
        <div>
          <p className="app-eyebrow">Live monitor</p>
          <h2 className="text-base font-semibold tracking-tight text-slate-900">Call provider stream</h2>
          <p className="text-[11px] text-slate-500">{providerLabel}</p>
          {session?.phone_number ? (
            <p className="mt-1 font-mono text-xs font-semibold text-slate-700">
              {formatPhoneForLiveOutput(session.phone_number)}
            </p>
          ) : null}
        </div>
        {session ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-medium text-slate-600 shadow-sm">
              {formatStepLabel(session.simulator_step || session.status)}
            </span>
            <StatusBadge status={session.status} />
          </div>
        ) : (
          <span className="text-xs text-slate-400">No active session</span>
        )}
      </div>

      <div className="mx-4 mt-4 flex min-h-[140px] max-h-[200px] flex-1 flex-col app-terminal">
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-[10px] uppercase tracking-[0.18em] text-slate-500">
          <span>Provider output</span>
          <span className="font-mono text-slate-600">live</span>
        </div>
        <div className="premium-scrollbar flex-1 overflow-y-auto px-3 py-2.5">
          {lines.length === 0 ? (
            <p className="text-slate-500">Responses from the telephony provider will appear here…</p>
          ) : (
            <ul className="space-y-1.5">
              {lines.map((row) => (
                <li key={row.key} className="whitespace-pre-wrap break-all leading-relaxed">
                  {row.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {bucket === "pending_admin" && session ? (
        <div className="mx-4 mt-4 rounded-2xl border border-teal-200/70 bg-gradient-to-br from-white to-teal-50/50 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Admin verification</h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-600">
            The callee submitted a code. Review the details and choose Accept or Deny.
          </p>
          <dl className="mt-4 grid gap-2 rounded-xl border border-slate-100 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2">
            <div>
              <dt className="text-slate-500">Recipient</dt>
              <dd className="font-medium text-slate-900">{session.name || "—"}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Service name</dt>
              <dd className="font-medium text-slate-900">{session.university || "—"}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Phone</dt>
              <dd className="font-mono tracking-tight text-slate-800">
                {formatPhoneForLiveOutput(session.phone_number)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Attempts</dt>
              <dd className="font-semibold tabular-nums text-slate-900">
                {attemptRound} / {maxVerifyAttempts}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-slate-500">Submitted OTP</dt>
              <dd className="mt-1 inline-block rounded-lg bg-slate-900 px-3 py-2 font-mono text-lg font-semibold tracking-[0.35em] text-emerald-300">
                {revealedCode || (revealError ? session.masked_entered_code : "…") || "—"}
              </dd>
              {revealError ? (
                <p className="mt-1 text-[11px] text-rose-600">{revealError} Showing masked value.</p>
              ) : null}
            </div>
          </dl>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              disabled={busyReview}
              onClick={onApprove}
              className="rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-3 text-base font-semibold text-white shadow-sm transition hover:from-emerald-500 hover:to-teal-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Accept
            </button>
            <DangerButton type="button" className="w-full py-3 text-base font-semibold" disabled={busyReview} onClick={onDeny}>
              Deny
            </DangerButton>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <SecondaryButton type="button" className="px-3 py-1.5 text-xs" onClick={clearOutput}>
          Clear logs
        </SecondaryButton>
        <SecondaryButton type="button" className="px-3 py-1.5 text-xs" onClick={() => onTechLogsToggle?.()}>
          {techLogsOpen ? "Hide technical logs" : "Show technical logs"}
        </SecondaryButton>
      </div>

      {techLogsOpen && session ? (
        <div className="max-h-48 overflow-auto border-t border-slate-200 px-2 py-2">
          <LiveLogs events={events} filterSessionId={session.id} />
        </div>
      ) : null}

      {bucket !== "pending_admin" ? (
      <div className="mt-auto border-t border-slate-100 bg-gradient-to-b from-slate-50/50 to-white px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Current action</p>
        <div className="mt-2 min-h-[5rem] text-sm leading-relaxed text-slate-800">
          {bucket === "none" && <p>No active call</p>}

          {bucket === "sip_up_unreachable" && (
            <p className="text-amber-800">
              Cannot reach SIP UP media service (ARI). Check that the API host/port and credentials are correct and the SIP UP media HTTP
              service is running.
            </p>
          )}

          {bucket === "sip_not_registered" && (
            <div>
              <p className="font-medium text-rose-800">Provider not registered</p>
              <p className="mt-1 text-xs text-slate-600">
                SIP trunk may not appear online in ARI endpoints. If SIP UP uses IP auth without REGISTER,
                outbound may still work; otherwise run{" "}
                <code className="rounded bg-slate-200 px-1">pjsip show registrations</code>.
              </p>
            </div>
          )}

          {bucket === "idle" && session && <p>Waiting for activity…</p>}

          {bucket === "dialing" && (
            <p>
              Calling recipient… When SIP UP returns ringing (183/180), the log shows{" "}
              <span className="font-mono text-xs">ringing</span> before connect.
            </p>
          )}

          {bucket === "consent" && (
            <div className="space-y-2">
              <p>
                Greeting is playing on the phone. Callee presses{" "}
                <span className="font-medium">1</span> to confirm or <span className="font-medium">2</span> to
                decline — either choice is shown in the output log and the call continues to OTP entry.
              </p>
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
                If <span className="font-mono">{formatPhoneForLiveOutput(session?.phone_number)}</span> never
                rang: our app can show &quot;SIP connected&quot; while SIP UP still marks the call{" "}
                <strong>FAILED 0:00</strong> in their dashboard. Authorize caller ID{" "}
                <span className="font-mono">{session?.outbound_caller_id || "—"}</span> and whitelist your public IP
                in SIP UP — unauthorized CLI is the usual cause.
              </p>
            </div>
          )}

          {bucket === "send_code" && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3">
              <p className="text-xs font-bold uppercase tracking-wide text-amber-900">Send code now</p>
              <p className="mt-2 text-sm text-amber-950">
                Recipient accepted. Send the OTP code using the client&apos;s official external
                platform, then click Done.
              </p>
              <PrimaryButton type="button" className="mt-3 w-full py-2 text-sm" disabled={busyCode} onClick={onDoneCodeSent}>
                {busyCode ? "Updating…" : "Done — code sent"}
              </PrimaryButton>
              {codeSentKickoffHint ? (
                <p className="mt-2 text-xs font-medium text-emerald-900">
                  The callee should hear the code-entry speech as soon as the ARI bridge consumes the server event (hosted TTS +
                  docker copy often needs ~1–2s). Set <code className="rounded bg-amber-100 px-0.5">SIPUP_ADMIN_CODE_SENT_AUDIO_MODE=sipup</code>{" "}
                  on the bridge to play your pre-recorded <code className="rounded bg-amber-100 px-0.5">ivr/code-sent</code> sound
                  instantly.
                </p>
              ) : null}
              {codeErr ? <p className="mt-2 text-xs text-rose-700">{codeErr}</p> : null}
            </div>
          )}

          {bucket === "waiting_code" && (
            <div className="space-y-2 rounded-xl border border-indigo-200/70 bg-indigo-50/60 px-3 py-3">
              <p>
                Monitoring keypad — waiting for the callee to enter an OTP code (4, 6, 8, or 10 digits).
              </p>
              <p className="text-[11px] leading-relaxed text-indigo-950/80">
                Each digit is forwarded immediately. The callee must press <strong>#</strong> (pound) to
                confirm and submit the code. Once submitted, Accept / Deny controls appear above.
              </p>
            </div>
          )}

          {bucket === "completed_ok" && <p>Verification completed</p>}
          {bucket === "declined_done" && <p>Recipient declined — call ended</p>}
          {bucket === "failed" && (
            <div>
              <p className="font-medium text-rose-800">
                {recipientBusy ? "Recipient busy — call declined" : "Call failed"}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Dialed {formatPhoneForLiveOutput(session?.phone_number)} with caller ID{" "}
                <span className="font-mono">{session?.outbound_caller_id || "—"}</span>.
              </p>
              {failureDetail ? (
                <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-950">
                  {failureDetail}
                </p>
              ) : (
                <p className="mt-1 text-xs text-slate-600">
                  Check the activity log below. SIP UP rejections are often SIP 403 — whitelist your
                  public IP in the SIP UP dashboard and authorize the caller ID.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
      ) : null}
    </div>
  );
}
