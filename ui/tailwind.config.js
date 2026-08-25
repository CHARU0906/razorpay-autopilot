/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        base:    '#0A0E14',
        panel:   '#141B26',
        border:  '#1E2A3A',
        'signal-blue': '#5B8DEF',
        amber:   '#F5A623',
        red:     '#E5484D',
        text:    '#E8ECF1',
        muted:   '#6B7A90',
        green:   '#3DD68C',
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', '"JetBrains Mono"', 'monospace'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
