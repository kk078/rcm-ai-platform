/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#eef1f8', 100: '#d5dce8', 200: '#aab9d1', 300: '#7e95ba',
          400: '#5272a4', 500: '#2a508e', 600: '#1a3872', 700: '#102554',
          800: '#0a1a3c', 900: '#060f24', 950: '#03091a',
        },
        gold: {
          100: '#fdf6e3', 200: '#f9e8b4', 300: '#f0cf7a', 400: '#e8b84b',
          500: '#c9a84c', 600: '#aa8a38', 700: '#8b6e28',
        },
        brand: {
          50: '#eef1f8', 100: '#d5dce8', 200: '#aab9d1', 300: '#7e95ba',
          400: '#5272a4', 500: '#2a508e', 600: '#1a3872', 700: '#102554',
          800: '#0a1a3c', 900: '#060f24',
        },
      },
      boxShadow: {
        'card':     '0 1px 3px 0 rgba(10,26,60,0.08), 0 1px 2px -1px rgba(10,26,60,0.06)',
        'card-md':  '0 4px 12px -2px rgba(10,26,60,0.10), 0 2px 6px -2px rgba(10,26,60,0.07)',
        'card-lg':  '0 10px 30px -5px rgba(10,26,60,0.14), 0 4px 12px -4px rgba(10,26,60,0.10)',
        'glow-gold':'0 0 24px rgba(201,168,76,0.30)',
      },
      animation: {
        'float':   'float 6s ease-in-out infinite',
        'fade-up': 'fadeUp 0.5s ease-out forwards',
      },
      keyframes: {
        float:   { '0%, 100%': { transform: 'translateY(0px)' }, '50%': { transform: 'translateY(-8px)' } },
        fadeUp:  { '0%': { opacity: '0', transform: 'translateY(16px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
};
