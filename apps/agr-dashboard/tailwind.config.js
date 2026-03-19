/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,ts}'],
  theme: {
    extend: {
      colors: {
        sidebar: '#0f172a',
        surface: '#1e293b',
        accent: '#6366f1',
      },
    },
  },
  plugins: [],
};
