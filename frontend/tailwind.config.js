/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#05060a", 900: "#0a0c12", 850: "#0e1118", 800: "#131722", 700: "#1b2030", 600: "#262c3f" },
        astra: { blue: "#3b82f6", cyan: "#22d3ee", violet: "#8b5cf6", pink: "#d946ef" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["'Space Grotesk'", "Inter", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: { glow: "0 0 40px -8px rgba(99,102,241,.55)", "glow-sm": "0 0 20px -6px rgba(59,130,246,.5)" },
      keyframes: { shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } } },
      animation: { shimmer: "shimmer 2.5s linear infinite" },
    },
  },
  plugins: [],
};
