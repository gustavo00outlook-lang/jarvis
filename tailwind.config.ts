import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Legacy (still used in a few places)
        "jarvis-cyan":   "#00B7FF",
        "jarvis-bright": "#5BD7FF",
        "jarvis-deep":   "#0078B8",

        // Full JARVIS palette matching theme.ts
        jarvis: {
          primary: "#00ddff",
          accent: "#22ffaa",
          warning: "#ffcc44",
          text: "#ffffff",
          textSecondary: "#a0f0ff",
          cyan: "#00ddff",
          bright: "#5BD7FF",
        },
      },
      fontFamily: {
        orbitron: ["Orbitron", "system-ui", "sans-serif"],
      },
      animation: {
        "pulse-slow": "pulse 3s ease-in-out infinite",
        "orb-glow": "orb-glow 2.2s ease-in-out infinite",
      },
      keyframes: {
        "orb-glow": {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
