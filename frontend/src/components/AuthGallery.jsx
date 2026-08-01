import { useEffect, useState } from "react";

const GALLERY_ITEMS = [
  {
    src: "/auth/outbound-call.svg",
    title: "Outbound verification calls",
    caption: "Reach recipients with your authorized caller ID and guided IVR prompts.",
  },
  {
    src: "/auth/keypad-otp.svg",
    title: "Keypad code entry",
    caption: "Callees enter the exact digit count you configure; submission is automatic.",
  },
  {
    src: "/auth/admin-review.svg",
    title: "Manual admin review",
    caption: "Review submitted codes on the dashboard and approve or deny in real time.",
  },
  {
    src: "/auth/secure-identity.svg",
    title: "Secure identity checks",
    caption: "Built for regulated workflows with encrypted DTMF storage and audit trails.",
  },
];

const ROTATE_MS = 5500;

export default function AuthGallery({ compact = false }) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveIndex((current) => (current + 1) % GALLERY_ITEMS.length);
    }, ROTATE_MS);
    return () => window.clearInterval(timer);
  }, []);

  const active = GALLERY_ITEMS[activeIndex];

  return (
    <div className={compact ? "mt-6" : "mt-8"}>
      <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-white/5 shadow-2xl backdrop-blur-sm">
        <div className="relative aspect-[16/10] w-full">
          {GALLERY_ITEMS.map((item, index) => (
            <img
              key={item.src}
              src={item.src}
              alt={item.title}
              className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-700 ${
                index === activeIndex ? "opacity-100" : "opacity-0"
              }`}
              loading={index === 0 ? "eager" : "lazy"}
            />
          ))}
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-950/80 via-slate-950/10 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 p-5 sm:p-6">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-teal-200/90">
              {String(activeIndex + 1).padStart(2, "0")} / {String(GALLERY_ITEMS.length).padStart(2, "0")}
            </p>
            <p className="mt-1 text-lg font-semibold text-white">{active.title}</p>
            <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-200/90">{active.caption}</p>
          </div>
        </div>
      </div>

      <div className={`flex items-center justify-center gap-2 ${compact ? "mt-3" : "mt-4"}`}>
        {GALLERY_ITEMS.map((item, index) => (
          <button
            key={item.src}
            type="button"
            aria-label={`Show slide ${index + 1}: ${item.title}`}
            aria-current={index === activeIndex ? "true" : undefined}
            onClick={() => setActiveIndex(index)}
            className={`h-2 rounded-full transition-all ${
              index === activeIndex ? "w-8 bg-teal-300" : "w-2 bg-white/30 hover:bg-white/50"
            }`}
          />
        ))}
      </div>

      {!compact ? (
        <div className="mt-4 grid grid-cols-4 gap-2">
          {GALLERY_ITEMS.map((item, index) => (
            <button
              key={`thumb-${item.src}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              className={`overflow-hidden rounded-xl border transition ${
                index === activeIndex
                  ? "border-teal-300/80 ring-2 ring-teal-300/40"
                  : "border-white/10 opacity-70 hover:opacity-100"
              }`}
            >
              <img src={item.src} alt="" className="aspect-[16/10] w-full object-cover" loading="lazy" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
