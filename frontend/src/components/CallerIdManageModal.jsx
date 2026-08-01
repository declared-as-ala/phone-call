import CallerIdPresetPanel from "./CallerIdPresetPanel.jsx";
import { SecondaryButton } from "./ui.jsx";

export default function CallerIdManageModal({ open, onClose, onChange }) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3"
      role="dialog"
      aria-modal="true"
      aria-labelledby="caller-id-manage-title"
    >
      <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="caller-id-manage-title" className="text-lg font-semibold text-slate-900">
              Set new Caller ID
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Save caller IDs per provider. They appear when you start a call.
            </p>
          </div>
          <SecondaryButton type="button" className="shrink-0 px-3 py-1.5 text-xs" onClick={onClose}>
            Close
          </SecondaryButton>
        </div>

        <div className="mt-4">
          <CallerIdPresetPanel embedded open={open} onChange={onChange} />
        </div>
      </div>
    </div>
  );
}
