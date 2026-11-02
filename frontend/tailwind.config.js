/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f5f5ee",
        ink: "#252820",
        accent: "#ed481d",
        rule: "#cfd1c7",
      },
      fontFamily: {
        sans: ["Arial", "Helvetica Neue", "sans-serif"],
        mono: ["Consolas", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
