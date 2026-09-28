import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        accent: { DEFAULT: "#2563EB", hover: "#1D4ED8", subtle: "#EFF6FF" },
      },
      fontSize: {
        "2xs": ["11px", "16px"],
        xs: ["12px", "16px"],
        sm: ["13px", "20px"],
        base: ["14px", "22px"],
      },
      borderRadius: { DEFAULT: "6px", md: "6px", lg: "8px" },
    },
  },
  plugins: [],
};
export default config;
