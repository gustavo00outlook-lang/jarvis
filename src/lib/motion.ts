/**
 * Timing e easing — sincronizado com globals.css (--jarvis-motion-ms).
 */
export const JARVIS_MOTION = {
  ms: 980,
  msClose: 560,
  /** Entrada do texto de resposta (fade + translateY sutil) */
  msText: 420,
  /** Saída do texto após a fala — sincronizado com .jarvis-conversation.is-fading */
  msTextFade: 520,
  ease: "cubic-bezier(0.16, 1, 0.3, 1)",
  easeOrb: "cubic-bezier(0.12, 0.9, 0.2, 1)",
  staggerMs: 40,
  /** Ação PC / confirmação — orb encolhe à esquerda */
  orbDockTransform: "translate(-14vw, 0) scale(0.66)",
  /** Google/painel à esquerda — orb desliza à DIREITA (sincronizado com painel) */
  orbDockBrowserTransform: "translate(22vw, 0) scale(0.54)",
  orbIdleTransform: "translate(0, 0) scale(1)",
  orbTransformOrigin: "50% 50%",
} as const;

export function orbTransition(prop = "all"): string {
  const { ms, easeOrb } = JARVIS_MOTION;
  return `${prop} ${ms}ms ${easeOrb}`;
}

export function panelTransition(): string {
  const { ms, ease } = JARVIS_MOTION;
  return `opacity ${ms}ms ${ease}, transform ${ms}ms ${ease}`;
}

export function fadeTransition(prop = "opacity"): string {
  const { ms, ease } = JARVIS_MOTION;
  return `${prop} ${ms}ms ${ease}`;
}

export function motionReleaseDelay(): number {
  return Math.max(0, JARVIS_MOTION.ms - JARVIS_MOTION.staggerMs);
}

export function motionCloseDelay(): number {
  return Math.max(0, JARVIS_MOTION.msClose - 24);
}