import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        ink: v("ink"),
        panel: v("panel"),
        raised: v("raised"),
        line: v("line"),
        fg: v("fg"),
        muted: v("muted"),
        ok: v("ok"),
        user: v("user"),
        late: v("late"),
        infra: v("infra"),
        live: v("live"),
      },
      fontFamily: {
        sans: ['"Instrument Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        // modular scale ~1.2, 16px base
        xs: ["0.75rem", "1.1rem"],
        sm: ["0.833rem", "1.25rem"],
        base: ["1rem", "1.55rem"],
        lg: ["1.2rem", "1.7rem"],
        xl: ["1.44rem", "1.9rem"],
        "2xl": ["1.728rem", "2.1rem"],
        "3xl": ["2.488rem", "2.7rem"],
      },
      keyframes: {
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".35" } },
      },
      animation: { beat: "pulse 1.4s ease-in-out infinite" },
    },
  },
  plugins: [],
} satisfies Config;
