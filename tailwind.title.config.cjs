// Tailwind for the title page only (src/title-exact): the approved design is
// written in Tailwind and kept verbatim. No preflight, so the rest of the site
// is untouched; utilities are scoped under .mv-tw.
module.exports = {
  content: ['./src/title-exact/**/*.{js,jsx}'],
  important: '.mv-tw',
  corePlugins: {preflight: false},
  theme: {extend: {}},
  plugins: []
};
