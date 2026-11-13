/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070b14",
          900: "#0b1120",
          850: "#101a2e",
          800: "#152238",
          700: "#1e3150",
        },
        accent: {
          400: "#6ea8ff",
          500: "#4d8bff",
          600: "#2f6fe6",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Noto Sans SC", "sans-serif"],
      },
    },
  },
  plugins: [],
};
