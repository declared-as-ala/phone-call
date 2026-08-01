import { useEffect, useMemo, useRef, useState } from "react";
import { fetchSpeechScripts, simulatorAction, simulatorAnswered, simulatorEnterCode, simulatorPress } from "../api.js";
import { canUseSpeechSynthesis, speakDigitsSlowly, speakText, stopSpeech } from "../utils/speech.js";
import { expectedDigits, substituteSpeechTemplate } from "../utils/speechTemplate.js";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];
const AUTO_CLOSE_FINISHED_CALL_MS = 2500;

function consentPrompt(session, scripts) {
  const template =
    scripts?.consent_prompt ||
    "Hello {name}. We call from {organization}. To confirm, press 1. To decline, press 2.";
  return substituteSpeechTemplate(template, {
    name: session?.name,
    university: session?.university,
    codeLength: expectedDigits(session),
  });
}

function scriptText(scripts, key, fallback) {
  const raw = scripts?.[key];
  return typeof raw === "string" && raw.trim() ? raw : fallback;
}

function formatStep(step) {
  if (!step) return "Idle";
  return String(step)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function maskDigits(value) {
  if (!value) return "";
  if (value.length <= 2) return value;
  return `${"*".repeat(value.length - 2)}${value.slice(-2)}`;
}

function eventSortKey(ev) {
  return `${ev.created_at || ""}-${ev.id || ""}`;
}

export default function MobileCallSimulator({
  open,
  session,
  events,
  onClose,
  onRefresh,
  standalone = false,
  notice = null,
  demoCode = null,
}) {
  const [muted, setMuted] = useState(false);
  const [digits, setDigits] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [localStep, setLocalStep] = useState(null);
  const [ended, setEnded] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [lastPrompt, setLastPrompt] = useState("");
  const [transcript, setTranscript] = useState([]);
  const [incoming, setIncoming] = useState(false);
  const [speechScripts, setSpeechScripts] = useState(null);
  const seenEventIds = useRef(new Set());
  const spokenEventIds = useRef(new Set());

  const prompts = useMemo(() => {
    const subs = (key, fallback) =>
      substituteSpeechTemplate(scriptText(speechScripts, key, fallback), {
        name: session?.name,
        university: session?.university,
        codeLength: expectedDigits(session),
      });
    return {
      enterCode: "Please enter the code now.",
      enterCodeSpoken: "Local demo code was spoken. Please enter it now.",
      officialCode: subs(
        "code_sent_prompt",
        "Please enter your {code_length}-digit verification code on your keypad.",
      ),
      pendingAdmin: subs(
        "pending_admin_verification_prompt",
        "Please wait for the administrator verification.",
      ),
      approved: subs("approved_prompt", "Thank you for choosing our services."),
      rejected: subs(
        "rejected_retry_prompt",
        "Verification failed. Please repeat your {code_length}-digit verification code.",
      ),
      failed: subs("failed_prompt", "Verification failed. Please contact the administration."),
      declined: subs("declined_prompt", "Verification declined. Goodbye."),
      goodbye: subs("goodbye_prompt", "Goodbye."),
    };
  }, [session?.name, session?.university, session?.expected_digits_count, speechScripts]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchSpeechScripts()
      .then((data) => {
        if (!cancelled && data?.scripts) setSpeechScripts(data.scripts);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open]);

  const callEvents = useMemo(() => {
    if (!session) return [];
    return events
      .filter((ev) => ev.session_id === session.id)
      .slice()
      .sort((a, b) => eventSortKey(a).localeCompare(eventSortKey(b)));
  }, [events, session]);

  const effectiveStep = localStep || session?.simulator_step || "idle";
  const hasAnsweredEvent = callEvents.some((ev) => ev.event_type === "CALL_ANSWERED");
  const isPendingAdmin = effectiveStep === "pending_admin_verification";
  const isCodeEntry = effectiveStep === "verification_code";
  const isConsent = effectiveStep === "consent";
  const isTerminal =
    ended ||
    ["completed", "failed", "cancelled"].includes(session?.status) ||
    effectiveStep === "finished";

  function addTranscript(kind, text) {
    setTranscript((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${prev.length}`,
        kind,
        text,
      },
    ]);
  }

  function say(text) {
    setLastPrompt(text);
    addTranscript("SAY", text);
    speakText(text, { muted });
  }

  function speakCodeInstruction() {
    if (demoCode) {
      setLastPrompt(prompts.enterCodeSpoken);
      addTranscript("LOCAL DEMO ONLY", prompts.enterCodeSpoken);
      speakDigitsSlowly(demoCode, { muted });
      return;
    }
    say(prompts.officialCode);
  }

  function speakRetryCodeInstruction() {
    if (demoCode) {
      const message = "Code not verified. Please try again.";
      setLastPrompt(message);
      addTranscript("SAY", message);
      speakDigitsSlowly(demoCode, {
        muted,
        intro: "Code not verified. Please try again. Local demo code is:",
      });
      return;
    }
    say(prompts.rejected);
  }

  useEffect(() => {
    if (!open || !session) return;
    setDigits("");
    setBusy(false);
    setError(null);
    setEnded(false);
    setSeconds(0);
    const shouldShowIncoming =
      !hasAnsweredEvent &&
      ["pending", "dialing", "ringing"].includes(session.status || "pending");
    setIncoming(shouldShowIncoming);
    setLocalStep(shouldShowIncoming ? "incoming" : session.simulator_step || "consent");
    setTranscript([]);
    seenEventIds.current = new Set(callEvents.map((ev) => ev.id));
    spokenEventIds.current = new Set();
    if (shouldShowIncoming) {
      setLastPrompt("");
      setTranscript([]);
    } else {
      const prompt = consentPrompt(session, speechScripts);
      setLastPrompt(prompt);
      setTranscript([
        { id: "initial-say", kind: "SAY", text: prompt },
        {
          id: "initial-wait",
          kind: "WAITING FOR DTMF",
          text: "press 1 to confirm, 2 to decline",
        },
      ]);
      speakText(prompt, { muted });
    }
    return () => stopSpeech();
    // Reset only when a new modal session opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, session?.id]);

  useEffect(() => {
    if (!open || isTerminal) return undefined;
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [isTerminal, open]);

  useEffect(() => {
    if (!open || !standalone || !isTerminal) return undefined;
    const timer = window.setTimeout(() => {
      stopSpeech();
      onClose?.();
    }, AUTO_CLOSE_FINISHED_CALL_MS);
    return () => window.clearTimeout(timer);
  }, [isTerminal, onClose, open, standalone]);

  useEffect(() => {
    if (!open || !session) return;
    for (const ev of callEvents) {
      if (seenEventIds.current.has(ev.id)) continue;
      seenEventIds.current.add(ev.id);

      if (ev.event_type === "ADMIN_VERIFICATION_APPROVED") {
        addTranscript("ADMIN APPROVED", "");
        say(prompts.approved);
        setLocalStep("finished");
        setEnded(true);
      }
      if (ev.event_type === "ADMIN_VERIFICATION_REJECTED") {
        addTranscript("ADMIN REJECTED", "");
        const terminalReject = /maximum attempts/i.test(ev.message || "");
        setDigits("");
        setLocalStep(terminalReject ? "finished" : "verification_code");
        setEnded(terminalReject);
        if (terminalReject) {
          say(prompts.failed);
        } else {
          speakRetryCodeInstruction();
        }
      }
      if (ev.event_type === "VERIFICATION_SUCCESS" && !spokenEventIds.current.has(ev.id)) {
        spokenEventIds.current.add(ev.id);
        setLocalStep("finished");
        setEnded(true);
      }
      if (ev.event_type === "CALL_HANGUP") {
        say(prompts.goodbye);
        setLocalStep("finished");
        setEnded(true);
      }
    }
  }, [callEvents, open, session]);

  async function run(action) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onRefresh?.();
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function acceptIncomingCall() {
    if (!session || busy) return;
    await run(async () => {
      await simulatorAnswered(session.id);
      setIncoming(false);
      setLocalStep("consent");
      const prompt = consentPrompt(session, speechScripts);
      setLastPrompt(prompt);
      setTranscript([
        { id: "initial-say", kind: "SAY", text: prompt },
        {
          id: "initial-wait",
          kind: "WAITING FOR DTMF",
          text: "press 1 to confirm, 2 to decline",
        },
      ]);
      speakText(prompt, { muted });
    });
  }

  async function declineIncomingCall() {
    if (!session || busy) {
      onClose?.();
      return;
    }
    await run(async () => {
      await simulatorAction(session.id, { action: "hangup" });
      setIncoming(false);
      setEnded(true);
      setLocalStep("finished");
      stopSpeech();
    });
  }

  function handleKey(key) {
    if (!session || busy || isPendingAdmin || isTerminal) return;

    if (isConsent) {
      if (key !== "1" && key !== "2") return;
      run(async () => {
        const res = await simulatorPress(session.id, key);
        addTranscript("DTMF RECEIVED", key);
        if (res?.declined) {
          setLocalStep("finished");
          setEnded(true);
          say(prompts.declined);
          return;
        }
        setLocalStep("verification_code");
        speakCodeInstruction();
      });
      return;
    }

    if (isCodeEntry) {
      const maxDigits = expectedDigits(session);

      if (key === "#") {
        if (digits.length !== maxDigits) {
          setError(`Enter exactly ${maxDigits} digits to continue.`);
          return;
        }
        run(async () => {
          await simulatorEnterCode(session.id, digits);
          addTranscript("DTMF SUBMIT", digits);
          setLocalStep("pending_admin_verification");
          stopSpeech();
          say(prompts.pendingAdmin);
        });
        return;
      }

      if (!/^\d$/.test(key) || digits.length >= maxDigits) return;
      const next = `${digits}${key}`;
      setDigits(next);
      addTranscript("DTMF", key);
      if (next.length === maxDigits) {
        run(async () => {
          await simulatorEnterCode(session.id, next);
          addTranscript("DTMF SUBMIT", next);
          setLocalStep("pending_admin_verification");
          stopSpeech();
          say(prompts.pendingAdmin);
        });
      }
    }
  }

  function handleHangup() {
    if (!session || busy || isTerminal) {
      onClose?.();
      return;
    }
    run(async () => {
      await simulatorAction(session.id, { action: "hangup" });
      setEnded(true);
      setLocalStep("finished");
      say(prompts.goodbye);
    });
  }

  if (!open || !session) return null;

  const wrapperClass = standalone
    ? "flex min-h-screen items-center justify-center bg-slate-50 p-2"
    : "fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] items-center justify-center border-l border-slate-200 bg-white p-4 shadow-2xl shadow-slate-200/80 max-lg:inset-0 max-lg:max-w-none";
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");

  return (
    <div className={wrapperClass}>
      <div className="relative flex h-[calc(100vh-2rem)] max-h-[740px] w-full max-w-[390px] flex-col rounded-[2.4rem] border border-slate-200 bg-slate-100 p-3 shadow-xl shadow-slate-200">
        {incoming ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[2rem] bg-[radial-gradient(circle_at_50%_35%,rgba(16,185,129,0.35),transparent_32%),linear-gradient(160deg,#0f172a,#052e2b_45%,#111827)] px-8 py-8 text-white">
            <div className="flex items-center justify-between text-[11px] font-semibold text-white/70">
              <span>{minutes}:{secs}</span>
              <div className="h-1.5 w-20 rounded-full bg-white/25" />
              <span>LTE</span>
            </div>

            <div className="mt-10 text-center">
              <p className="text-sm uppercase tracking-[0.22em] text-white/55">Incoming call</p>
              <h2 className="mt-4 text-4xl font-light tracking-tight">{session.name}</h2>
              <p className="mt-2 text-base text-white/70">{session.university}</p>
              <p className="mt-2 font-mono text-xs text-white/45">{session.phone_number}</p>
            </div>

            <div className="mt-auto grid grid-cols-2 gap-x-12 gap-y-7 pb-6">
              <div className="text-center">
                <button
                  type="button"
                  disabled={busy}
                  className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-white/12 text-2xl text-white backdrop-blur transition hover:bg-white/20 disabled:opacity-50"
                  aria-label="Remind me"
                >
                  ⏰
                </button>
                <p className="mt-2 text-sm text-white/85">Remind Me</p>
              </div>
              <div className="text-center">
                <button
                  type="button"
                  disabled={busy}
                  className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-white/12 text-2xl text-white backdrop-blur transition hover:bg-white/20 disabled:opacity-50"
                  aria-label="Message"
                >
                  ●
                </button>
                <p className="mt-2 text-sm text-white/85">Message</p>
              </div>
              <div className="text-center">
                <button
                  type="button"
                  disabled={busy}
                  onClick={declineIncomingCall}
                  className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-500 text-3xl text-white shadow-lg shadow-red-950/30 transition hover:bg-red-400 disabled:opacity-50"
                  aria-label="Decline call"
                >
                  ✕
                </button>
                <p className="mt-2 text-sm text-white/90">Decline</p>
              </div>
              <div className="text-center">
                <button
                  type="button"
                  disabled={busy}
                  onClick={acceptIncomingCall}
                  className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-500 text-3xl text-white shadow-lg shadow-green-950/30 transition hover:bg-green-400 disabled:opacity-50"
                  aria-label="Accept call"
                >
                  ✓
                </button>
                <p className="mt-2 text-sm text-white/90">Accept</p>
              </div>
            </div>

            {error ? (
              <p className="rounded-xl border border-red-300/30 bg-red-950/30 px-3 py-2 text-xs text-red-100">
                {error}
              </p>
            ) : null}
          </div>
        ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[2rem] bg-[radial-gradient(circle_at_50%_18%,rgba(59,130,246,0.24),transparent_28%),linear-gradient(180deg,#f8fafc,#eef2ff)] text-slate-950">
          <div className="shrink-0 px-7 pt-5 text-center">
            <div className="mb-5 flex items-center justify-between text-[11px] font-semibold text-slate-500">
              <span>{minutes}:{secs}</span>
              <div className="h-1.5 w-20 rounded-full bg-slate-300" />
              <span>LTE</span>
            </div>

            <h2 className="truncate text-4xl font-light tracking-tight">{session.name}</h2>
            <p className="mt-2 text-base text-slate-500">{session.university}</p>
            <p className="mt-1 font-mono text-xs text-slate-400">{session.phone_number}</p>
            <p className="mt-4 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">
              Voice call {isTerminal ? "ended" : "active"}
            </p>
            {isPendingAdmin ? (
              <p className="mt-2 text-sm font-medium text-amber-700">Waiting for administrator verification</p>
            ) : null}
            {isCodeEntry ? (
              <p className="mt-2 text-sm font-medium text-indigo-700">Enter your verification code — submission is automatic</p>
            ) : null}
            {isCodeEntry && digits ? (
              <p className="mt-3 font-mono text-lg tracking-[0.35em] text-slate-700">
                {digits}
                <span className="ml-1 animate-pulse-soft text-teal-500">|</span>
              </p>
            ) : null}
          </div>

          {notice ? (
            <p className="mx-7 mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {notice}
            </p>
          ) : null}

          <div className="mt-auto px-6 pb-6">
            <div className="mb-5 grid grid-cols-3 gap-4 text-center">
              <button
                type="button"
                onClick={() => {
                  setMuted((value) => !value);
                  if (!muted) stopSpeech();
                }}
                className="rounded-2xl bg-white/80 px-3 py-3 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200"
              >
                {muted ? "Unmute" : "Mute"}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (isCodeEntry && demoCode) {
                    speakDigitsSlowly(demoCode, { muted });
                  } else {
                    speakText(lastPrompt, { muted });
                  }
                }}
                className="rounded-2xl bg-white/80 px-3 py-3 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200"
              >
                Replay
              </button>
              <button
                type="button"
                onClick={() => {
                  stopSpeech();
                  onClose?.();
                }}
                className="rounded-2xl bg-white/80 px-3 py-3 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200"
              >
                Close
              </button>
            </div>

            <div className="grid grid-cols-3 gap-2.5">
              {KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  disabled={busy || isPendingAdmin || isTerminal}
                  onClick={() => handleKey(key)}
                  className={`rounded-full py-3 text-xl font-semibold shadow-sm transition disabled:cursor-not-allowed disabled:opacity-35 ${
                    isConsent && (key === "1" || key === "2")
                      ? "bg-emerald-600 text-white hover:bg-emerald-500"
                      : isCodeEntry && key === "#"
                        ? "bg-gradient-to-br from-teal-500 to-indigo-500 text-white ring-2 ring-teal-200 hover:shadow-glow"
                        : "bg-white/90 text-slate-900 ring-1 ring-slate-200 hover:bg-white"
                  }`}
                >
                  {key}
                </button>
              ))}
            </div>

            <div className="mt-5 flex justify-center">
              <button
                type="button"
                onClick={handleHangup}
                className="flex h-16 w-16 items-center justify-center rounded-full bg-rose-600 text-xs font-bold uppercase text-white shadow-lg shadow-rose-950/30 hover:bg-rose-500"
              >
                End
              </button>
            </div>

            {!canUseSpeechSynthesis() ? (
              <p className="mt-3 text-center text-xs text-amber-700">
                Browser speech is not available.
              </p>
            ) : null}
            {error ? (
              <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {error}
              </p>
            ) : null}
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
