import type { Config } from "tailwindcss";

// Every colour resolves to a CSS variable in src/app/globals.css, the single source of truth.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        serif: ["var(--font-serif)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        paper: token("paper"),
        panel: token("panel"),
        rule: token("rule"),
        // Warm neutral ramp: 200 is the hairline rule, 500 the secondary text, 900 the ink.
        ink: {
          50: token("ink-50"),
          100: token("ink-100"),
          200: token("rule"),
          300: token("ink-300"),
          400: token("ink-400"),
          500: token("ink-500"),
          600: token("ink-600"),
          700: token("ink-700"),
          800: token("ink-800"),
          900: token("ink"),
          DEFAULT: token("ink"),
        },
        accent: { DEFAULT: token("accent"), hover: token("accent-hover"), subtle: token("accent-subtle") },
        alert: { DEFAULT: token("alert"), subtle: token("alert-subtle") },
        pending: { DEFAULT: token("pending"), ink: token("pending-ink"), subtle: token("pending-subtle") },
      },
      fontSize: {
        "2xs": ["11px", "16px"],
        xs: ["12px", "17px"],
        sm: ["13px", "20px"],
        base: ["14px", "22px"],
      },
      borderRadius: { none: "0", sm: "1px", DEFAULT: "2px", md: "2px", lg: "2px" },
    },
  },
  plugins: [],
};
export default config;
