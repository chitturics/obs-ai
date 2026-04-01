import forms from '@tailwindcss/forms';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: '#0b0d12',
          2: '#13151c',
          3: '#1c1f2a',
          4: '#252836',
        },
        border: {
          DEFAULT: '#2a2d3d',
          hover: '#3a3e52',
        },
        text: {
          DEFAULT: '#e4e4ec',
          2: '#8b90a5',
          3: '#8891a8',
        },
        accent: {
          DEFAULT: '#6c8cff',
          hover: '#5470d6',
          glow: 'rgba(108, 140, 255, 0.12)',
        },
        success: '#34d399',
        danger: '#ef4444',
        warning: '#fbbf24',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '10px',
        sm: '6px',
      },
      width: {
        sidebar: '240px',
      },
    },
  },
  plugins: [forms({ strategy: 'class' })],
};
