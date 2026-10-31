/** Tailwind config: brand colours and the risk-level palette from BUILD_SPEC §4. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { 50: "#F1F8E9", 100: "#DCEDC8", 600: "#2E7D32", 700: "#1B5E20", 900: "#0D3B12" },
        low: { DEFAULT: "#2E7D32", text: "#1B5E20", bg: "#E8F5E9" },
        moderate: { DEFAULT: "#F9A825", text: "#6D4C00", bg: "#FFF8E1" },
        high: { DEFAULT: "#C62828", text: "#B71C1C", bg: "#FFEBEE" },
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans", "Noto Sans Devanagari", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
