/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#ffffff',    // White
        surface: '#f4f4f5',       // Zinc 100
        surfaceHighlight: '#e4e4e7', // Zinc 200
        primary: '#18181b',       // Zinc 900 - black accent
        secondary: '#52525b',     // Zinc 600
        success: '#22c55e',       // Green 500
        warning: '#eab308',       // Yellow 500
        error: '#ef4444',         // Red 500
        text: '#09090b',          // Zinc 950 - black text
        textMuted: '#71717a',     // Zinc 500
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 3s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-5px)' },
        }
      }
    },
  },
  plugins: [],
}
