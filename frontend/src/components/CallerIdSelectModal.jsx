import { SecondaryButton } from "./ui.jsx";

export default function CallerIdSelectModal({
  open,
  providerLabel,
  destinationE164 = "",
  configuredCallerId = "",
  presets,
  onClose,
  onSelect,
  onEditConfiguredAccount,
}) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3"
      role="dialog"
      aria-modal="true"
      aria-labelledby="caller-id-modal-title"
    >
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <h2 id="caller-id-modal-title" className="text-lg font-semibold text-slate-900">
          Choose caller ID
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Provider: <span className="font-medium">{providerLabel}</span>. Pick the CLI for this call.
        </p>
        {destinationE164 ? (
          <p className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-950">
            Calling recipient: <span className="font-mono font-semibold">{destinationE164}</span>
          </p>
        ) : null}

        <div className="mt-5 space-y-2">
          {presets.length === 0 ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              No caller IDs saved. Use &quot;Set new Caller ID&quot; below the form first.
            </p>
          ) : (
            presets.map((preset) => {
              const isConfigured =
                preset.configured ||
                (configuredCallerId &&
                  String(preset.number).replace(/\D/g, "") ===
                    String(configuredCallerId).replace(/\D/g, ""));
              return (
                <div
                  key={preset.id}
                  className={`flex w-full items-stretch gap-2 rounded-xl border transition ${
                    isConfigured
                      ? "border-emerald-300 bg-emerald-50/60"
                      : "border-slate-200 bg-white"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(preset)}
                    className={`flex min-w-0 flex-1 flex-col px-4 py-3 text-left hover:bg-blue-50/50 ${
                      isConfigured ? "hover:bg-emerald-50" : ""
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      {preset.label}
                      {isConfigured ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">
                          Account
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 font-mono text-xs text-slate-600">{preset.number}</span>
                  </button>
                  {isConfigured && onEditConfiguredAccount ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditConfiguredAccount();
                      }}
                      className="shrink-0 self-center rounded-lg border border-emerald-300 bg-white px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-emerald-800 hover:bg-emerald-100"
                    >
                      Edit
                    </button>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <SecondaryButton type="button" className="px-4 py-2 text-sm" onClick={onClose}>
            Cancel
          </SecondaryButton>
        </div>
      </div>
    </div>
  );
}
