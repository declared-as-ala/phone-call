/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Inter", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.05), 0 12px 32px -16px rgb(15 23 42 / 0.18)",
        "card-hover": "0 8px 24px -8px rgb(15 23 42 / 0.22), 0 0 0 1px rgb(45 212 191 / 0.15)",
        glow: "0 0 0 1px rgb(45 212 191 / 0.25), 0 12px 40px -16px rgb(13 148 136 / 0.35)",
      },
      animation: {
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
    },
  },
  plugins: [],
};
