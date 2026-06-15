/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        aethera: {
          50:  '#e6edf6',
          100: '#c8d8ed',
          200: '#91b1db',
          300: '#5a8ac9',
          400: '#2b62b6',
          500: '#0050a0',
          600: '#003087',   /* Aethera brand blue — active states */
          700: '#002568',
          800: '#001a4a',
          900: '#000f2c',
          950: '#00071a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        sm:  'var(--shadow-sm)',
        md:  'var(--shadow-md)',
        lg:  'var(--shadow-lg)',
      },
      borderRadius: {
        xl:  '0.75rem',
        '2xl': '1rem',
      },
      keyframes: {
        fadeIn: {
          '0%':   { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        fadeIn: 'fadeIn 0.2s ease-out',
        shimmer: 'shimmer 1.4s ease infinite',
      },
    },
  },
  plugins: [],
};
