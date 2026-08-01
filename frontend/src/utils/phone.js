/** Phone numbers are shown as entered in the local demo UI. */
export function maskPhoneDisplay(value) {
  if (value == null || String(value).trim() === "") return "-";
  return String(value);
}

export function formatStepLabel(step) {
  if (step == null || step === "") return "-";
  return String(step)
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
