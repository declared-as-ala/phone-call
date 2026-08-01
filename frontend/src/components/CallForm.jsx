import { useEffect, useState } from "react";
import { startCall, fetchOutboundSpacing, endActiveCall } from "../api.js";
import { inputClass, labelClass, PrimaryButton, SecondaryButton, SectionHeader, cardClass } from "./ui.jsx";
import {
  COUNTRY_DIAL_CODES,
  DEFAULT_COUNTRY_ISO,
} from "../utils/countryDialCodes.js";
import {
  composeDestinationE164,
  destinationCountryMismatch,
  parseInternationalPhoneInput,
} from "../utils/phoneInput.js";
import {
  getGlobalCookie,
  removeGlobalCookie,
  setGlobalCookie,
} from "../utils/globalCookies.js";
import {
  loadCallerIdPresets,
  presetsWithConfiguredCallerId,
} from "../utils/callerIdPresets.js";
import CallerIdSelectModal from "./CallerIdSelectModal.jsx";
import CallerIdManageModal from "./CallerIdManageModal.jsx";
import SpeechEngineSelectModal from "./SpeechEngineSelectModal.jsx";
import SipUpAccountEditModal from "./SipUpAccountEditModal.jsx";

const DEFAULT_CALL_SPEECH = {
  speech_engine: "free",
  luvvoice_voice_id: null,
  speech_volume_percent: 70,
};

const defaultCountry =
  COUNTRY_DIAL_CODES.find((country) => country.iso === DEFAULT_COUNTRY_ISO) || COUNTRY_DIAL_CODES[0];

function sanitizeNationalNumber(value) {
  return String(value || "").replace(/\D/g, "");
}

/** Strip redundant NANP trunk digit when dial code is already +1 (US/CA/etc.). */
function normalizeNationalDigitsForDialCode(dialCode, nationalDigits) {
  let d = sanitizeNationalNumber(nationalDigits);
  if (!d) return "";
  const dc = String(dialCode || "").trim();
  if ((dc === "+1" || dc === "1") && d.length === 11 && d.startsWith("1")) {
    d = d.slice(1);
  }
  return d;
}

function formatNationalNumber(value, iso) {
  const digits = sanitizeNationalNumber(value);
  if (!digits) return "";
  if (iso === "TN") {
    const parts = [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 8)].filter(Boolean);
    return parts.join(" ");
  }
  if (iso === "IT") {
    const parts = [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6, 10)].filter(Boolean);
    return parts.join(" ");
  }
  return digits.replace(/(\d{3})(?=\d)/g, "$1 ").trim();
}

const NATIONAL_PLACEHOLDER_BY_ISO = {
  IT: "333 123 4567",
  DE: "30 12345678",
  KW: "5000 1234",
  US: "555 123 4567",
  TN: "26 565 725",
};

const RECENT_ORGANIZATIONS_KEY = "ivr_recent_organizations";
const MAX_RECENT_ORGANIZATIONS = 20;

function loadRecentOrganizations() {
  try {
    const parsed = JSON.parse(getGlobalCookie(RECENT_ORGANIZATIONS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function storeRecentOrganization(value, existing) {
  const clean = value.trim();
  if (!clean) return existing;
  const next = [
    clean,
    ...existing.filter((item) => item.toLowerCase() !== clean.toLowerCase()),
  ].slice(0, MAX_RECENT_ORGANIZATIONS);
  try {
    setGlobalCookie(RECENT_ORGANIZATIONS_KEY, JSON.stringify(next));
  } catch {
    return existing;
  }
  return next;
}

const MOBILE_WINDOW_FEATURES = "width=420,height=760,menubar=no,toolbar=no,location=no,status=no";

export default function CallForm({
  onCreated,
  enableMobileSimulator = false,
  simple = false,
  startConfirmMessage = null,
  /** Increment from parent (e.g. "New call") to clear fields without remounting. */
  resetSignal = 0,
  runtime = null,
  onRuntimeRefresh = null,
  onResumeActiveCall = null,
  onActiveCallEnded = null,
}) {
  const [name, setName] = useState("");
  const [university, setUniversity] = useState("");
  const [recentOrganizations, setRecentOrganizations] = useState(loadRecentOrganizations);
  const [showOrganizationSuggestions, setShowOrganizationSuggestions] = useState(false);
  const [selectedIso, setSelectedIso] = useState(DEFAULT_COUNTRY_ISO);
  const [nationalNumber, setNationalNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [callerIdModalOpen, setCallerIdModalOpen] = useState(false);
  const [speechModalOpen, setSpeechModalOpen] = useState(false);
  const [callerIdManageOpen, setCallerIdManageOpen] = useState(false);
  const [sipUpAccountEditOpen, setSipUpAccountEditOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState(null);
  const [pendingTrunk, setPendingTrunk] = useState(null);
  const [pendingCallerId, setPendingCallerId] = useState(null);
  const [callerIdPresets, setCallerIdPresets] = useState(loadCallerIdPresets);
  const [outboundSpacing, setOutboundSpacing] = useState(null);
  const [endingActiveCall, setEndingActiveCall] = useState(false);

  const spacingBlocked = outboundSpacing && !outboundSpacing.allowed;
  const spacingWait = spacingBlocked ? Number(outboundSpacing.wait_seconds || 0) : 0;
  const activeCallId = spacingBlocked && outboundSpacing?.reason === "active_call"
    ? outboundSpacing.active_call_id
    : null;

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function refresh() {
      try {
        const row = await fetchOutboundSpacing();
        if (!cancelled) setOutboundSpacing(row);
        if (!cancelled && row && !row.allowed) {
          timer = setTimeout(refresh, 1000);
        }
      } catch {
        if (!cancelled) setOutboundSpacing(null);
      }
    }
    refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [resetSignal]);

  const selectedCountry =
    COUNTRY_DIAL_CODES.find((country) => country.iso === selectedIso) || defaultCountry;

  const destinationPreview = composeDestinationE164(selectedCountry, nationalNumber);
  const countryMismatch = destinationCountryMismatch(selectedIso, destinationPreview);

  function handleNationalNumberChange(raw) {
    const parsed = parseInternationalPhoneInput(raw, COUNTRY_DIAL_CODES);
    if (parsed) {
      setSelectedIso(parsed.iso);
      setNationalNumber(parsed.nationalDigits);
      return;
    }
    setNationalNumber(sanitizeNationalNumber(raw));
  }

  useEffect(() => {
    setRecentOrganizations(loadRecentOrganizations());
  }, [resetSignal]);

  useEffect(() => {
    if (!resetSignal) return;
    setName("");
    setUniversity("");
    setSelectedIso(DEFAULT_COUNTRY_ISO);
    setNationalNumber("");
    setError(null);
    setShowOrganizationSuggestions(false);
    setCallerIdModalOpen(false);
    setSpeechModalOpen(false);
    setCallerIdManageOpen(false);
    setSipUpAccountEditOpen(false);
    setPendingStart(null);
    setPendingTrunk(null);
    setPendingCallerId(null);
  }, [resetSignal]);

  async function runStartWithTrunk(
    outbound_trunk,
    startPayload = null,
    outbound_caller_id = null,
    speechOptions = DEFAULT_CALL_SPEECH,
  ) {
    const payload = startPayload || pendingStart;
    const callerId =
      typeof outbound_caller_id === "object" && outbound_caller_id?.number
        ? outbound_caller_id.number
        : outbound_caller_id || pendingCallerId;
    if (!payload || !callerId) return;
    setCallerIdModalOpen(false);
    setSpeechModalOpen(false);
    setBusy(true);
    const mobileWindow = enableMobileSimulator ? window.open("", "ivr-recipient-mobile", MOBILE_WINDOW_FEATURES) : null;
    if (mobileWindow) {
      mobileWindow.document.title = "Recipient call";
      mobileWindow.document.body.innerHTML =
        '<div style="font-family: system-ui, sans-serif; padding: 24px;">Starting recipient call...</div>';
    }
    try {
      const row = await startCall({
        ...payload,
        outbound_trunk,
        outbound_caller_id: callerId,
        speech_engine: speechOptions.speech_engine,
        luvvoice_voice_id: speechOptions.luvvoice_voice_id,
        speech_volume_percent: speechOptions.speech_volume_percent,
      });
      setRecentOrganizations((items) => storeRecentOrganization(payload.university, items));
      await onCreated(row, mobileWindow);
      setName("");
      setUniversity("");
      setSelectedIso(defaultCountry.iso);
      setNationalNumber("");
      setPendingStart(null);
      setPendingTrunk(null);
      setPendingCallerId(null);
    } catch (err) {
      mobileWindow?.close();
      setError(err.message || "Could not start call");
    } finally {
      setBusy(false);
    }
  }

  async function handleEndActiveCall() {
    if (!activeCallId || endingActiveCall) return;
    setError(null);
    setEndingActiveCall(true);
    try {
      await endActiveCall(activeCallId);
      const row = await fetchOutboundSpacing();
      setOutboundSpacing(row);
      await onActiveCallEnded?.(activeCallId);
    } catch (err) {
      setError(err.message || "Could not end active call");
    } finally {
      setEndingActiveCall(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (spacingBlocked) {
      setError(
        outboundSpacing?.message ||
          `Wait ${spacingWait}s before starting another SIP UP call.`,
      );
      return;
    }
    const cleanNationalNumber = normalizeNationalDigitsForDialCode(
      selectedCountry.dialCode,
      nationalNumber,
    );
    if (!selectedCountry?.dialCode) {
      setError("Select a country");
      return;
    }
    if (!cleanNationalNumber) {
      setError("Enter the national phone number");
      return;
    }
    const destination = `${selectedCountry.dialCode}${cleanNationalNumber}`;
    const destDigits = destination.replace(/\D/g, "");
    if (destDigits.length > 15) {
      setError(
        "Phone number is too long. Enter only the recipient mobile (max 15 digits with country code). Do not paste caller ID here.",
      );
      return;
    }
    if (
      (selectedCountry.dialCode === "+1" || selectedCountry.dialCode === "1") &&
      cleanNationalNumber.length !== 10
    ) {
      setError("US/Canada numbers must be exactly 10 digits (area code + number), without a leading 1.");
      return;
    }
    const mismatch = destinationCountryMismatch(selectedIso, destination);
    if (mismatch) {
      setError(mismatch);
      return;
    }
    if (startConfirmMessage && !window.confirm(startConfirmMessage)) {
      return;
    }
    const startPayload = {
      name: name.trim(),
      university: university.trim(),
      phone_number: `${selectedCountry.dialCode}${cleanNationalNumber}`,
    };
    setPendingStart(startPayload);
    setPendingTrunk("sip_up");
    setCallerIdModalOpen(true);
  }

  function destinationConflictsWithCallerId(destinationE164, callerIdDigits) {
    const dest = String(destinationE164 || "").replace(/\D/g, "");
    const cid = String(callerIdDigits || "").replace(/\D/g, "");
    if (!dest || !cid || dest.length < 8 || cid.length < 8) return false;
    return dest === cid || dest.endsWith(cid) || cid.endsWith(dest);
  }

  function openSpeechPicker(preset) {
    const destination = pendingStart?.phone_number || "";
    if (destinationConflictsWithCallerId(destination, preset.number)) {
      setError(
        "Recipient number must not be the same as the caller ID. Enter the callee mobile, not the CLI.",
      );
      return;
    }
    setPendingCallerId(preset.number);
    setCallerIdModalOpen(false);
    setSpeechModalOpen(true);
  }

  const configuredCallerId = runtime?.sip_up?.caller_id || "";
  const configuredAccountLabel = runtime?.sip_up?.account_label || "SIP UP account (configured)";
  const trunkPresets = presetsWithConfiguredCallerId(
    callerIdPresets,
    configuredCallerId,
    configuredAccountLabel,
  );
  const providerLabel = "SIP UP";
  const pendingCallerPreset = trunkPresets.find((p) => p.number === pendingCallerId);

  return (
    <section className={`relative ${cardClass} ${simple ? "p-4" : "p-5"}`}>
      {simple ? (
        <div>
          <p className="app-eyebrow">Outbound IVR</p>
          <h3 className="mt-1 text-base font-semibold tracking-tight text-slate-900">Start verification call</h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            The recipient will receive an automated call with consent and OTP prompts.
          </p>
        </div>
      ) : (
        <SectionHeader
          eyebrow="Outbound IVR"
          title="Start outbound verification"
          description="The recipient will receive an automated verification call."
        />
      )}

      <form
        onSubmit={handleSubmit}
        className={`space-y-4 ${simple ? "mt-3" : "mt-4"}`}
        autoComplete="off"
        data-lpignore="true"
        data-1p-ignore="true"
      >
        {/* Decoy fields so Chrome fills these instead of real inputs */}
        <div className="pointer-events-none absolute h-0 w-0 overflow-hidden opacity-0" aria-hidden="true">
          <input type="text" name="fake-email" autoComplete="email" tabIndex={-1} defaultValue="" />
          <input type="password" name="fake-password" autoComplete="new-password" tabIndex={-1} defaultValue="" />
        </div>
        <div>
          <label className={labelClass}>
            Name
          </label>
          <input
            className={inputClass}
            name="ivr-recipient-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={255}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            placeholder="Recipient name"
            autoFocus={simple}
          />
        </div>
        <div>
          <label className={labelClass}>
            Service name
          </label>
          <input
            className={inputClass}
            name="ivr-recipient-organization"
            value={university}
            onChange={(e) => {
              setUniversity(e.target.value);
              setShowOrganizationSuggestions(true);
            }}
            onFocus={() => setShowOrganizationSuggestions(true)}
            onBlur={() => window.setTimeout(() => setShowOrganizationSuggestions(false), 120)}
            required
            maxLength={255}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder="Service name"
          />
          {showOrganizationSuggestions && recentOrganizations.length > 0 ? (
            <div className="mt-2 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
              <div className="mb-1 flex items-center justify-between px-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Recent service names
                </p>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    try {
                      removeGlobalCookie(RECENT_ORGANIZATIONS_KEY);
                    } catch {
                      /* ignore local browser storage errors */
                    }
                    setRecentOrganizations([]);
                  }}
                  className="text-[10px] font-semibold text-slate-500 hover:text-slate-900"
                >
                  Clear
                </button>
              </div>
              {recentOrganizations
                .filter((item) => item.toLowerCase().includes(university.trim().toLowerCase()))
                .slice(0, 6)
                .map((item) => (
                  <button
                    key={item}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setUniversity(item);
                      setShowOrganizationSuggestions(false);
                    }}
                    className="block w-full rounded-lg px-2 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
                  >
                    {item}
                  </button>
                ))}
            </div>
          ) : null}
        </div>
        <div>
          <label className={labelClass}>Country + phone</label>
          <div className="mt-2 flex overflow-hidden rounded-2xl border border-slate-300 bg-white shadow-sm transition focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
            <select
              className="min-w-[11rem] max-w-[45%] border-r border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-900 outline-none"
              name="ivr-recipient-country"
              value={selectedIso}
              onChange={(e) => setSelectedIso(e.target.value)}
              required
              autoComplete="off"
              aria-label="Country dial code"
            >
              {COUNTRY_DIAL_CODES.map((country) => (
                <option key={`${country.iso}-${country.name}`} value={country.iso}>
                  {country.flag} {country.name} {country.dialCode}
                </option>
              ))}
            </select>
            <input
              className="min-w-0 flex-1 bg-transparent px-4 py-3 font-mono text-base tracking-normal text-slate-900 placeholder:text-slate-400 outline-none"
              name="ivr-recipient-phone"
              value={formatNationalNumber(nationalNumber, selectedCountry.iso)}
              onChange={(e) => handleNationalNumberChange(e.target.value)}
              onPaste={(e) => {
                const pasted = e.clipboardData?.getData("text") || "";
                if (!parseInternationalPhoneInput(pasted, COUNTRY_DIAL_CODES)) return;
                e.preventDefault();
                handleNationalNumberChange(pasted);
              }}
              required
              maxLength={32}
              placeholder={NATIONAL_PLACEHOLDER_BY_ISO[selectedCountry.iso] || "National number"}
              inputMode="tel"
              autoComplete="off"
            />
          </div>
          {destinationPreview ? (
            <p
              className={`mt-1.5 text-[11px] font-medium ${
                countryMismatch ? "text-rose-700" : "text-slate-700"
              }`}
            >
              Will dial:{" "}
              <span className="font-mono">{destinationPreview}</span>
            </p>
          ) : (
            <p className="mt-1.5 text-[11px] text-slate-500">
              Enter the recipient mobile (not the caller ID).
            </p>
          )}
          {countryMismatch ? (
            <p className="mt-1 text-[11px] text-rose-700">{countryMismatch}</p>
          ) : null}
        </div>

        {spacingBlocked ? (
          <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
            <p>
              {outboundSpacing?.message ||
                (outboundSpacing?.reason === "active_call"
                  ? "A call is still active — wait until it ends before starting another."
                  : `SIP UP cooldown — wait ${spacingWait}s before the next call (prevents intermittent 403 failures).`)}
            </p>
            {activeCallId ? (
              <div className="flex flex-wrap gap-2">
                {onResumeActiveCall ? (
                  <SecondaryButton
                    type="button"
                    className="px-2.5 py-1 text-[11px]"
                    disabled={endingActiveCall}
                    onClick={() => onResumeActiveCall(activeCallId)}
                  >
                    Resume active call
                  </SecondaryButton>
                ) : null}
                <SecondaryButton
                  type="button"
                  className="px-2.5 py-1 text-[11px]"
                  disabled={endingActiveCall}
                  onClick={handleEndActiveCall}
                >
                  {endingActiveCall ? "Ending…" : "End active call"}
                </SecondaryButton>
              </div>
            ) : null}
          </div>
        ) : null}

        {error ? (
          <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </p>
        ) : null}

        <PrimaryButton
          type="submit"
          disabled={
            busy ||
            spacingBlocked ||
            callerIdModalOpen ||
            speechModalOpen ||
            callerIdManageOpen ||
            sipUpAccountEditOpen
          }
          className="w-full"
        >
          {busy
            ? "Starting..."
            : spacingBlocked && spacingWait > 0
              ? `Wait ${spacingWait}s…`
              : spacingBlocked
                ? "Call in progress…"
                : "Start verification call"}
        </PrimaryButton>

        {configuredCallerId ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2.5 text-xs text-emerald-950">
            <div className="flex items-start justify-between gap-2">
              <p className="font-semibold uppercase tracking-[0.12em] text-emerald-800">SIP UP outbound caller ID</p>
              <SecondaryButton
                type="button"
                className="shrink-0 px-2 py-0.5 text-[10px]"
                disabled={busy}
                onClick={() => setSipUpAccountEditOpen(true)}
              >
                Edit account
              </SecondaryButton>
            </div>
            <p className="mt-1 font-mono text-sm font-semibold text-emerald-950">{configuredCallerId}</p>
            <p className="mt-1 text-emerald-900/80">
              {configuredAccountLabel} — update here when you change Caller ID in the SIP UP portal.
            </p>
          </div>
        ) : (
          <SecondaryButton
            type="button"
            className="w-full py-2 text-sm"
            disabled={busy}
            onClick={() => setSipUpAccountEditOpen(true)}
          >
            Configure SIP UP account
          </SecondaryButton>
        )}

        <SecondaryButton
          type="button"
          className="w-full py-2 text-sm"
          disabled={busy}
          onClick={() => setCallerIdManageOpen(true)}
        >
          Set new Caller ID
        </SecondaryButton>
      </form>

      <CallerIdManageModal
        open={callerIdManageOpen}
        onClose={() => setCallerIdManageOpen(false)}
        onChange={setCallerIdPresets}
      />

      <CallerIdSelectModal
        open={callerIdModalOpen}
        providerLabel={providerLabel}
        destinationE164={pendingStart?.phone_number || ""}
        configuredCallerId={configuredCallerId}
        presets={trunkPresets}
        onClose={() => {
          setCallerIdModalOpen(false);
          setPendingTrunk(null);
        }}
        onSelect={(preset) => openSpeechPicker(preset)}
        onEditConfiguredAccount={() => {
          setCallerIdModalOpen(false);
          setSipUpAccountEditOpen(true);
        }}
      />

      <SipUpAccountEditModal
        open={sipUpAccountEditOpen}
        onClose={() => setSipUpAccountEditOpen(false)}
        onSaved={async () => {
          await onRuntimeRefresh?.();
        }}
      />

      <SpeechEngineSelectModal
        open={speechModalOpen}
        providerLabel={providerLabel}
        destinationE164={pendingStart?.phone_number || ""}
        callerIdLabel={pendingCallerPreset?.label || pendingCallerId}
        callerIdDigits={pendingCallerId || ""}
        authorizedCallerId={runtime?.sip_up?.caller_id || ""}
        onClose={() => {
          setSpeechModalOpen(false);
          setPendingCallerId(null);
        }}
        onConfirm={(speechOptions) => {
          setSpeechModalOpen(false);
          runStartWithTrunk(pendingTrunk || "sip_up", pendingStart, pendingCallerId, speechOptions);
        }}
      />
    </section>
  );
}
