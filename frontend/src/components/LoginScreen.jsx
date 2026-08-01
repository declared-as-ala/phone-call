import { useState } from "react";
import { getResolvedApiRoot, loginAdmin } from "../api.js";
import AuthGallery from "./AuthGallery.jsx";
import { cardClass, inputClass, labelClass, PrimaryButton } from "./ui.jsx";

// No public self-registration: the first admin is created via
// `backend/scripts/create_admin.py` (see README), and additional admins are
// created from the authenticated Administration screen, not this public page.

export default function LoginScreen({ onAuthenticated }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const normalizedEmail = email.trim().toLowerCase();

    setBusy(true);
    try {
      const data = await loginAdmin({
        email: normalizedEmail,
        password,
      });
      onAuthenticated(data.admin);
    } catch (err) {
      const msg = String(err?.message || err || "").trim();
      if (/failed to fetch|networkerror|load failed/i.test(msg)) {
        setError(
          `Cannot reach the API at ${getResolvedApiRoot()}. Start the backend with ./scripts/run_backend.sh, open the URL shown by Vite (e.g. http://localhost:5173), then hard-refresh (Ctrl+Shift+R).`
        );
      } else if (msg) {
        setError(msg);
      } else {
        setError(`Login failed (${getResolvedApiRoot()}). Check email and password.`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid h-dvh max-h-dvh overflow-hidden lg:grid-cols-[1.05fr_0.95fr]">
      <section className="login-panel relative hidden min-h-0 overflow-y-auto px-10 py-8 text-white lg:flex lg:flex-col lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-2 backdrop-blur">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-teal-300 to-indigo-400 text-xs font-bold text-slate-950">
              IV
            </div>
            <span className="text-sm font-semibold tracking-tight">Verification Operations</span>
          </div>
          <h1 className="mt-10 max-w-lg text-4xl font-semibold leading-tight tracking-tight">
            Phone-based identity verification for institutions
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-teal-50/80">
            Run outbound IVR calls, collect consent and OTP entry via keypad, and review submissions
            with manual admin approval — built for universities, exam boards, and regulated workflows.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { step: "01", title: "Start call", text: "Dial the recipient with your authorized caller ID." },
            { step: "02", title: "IVR + OTP", text: "Callee enters the exact digit count you configured — submission is automatic." },
            { step: "03", title: "Admin review", text: "You approve or reject the entered code manually." },
          ].map((item) => (
            <div
              key={item.step}
              className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm"
            >
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-teal-200/80">{item.step}</p>
              <p className="mt-2 text-sm font-semibold">{item.title}</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-300">{item.text}</p>
            </div>
          ))}
        </div>

        <AuthGallery />
      </section>

      <section className="flex min-h-0 items-center justify-center overflow-y-auto px-4 py-4 sm:py-6">
        <div className={`my-auto w-full max-w-md p-5 sm:p-6 ${cardClass} animate-slide-up shadow-card`}>
          <div className="mb-6 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 to-indigo-500 text-sm font-bold text-white">
              IV
            </div>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">Welcome back</h2>
          <p className="mt-1 text-sm text-slate-500">Sign in to launch and monitor verification calls.</p>

          <form onSubmit={handleSubmit} className="mt-5 space-y-3">
            <div>
              <label className={labelClass}>Email</label>
              <input
                className={inputClass}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div>
              <label className={labelClass}>Password</label>
              <input
                className={inputClass}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {error ? (
              <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>
            ) : null}

            <PrimaryButton type="submit" disabled={busy} className="w-full py-3">
              {busy ? "Signing in..." : "Sign in"}
            </PrimaryButton>
          </form>

          <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
            New admin accounts are created from the Administration screen by an existing admin, or via{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5">scripts/create_admin.py</code> for the first account.
          </p>

          <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
            Session persists in this browser via a secure cookie (Path=/).
          </p>
        </div>
      </section>
    </div>
  );
}
