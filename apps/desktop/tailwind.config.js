/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/renderer/**/*.{html,tsx,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontSize: {
        base: 'var(--font-size, 14px)',
      },
      fontFamily: {
        sans: ['var(--font-family, system-ui)', 'sans-serif'],
        mono: ['var(--font-family-mono, "JetBrains Mono", monospace)', 'monospace'],
      },
    },
  },
  plugins: [],
}
