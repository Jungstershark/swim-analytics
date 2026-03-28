import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ssa: {
          navy: "#0c2340",
          "navy-light": "#1a3a5c",
          teal: "#00857c",
          "teal-light": "#00a89d",
          "teal-dark": "#006b63",
          gold: "#c4a35a",
          slate: "#3d4f5f",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
