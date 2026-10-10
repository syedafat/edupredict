module.exports = {
  content: ['./templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#F8FAFC', dark: '#0F172A' },
      },
    },
  },
  safelist: [
    { pattern: /^(bg|text|border)-(indigo|sky|emerald|rose|amber|violet|teal|fuchsia)-(50|100|200|300|400|500|600|700|800|900)$/ },
    { pattern: /^(bg|text)-(indigo|sky|emerald|rose|amber|violet|teal|fuchsia)-(950\/40|300)$/, variants: ['dark'] },
  ],
};
