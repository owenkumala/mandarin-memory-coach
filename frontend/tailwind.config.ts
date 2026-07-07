import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#172126",
        jade: "#147d64",
        saffron: "#d97706",
        porcelain: "#f8faf7",
      },
      boxShadow: {
        soft: "0 18px 48px rgba(23, 33, 38, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;
