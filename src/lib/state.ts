import { create } from "zustand";
import { JARVIS_THEME } from "./theme";

export type JarvisState = "idle" | "listening" | "thinking" | "speaking";
export type LayoutMode = "idle" | "widgets" | "operating";
export type JarvisMood = "calm" | "happy" | "playful" | "warm" | "alert" | "focused";

function computeLayoutMode(s: {
  working: boolean;
  showChatWidget: boolean;
  showMusicWidget: boolean;
}): LayoutMode {
  if (s.working) return "operating";
  if (s.showChatWidget || s.showMusicWidget) return "widgets";
  return "idle";
}

export interface NowPlaying {
  title: string;
  artist: string;
}

export interface ActiveAgentInfo {
  id: string;
  name: string;
  reason?: string;
}

interface JarvisStore {
  state: JarvisState;
  intensity: number;
  caption: string;
  activeAgent: ActiveAgentInfo | null;
  setActiveAgent: (agent: ActiveAgentInfo | null) => void;
  nowPlaying: NowPlaying | null;
  isMusicPlaying: boolean;
  musicProgress: number;

  // Amplitude real do áudio do TTS (0..1) — faz o orb dançar com a voz
  audioLevel: number;
  setAudioLevel: (v: number) => void;

  // Modo trabalho: agente executando tools — orb desloca, chat ativo
  working: boolean;
  setWorking: (v: boolean) => void;

  /** Painel de navegação aberto — permanece até browse_close */
  browserActive: boolean;
  setBrowserActive: (v: boolean) => void;

  /** Tom emocional detectado (humor, pegadinha, etc.) */
  mood: JarvisMood;
  tone: string;
  setMood: (mood: JarvisMood, tone?: string) => void;

  // Layout TikTok 763349: idle | widgets | operating
  layoutMode: LayoutMode;
  showChatWidget: boolean;
  showMusicWidget: boolean;
  toggleChatWidget: () => void;
  toggleMusicWidget: () => void;
  setShowChatWidget: (v: boolean) => void;
  setShowMusicWidget: (v: boolean) => void;

  // Fase 1: visible reasoning trace (Grok thinking in real time)
  reasoningTrace: string;
  isDeepThinking: boolean;

  setState: (state: JarvisState) => void;
  setIntensity: (value: number) => void;
  setCaption: (text: string) => void;
  setNowPlaying: (track: NowPlaying | null) => void;
  setMusicPlaying: (isPlaying: boolean) => void;
  setMusicProgress: (progress: number) => void;

  // High-level actions used by UI / WS
  startListening: () => void;
  startThinking: () => void;
  startSpeaking: (caption?: string) => void;
  goIdle: () => void;

  // Fase 1: deep reasoning controls
  startDeepThinking: (effort?: string) => void;
  appendReasoningChunk: (chunk: string) => void;
  finishReasoning: (fullTrace: string, reasoningTokens?: number) => void;
  clearReasoning: () => void;

  // Music helpers
  playMusic: (track?: NowPlaying) => void;
  pauseMusic: () => void;
  setTrackProgress: (p: number) => void;

  // Fase 2: confirmation pending for orb visual
  confirmationPending: boolean;
  setConfirmationPending: (pending: boolean) => void;

  /** Mantém modo HUD ativo após interação (volta ao relógio após idle) */
  hudPinned: boolean;
  pinHud: () => void;
  unpinHud: () => void;
}

export const useJarvis = create<JarvisStore>((set, get) => ({
  state: "idle",
  intensity: 0.15,
  caption: "",
  activeAgent: null,
  setActiveAgent: (agent) => set({ activeAgent: agent }),
  nowPlaying: null,
  isMusicPlaying: false,
  musicProgress: 0,
  reasoningTrace: "",
  isDeepThinking: false,
  confirmationPending: false,
  hudPinned: false,
  audioLevel: 0,
  working: false,
  browserActive: false,
  mood: "calm",
  tone: "neutro",
  layoutMode: "idle",
  showChatWidget: false,
  showMusicWidget: false,

  setAudioLevel: (v) => set({ audioLevel: Math.max(0, Math.min(1, v)) }),
  setWorking: (v) =>
    set((s) => {
      const working = v;
      return {
        working,
        layoutMode: computeLayoutMode({
          working,
          showChatWidget: s.showChatWidget,
          showMusicWidget: s.showMusicWidget,
        }),
      };
    }),

  setBrowserActive: (browserActive) => set({ browserActive }),

  setMood: (mood, tone) =>
    set({
      mood,
      ...(tone !== undefined ? { tone } : {}),
    }),

  setShowChatWidget: (showChatWidget) =>
    set((s) => ({
      showChatWidget,
      layoutMode: computeLayoutMode({
        working: s.working,
        showChatWidget,
        showMusicWidget: s.showMusicWidget,
      }),
    })),

  setShowMusicWidget: (showMusicWidget) =>
    set((s) => ({
      showMusicWidget,
      layoutMode: computeLayoutMode({
        working: s.working,
        showChatWidget: s.showChatWidget,
        showMusicWidget,
      }),
    })),

  toggleChatWidget: () =>
    set((s) => {
      const showChatWidget = !s.showChatWidget;
      return {
        showChatWidget,
        layoutMode: computeLayoutMode({
          working: s.working,
          showChatWidget,
          showMusicWidget: s.showMusicWidget,
        }),
      };
    }),

  toggleMusicWidget: () =>
    set((s) => {
      const showMusicWidget = !s.showMusicWidget;
      const next = {
        showMusicWidget,
        layoutMode: computeLayoutMode({
          working: s.working,
          showChatWidget: s.showChatWidget,
          showMusicWidget,
        }),
      };
      if (showMusicWidget && !s.nowPlaying) {
        return {
          ...next,
          isMusicPlaying: true,
          nowPlaying: { title: "Still Into You", artist: "Paramore" },
          musicProgress: 62,
        };
      }
      return next;
    }),

  setState: (state) => set({ state }),
  setIntensity: (intensity) => set({ intensity: Math.max(0, Math.min(1, intensity)) }),
  setCaption: (caption) => set({ caption }),
  setNowPlaying: (nowPlaying) => set({ nowPlaying }),
  setMusicPlaying: (isMusicPlaying) => set({ isMusicPlaying }),
  setMusicProgress: (musicProgress) => set({ musicProgress: Math.max(0, Math.min(100, musicProgress)) }),

  startListening: () => set({
    state: "listening",
    intensity: 0.55,
    caption: "Escutando...",
    hudPinned: true,
  }),

  startThinking: () => set({
    state: "thinking",
    intensity: 0.72,
    caption: "Processando...",
    hudPinned: true,
  }),

  startSpeaking: (caption = "") => set({
    state: "speaking",
    intensity: 1.0,
    caption,
    hudPinned: true,
  }),

  goIdle: () => set({
    state: "idle",
    intensity: 0.15,
    caption: "",
    isDeepThinking: false,
    hudPinned: false,
  }),

  // ============================================================
  // FASE 1: Deep Reasoning (visible thinking trace)
  // ============================================================
  startDeepThinking: (effort = "high") => set({
    state: "thinking",
    intensity: effort === "high" ? 0.92 : effort === "medium" ? 0.82 : 0.72,
    caption: `Pensando profundamente (${effort})...`,
    reasoningTrace: "",
    isDeepThinking: true,
  }),

  appendReasoningChunk: (chunk) => set((s) => ({
    reasoningTrace: (s.reasoningTrace + chunk).slice(-2000), // keep last ~2000 chars
    intensity: Math.min(1.0, s.intensity + 0.015), // subtle ramp while thinking
  })),

  finishReasoning: (fullTrace, reasoningTokens = 0) => set((s) => ({
    reasoningTrace: fullTrace,
    isDeepThinking: false,
    caption: reasoningTokens > 0
      ? `Raciocínio concluído (${reasoningTokens} tokens)`
      : "Raciocínio concluído",
  })),

  clearReasoning: () => set({
    reasoningTrace: "",
    isDeepThinking: false,
  }),

  playMusic: (track) => set((s) => ({
    isMusicPlaying: true,
    nowPlaying: track ?? s.nowPlaying ?? { title: "Neural Drift", artist: "JARVIS Core" },
    musicProgress: s.musicProgress || 12,
  })),

  pauseMusic: () => set({ isMusicPlaying: false }),

  setTrackProgress: (p) => set({ musicProgress: Math.max(0, Math.min(100, p)) }),

  setConfirmationPending: (pending) => set({
    confirmationPending: pending,
    ...(pending ? { hudPinned: true } : {}),
  }),

  pinHud: () => set({ hudPinned: true }),
  unpinHud: () => set({ hudPinned: false }),
}));

// Keep legacy STATE_COLORS export for any old code still using it (maps to theme)
export const STATE_COLORS: Record<JarvisState, { core: string; edge: string }> = {
  idle:      JARVIS_THEME.colors.orb.idle,
  listening: JARVIS_THEME.colors.orb.listening,
  thinking:  JARVIS_THEME.colors.orb.thinking,
  speaking:  JARVIS_THEME.colors.orb.speaking,
};

if (typeof window !== "undefined" && process.env.NODE_ENV === "development") {
  (window as Window & { __jarvisDev?: { setWorking: (v: boolean) => void } }).__jarvisDev = {
    setWorking: (v) => useJarvis.getState().setWorking(v),
  };
}
