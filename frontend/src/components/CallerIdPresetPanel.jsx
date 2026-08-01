import { useEffect, useState } from "react";
import {
  addCallerIdPreset,
  loadCallerIdPresets,
  removeCallerIdPreset,
} from "../utils/callerIdPresets.js";
import { DangerButton, SecondaryButton, inputClass, labelClass } from "./ui.jsx";

export default function CallerIdPresetPanel({ onChange, embedded = false, open = true }) {
  const [presets, setPresets] = useState(loadCallerIdPresets);
  const [label, setLabel] = useState("");
  const [number, setNumber] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) setPresets(loadCallerIdPresets());
  }, [open]);

  function refresh(next) {
    setPresets(next);
    onChange?.(next);
  }

  function handleDelete(preset) {
    const ok = window.confirm(
      `Delete caller ID "${preset.label}" (${preset.number})? This cannot be undone.`,
    );
    if (!ok) return;
    refresh(removeCallerIdPreset(preset.id));
  }

  function handleAdd(e) {
    e.preventDefault();
    setError(null);
    try {
      refresh(addCallerIdPreset({ label, number }));
      setLabel("");
      setNumber("");
    } catch (err) {
      setError(err.message || "Could not save caller ID");
    }
  }

  return (
    <div className={embedded ? "" : "rounded-xl border border-slate-200 bg-slate-50/80 p-4"}>
      {!embedded ? (
        <>
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-slate-900">Caller IDs</h4>
            <span className="text-[10px] uppercase tracking-wide text-slate-500">Set new Caller ID</span>
          </div>
          <p className="mt-1 text-xs text-slate-600">
            Saved IDs appear when you start a SIP UP call.
          </p>
        </>
      ) : null}

      {presets.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          No caller IDs saved yet. Add one below.
        </p>
      ) : (
        <ul className={`space-y-2 ${embedded ? "mt-0" : "mt-3"}`}>
          {presets.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-slate-900">{p.label}</div>
                <div className="font-mono text-xs text-slate-600">{p.number}</div>
                <div className="mt-0.5 text-[10px] text-slate-500">SIP UP</div>
              </div>
              <DangerButton
                type="button"
                onClick={() => handleDelete(p)}
                className="shrink-0 px-2 py-1 text-[10px]"
              >
                Delete
              </DangerButton>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={handleAdd}
        className={`space-y-3 ${embedded ? "mt-4 border-t border-slate-200 pt-4" : "mt-4 border-t border-slate-200 pt-4"}`}
      >
        <div>
          <label className={labelClass}>Label</label>
          <input
            className={inputClass}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Italy test"
            maxLength={64}
            required
          />
        </div>
        <div>
          <label className={labelClass}>Caller ID number</label>
          <input
            className={`${inputClass} font-mono`}
            value={number}
            onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))}
            placeholder="393888736444"
            inputMode="numeric"
            maxLength={20}
            required
          />
        </div>
        {error ? <p className="text-xs text-rose-600">{error}</p> : null}
        <SecondaryButton type="submit" className="w-full py-2 text-sm">
          Save caller ID
        </SecondaryButton>
      </form>
    </div>
  );
}
