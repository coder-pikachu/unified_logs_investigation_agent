/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0e14",
        panel: "#0f141d",
        panel2: "#131a25",
        edge: "#1e2732",
        edge2: "#2a3644",
        muted: "#7c889b",
        fg: "#c9d4e3",
        fgdim: "#9aa7ba",
        accent: "#3ad0c0",
        accent2: "#2aa896",
        sev: {
          ok: "#34d399",
          warn: "#f4b740",
          crit: "#f2686a",
          info: "#5aa8f0",
          biz: "#c084fc",
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
