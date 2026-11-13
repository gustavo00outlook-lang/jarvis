"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { OrbWhatsAppCanvas } from "@/components/orb/OrbWhatsAppCanvas";
import { OperPanels } from "@/components/hud/OperPanels";
import { MusicWidget } from "@/components/hud/MusicWidget";
import { useJarvis } from "@/lib/state";
import { JARVIS_MOTION } from "@/lib/motion";
import { STATE_LABELS } from "@/lib/theme";
import { jarvisApi, jarvisHealthOk } from "@/lib/apiBase";
import { JarvisInputBar } from "./JarvisInputBar";
import { JarvisConversation } from "./JarvisConversation";

const STATE_PT: Record<string, string> = {
  idle: "ONLINE",
  listening: "OUVINDO",
  thinking: "PROCESSANDO",
  speaking: "FALANDO",
};

const API = jarvisApi("");

const ORB_SIZE = "min(30vh, 30vw)";

export function WhatsAppJarvisScreen() {
  const state = useJarvis((s) => s.state);
  const working = useJarvis((s) => s.working);
  const browserActive = useJarvis((s) => s.browserActive);
  const confirmationPending = useJarvis((s) => s.confirmationPending);
  const showMusicWidget = useJarvis((s) => s.showMusicWidget);
  const activeAgent = useJarvis((s) => s.activeAgent);

  const [jarvisText, setJarvisText] = useState("");
  const [processing, setProcessing] = useState(false);
  const [fading, setFading] = useState(false);
  const [backendOk, setBackendOk] = useState(true);

  // Restore conversation history on boot (huwprosser style: memory persists across sessions)
  useEffect(() => {
    let alive = true;
    const restoreHistory = async () => {
      try {
        const res = await fetch(`${API}/api/jarvis/history?limit=8`);
        if (res.ok) {
          const data = await res.json();
          if (data.last_jarvis && !jarvisText && state === "idle" && alive) {
            setJarvisText(data.last_jarvis);
            setFading(false);
          }
        }
      } catch {
        // ignore - history restore is optional
      }
    };
    void restoreHistory();
  }, []);

  useEffect(() => {
    let alive = true;
    let fails = 0;
    const tick = async () => {
      const ok = await jarvisHealthOk(3500);
      if (!alive) return;
      if (ok) {
        fails = 0;
        setBackendOk(true);
        return;
      }
      fails += 1;
      if (fails >= 2) setBackendOk(false);
    };
    void tick();
    const id = window.setInterval(tick, 12000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const browserDocked = useMemo(
    () => browserActive && !confirmationPending,
    [browserActive, confirmationPending]
  );
  /** Esquerda só na barra vermelha de confirmação — conversa/pesquisa ficam no centro ou direita */
  const confirmationDocked = useMemo(() => confirmationPending, [confirmationPending]);

  const label = confirmationPending
    ? { text: "CONFIRMAR", color: "#ff4444" }
    : browserActive
      ? { text: "NAVEGANDO", color: "#7fe9ff" }
      : working
        ? { text: "EXECUTANDO", color: "#ffd97f" }
        : STATE_LABELS[state] ?? STATE_LABELS.idle;

  const displayText = confirmationPending
    ? "AÇÃO PENDENTE"
    : browserActive
      ? "PAINEL ATIVO"
      : working
        ? "EXECUTANDO"
        : state === "thinking"
          ? "PROCESSANDO"
          : (STATE_PT[state] ?? label.text);

  const onJarvisReply = useCallback((text: string) => {
    const t = text.trim();
    if (t) {
      setFading(false);
      setJarvisText(t);
      setProcessing(false);
    }
  }, []);

  useEffect(() => {
    const onNarration = (e: Event) => {
      const text = String((e as CustomEvent<{ text?: string }>).detail?.text || "").trim();
      if (!text) return;
      setFading(false);
      setJarvisText(text);
      setProcessing(false);
    };
    const onUserSent = () => setProcessing(true);
    const onTextFade = () => {
      setFading(true);
      window.setTimeout(() => {
        setJarvisText("");
        setFading(false);
      }, JARVIS_MOTION.msTextFade);
    };

    window.addEventListener("jarvis:narration", onNarration);
    window.addEventListener("jarvis:user-sent", onUserSent);
    window.addEventListener("jarvis:text-fade", onTextFade);
    return () => {
      window.removeEventListener("jarvis:narration", onNarration);
      window.removeEventListener("jarvis:user-sent", onUserSent);
      window.removeEventListener("jarvis:text-fade", onTextFade);
    };
  }, []);

  const greeting =
    !jarvisText && !processing && state === "idle"
      ? "Olá, senhor."
      : !jarvisText && state === "listening"
        ? "Estou ouvindo..."
        : null;

  const orbTransform = browserDocked
    ? JARVIS_MOTION.orbDockBrowserTransform
    : confirmationDocked
      ? JARVIS_MOTION.orbDockTransform
      : JARVIS_MOTION.orbIdleTransform;

  const orbMotionMs =
    browserDocked || confirmationDocked ? JARVIS_MOTION.ms : JARVIS_MOTION.msClose;

  return (
    <div className="absolute inset-0 wa-jarvis-bg overflow-hidden" data-jarvis-ui="wa-v22-huw">
      <div className="absolute inset-0 wa-particles pointer-events-none" aria-hidden />
      <div className="absolute inset-0 wa-vignette pointer-events-none" aria-hidden />

      <OperPanels browserVisible={browserActive} statusVisible={confirmationDocked} />

      {!backendOk && (
        <div
          className="absolute top-3 left-1/2 -translate-x-1/2 z-[60] px-4 py-2 rounded-md bg-red-950/90 border border-red-500/50 text-red-200 text-[11px] font-mono tracking-wide pointer-events-none"
          role="alert"
        >
          BACKEND OFFLINE — duplo-clique INICIAR-JARVIS.bat
        </div>
      )}

      {showMusicWidget && <MusicWidget />}

      <div className={`jarvis-huw-header ${confirmationDocked ? "is-visible" : ""}`} aria-hidden={!confirmationDocked}>
        <div
          className="font-semibold tracking-[0.42em] text-white/92 text-[13px]"
          style={{ fontFamily: "'Montserrat', system-ui, sans-serif" }}
        >
          J A R V I S
        </div>
        <div className="mt-2.5 flex items-center justify-center gap-2">
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: label.color, boxShadow: `0 0 10px ${label.color}` }}
          />
          <span className="text-[10px] font-mono tracking-[3px] uppercase" style={{ color: label.color }}>
            {displayText}
          </span>
        </div>
        {activeAgent?.name && (
          <p className="mt-2 text-[9px] font-mono tracking-[0.2em] text-cyan-300/55 uppercase">
            {activeAgent.name}
          </p>
        )}
      </div>

      <div
        className="absolute inset-0 z-20 pointer-events-none jarvis-orb-stage"
        style={{
          transform: orbTransform,
          transformOrigin: JARVIS_MOTION.orbTransformOrigin,
          transition: `transform ${orbMotionMs}ms ${JARVIS_MOTION.easeOrb}`,
          willChange: "transform",
          contain: "layout style paint",
        }}
      >
        <div
          className="absolute jarvis-orb-dock pointer-events-none"
          style={{
            left: "50%",
            top: "50%",
            width: ORB_SIZE,
            height: ORB_SIZE,
            transform: "translate3d(-50%, -50%, 0)",
          }}
        >
          <div className="relative w-full h-full">
            <OrbWhatsAppCanvas />
          </div>
        </div>
      </div>

      <JarvisConversation
        jarvisText={jarvisText}
        processing={processing}
        greeting={greeting}
        fading={fading}
        browserMode={browserDocked}
        actionMode={confirmationDocked}
        motionMs={orbMotionMs}
      />

      <JarvisInputBar onReply={onJarvisReply} />
    </div>
  );
}