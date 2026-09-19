import animate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
//
// Tailwind exists in this app for one reason: the ElevenLabs UI components
// adopted under src/components/elevenlabs/ ship as shadcn-style sources that
// style themselves with utility classes. It is NOT a general styling tool
// here — page CSS still belongs in each page's own stylesheet reading
// src/theme/tokens.css.
//
// Rules that keep it from fighting the existing design system:
//  - preflight is OFF (see corePlugins): no global resets. The utilities
//    that need --tw-* variable defaults get them scoped under .app-root in
//    src/theme/tailwind.css instead.
//  - darkMode is "class" so `dark:` utilities in copied sources can never
//    fire: this product has no dark mode, ever (see DESIGN.md).
//  - Every semantic colour/radius/font below maps straight to a token from
//    src/theme/tokens.css. No hex values live in this file.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        border: "var(--color-border)",
        input: "var(--color-border-strong)",
        ring: "var(--color-primary)",
        background: "var(--color-bg-raised)",
        foreground: "var(--color-ink)",
        primary: {
          DEFAULT: "var(--color-primary)",
          deep: "var(--color-primary-deep)",
          foreground: "var(--color-on-primary)",
        },
        warn: {
          DEFAULT: "var(--color-warn)",
          soft: "var(--color-warn-soft)",
        },
        secondary: {
          DEFAULT: "var(--color-bg)",
          foreground: "var(--color-ink)",
        },
        muted: {
          DEFAULT: "var(--color-bg)",
          foreground: "var(--color-mute)",
        },
        accent: {
          DEFAULT: "var(--color-primary-soft)",
          foreground: "var(--color-primary-deep)",
        },
        destructive: {
          DEFAULT: "var(--color-urgent)",
          foreground: "var(--color-on-primary)",
        },
        card: {
          DEFAULT: "var(--color-panel)",
          foreground: "var(--color-ink)",
        },
        popover: {
          DEFAULT: "var(--color-panel)",
          foreground: "var(--color-ink)",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        full: "var(--radius-full)",
      },
      fontFamily: {
        sans: "var(--font-body)",
        display: "var(--font-display)",
        mono: "var(--font-mono)",
      },
      boxShadow: {
        xs: "var(--shadow-sm)",
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
    },
  },
  // tailwindcss-animate provides the animate-in/out + fade/zoom/slide
  // utilities the copied dropdown-menu source uses for its open/close motion.
  plugins: [animate],
};
