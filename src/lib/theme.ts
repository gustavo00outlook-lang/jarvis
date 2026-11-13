export const JARVIS_THEME = {
  colors: {
    /* Huw Prosser design: primary electric cyan #00d4ff on near-black #050505 */
    primary: "#00d4ff",
    accent: "#22ffaa",
    warning: "#ffcc44",
    text: "#ffffff",
    textSecondary: "#a0f0ff",

    orb: {
      idle:      { core: "#0a1428", edge: "#00d4ff" },
      listening: { core: "#0a1f15", edge: "#00e8c4" },
      thinking:  { core: "#1f1908", edge: "#ffcc44" },
      speaking:  { core: "#0a1622", edge: "#00d4ff" },
    }
  },

  glow: {
    strength: "0 0 25px",
    /* Huw: updated cyan primary glows */
    orbIdle: "0 0 35px #00d4ff",
    orbActive: "0 0 70px #00d4ff",
  },

  opacity: {
    rings: {
      outer: 0.28,
      middle: 0.55,
      inner: 0.85,
    }
  },

  bloom: {
    intensity: 1.32,
    luminanceThreshold: 0.19,
    radius: 0.98,
  },

  animation: {
    speed: 1.18,
    /** Sincronizado com src/lib/motion.ts */
    panelMs: 560,
    ease: "cubic-bezier(0.19, 1, 0.22, 1)",
  },
} as const;

export type JarvisTheme = typeof JARVIS_THEME;

// Helper to get orb colors safely
export function getOrbColors(state: keyof typeof JARVIS_THEME.colors.orb) {
  return JARVIS_THEME.colors.orb[state] ?? JARVIS_THEME.colors.orb.idle;
}

// Map state -> human label + color
export const STATE_LABELS: Record<string, { text: string; color: string }> = {
  idle:      { text: "ONLINE",    color: JARVIS_THEME.colors.orb.idle.edge },
  listening: { text: "LISTENING", color: JARVIS_THEME.colors.orb.listening.edge },
  thinking:  { text: "THINKING",  color: JARVIS_THEME.colors.orb.thinking.edge },
  speaking:  { text: "SPEAKING",  color: JARVIS_THEME.colors.orb.speaking.edge },
};
