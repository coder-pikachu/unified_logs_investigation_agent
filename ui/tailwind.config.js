/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        panel: "rgb(var(--c-panel) / <alpha-value>)",
        panel2: "rgb(var(--c-panel2) / <alpha-value>)",
        edge: "rgb(var(--c-edge) / <alpha-value>)",
        edge2: "rgb(var(--c-edge2) / <alpha-value>)",
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        fg: "rgb(var(--c-fg) / <alpha-value>)",
        fgdim: "rgb(var(--c-fgdim) / <alpha-value>)",
        accent: "rgb(var(--c-accent) / <alpha-value>)",
        accent2: "rgb(var(--c-accent2) / <alpha-value>)",
        sev: {
          ok: "rgb(var(--c-sev-ok) / <alpha-value>)",
          warn: "rgb(var(--c-sev-warn) / <alpha-value>)",
          crit: "rgb(var(--c-sev-crit) / <alpha-value>)",
          info: "rgb(var(--c-sev-info) / <alpha-value>)",
          biz: "rgb(var(--c-sev-biz) / <alpha-value>)",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "SFMono-Regular",
          "SF Mono",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      keyframes: {
        flow: {
          to: { strokeDashoffset: "-24" },
        },
        looppulse: {
          "0%": { stroke: "#f4b740", strokeWidth: "1.5", opacity: "0.55" },
          "50%": { stroke: "#f2686a", strokeWidth: "3", opacity: "1" },
          "100%": { stroke: "#f4b740", strokeWidth: "1.5", opacity: "0.55" },
        },
        blip: {
          "0%": { opacity: "0", transform: "translateX(-2px)" },
          "20%": { opacity: "1" },
          "100%": { opacity: "0.35", transform: "translateX(0)" },
        },
        pulsedot: {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        drawer: {
          from: { transform: "translateX(16px)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
      },
      animation: {
        flow: "flow 1s linear infinite",
        looppulse: "looppulse 0.9s ease-in-out 6",
        blip: "blip 0.6s ease-out",
        pulsedot: "pulsedot 1.1s ease-in-out infinite",
        drawer: "drawer 0.18s ease-out",
      },
    },
  },
  plugins: [],
};
