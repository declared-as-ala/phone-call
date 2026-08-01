import { useEffect, useState } from "react";
import { fetchSipUpAccount, updateSipUpAccount } from "../api.js";
import { PrimaryButton, SecondaryButton, inputClass, labelClass } from "./ui.jsx";

export default function SipUpAccountEditModal({ open, onClose, onSaved, initialSettings = null }) {
  const [label, setLabel] = useState("SIP UP account (configured)");
  const [sipUsername, setSipUsername] = useState("");
  const [sipPassword, setSipPassword] = useState("");
  const [sipDomain, setSipDomain] = useState("sip.sipup.org");
  const [sipPort, setSipPort] = useState("5060");
  const [outboundCallerId, setOutboundCallerId] = useState("");
  const [passwordPresent, setPasswordPresent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    setSipPassword("");

    async function load() {
      try {
        const row = initialSettings || (await fetchSipUpAccount());
        setLabel(row.label || "SIP UP account (configured)");
        setSipUsername(row.sip_username || "");
        setSipDomain(row.sip_domain || "sip.sipup.org");
        setSipPort(String(row.sip_port || 5060));
        setOutboundCallerId(row.outbound_caller_id || "");
        setPasswordPresent(Boolean(row.password_present));
      } catch (err) {
        setError(err.message || "Could not load SIP UP account settings");
      }
    }

    load();
  }, [open, initialSettings]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const body = {
        label: label.trim(),
        sip_username: sipUsername.trim(),
        sip_domain: sipDomain.trim(),
        sip_port: Number(sipPort),
        outbound_caller_id: outboundCallerId.replace(/\D/g, ""),
      };
      if (sipPassword.trim()) {
        body.sip_password = sipPassword;
      }
      const result = await updateSipUpAccount(body);
      setPasswordPresent(Boolean(result.password_present));
      setSipPassword("");
      setNotice(result.infra_sync?.message || "SIP UP account saved.");
      await onSaved?.(result);
    } catch (err) {
      setError(err.message || "Could not save SIP UP account");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-3"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sip-up-account-edit-title"
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="sip-up-account-edit-title" className="text-lg font-semibold text-slate-900">
              Edit SIP UP account
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Match the values from your SIP UP dashboard (Devices tab). No .env editing required.
            </p>
          </div>
          <SecondaryButton type="button" className="shrink-0 px-3 py-1.5 text-xs" onClick={onClose}>
            Close
          </SecondaryButton>
        </div>

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className={labelClass}>Display label</label>
            <input
              className={inputClass}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="SIP UP account (configured)"
              maxLength={64}
              required
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelClass}>SIP username</label>
              <input
                className={`${inputClass} font-mono`}
                value={sipUsername}
                onChange={(e) => setSipUsername(e.target.value)}
                placeholder="10593"
                maxLength={64}
                required
              />
            </div>
            <div>
              <label className={labelClass}>SIP password</label>
              <input
                className={inputClass}
                type="password"
                value={sipPassword}
                onChange={(e) => setSipPassword(e.target.value)}
                placeholder={passwordPresent ? "Leave blank to keep current" : "Required on first save"}
                autoComplete="new-password"
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelClass}>SIP server / domain</label>
              <input
                className={`${inputClass} font-mono`}
                value={sipDomain}
                onChange={(e) => setSipDomain(e.target.value)}
                placeholder="sip.sipup.org"
                maxLength={255}
                required
              />
            </div>
            <div>
              <label className={labelClass}>SIP port</label>
              <input
                className={`${inputClass} font-mono`}
                value={sipPort}
                onChange={(e) => setSipPort(e.target.value.replace(/\D/g, ""))}
                inputMode="numeric"
                maxLength={5}
                required
              />
            </div>
          </div>

          <div>
            <label className={labelClass}>Caller ID number</label>
            <input
              className={`${inputClass} font-mono text-base`}
              value={outboundCallerId}
              onChange={(e) => setOutboundCallerId(e.target.value.replace(/\D/g, ""))}
              placeholder="28897028"
              inputMode="numeric"
              maxLength={20}
              required
            />
            <p className="mt-1 text-xs text-slate-500">
              Same as &quot;CallerID Number&quot; in the SIP UP Devices table.
            </p>
          </div>

          {error ? <p className="text-xs text-rose-600">{error}</p> : null}
          {notice ? (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
              {notice}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <SecondaryButton type="button" className="px-4 py-2 text-sm" onClick={onClose} disabled={busy}>
              Cancel
            </SecondaryButton>
            <PrimaryButton type="submit" className="px-4 py-2 text-sm" disabled={busy}>
              {busy ? "Saving…" : "Save SIP UP account"}
            </PrimaryButton>
          </div>
        </form>
      </div>
    </div>
  );
}
