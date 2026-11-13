"use client";

import { useEffect, useRef } from "react";
import { JARVIS_MOTION } from "@/lib/motion";

interface JarvisConversationProps {
  jarvisText: string;
  processing: boolean;
  greeting: string | null;
  fading: boolean;
  browserMode: boolean;
  actionMode: boolean;
  motionMs: number;
}

const FADE_AFTER_TTS_MS = 4500;

/** Legenda JARVIS — card sutil, texto menor, some após a fala */
export function JarvisConversation({
  jarvisText,
  processing,
  greeting,
  fading,
  browserMode,
  actionMode,
  motionMs,
}: JarvisConversationProps) {
  const fadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const clearFade = () => {
      if (fadeTimer.current) {
        clearTimeout(fadeTimer.current);
        fadeTimer.current = null;
      }
    };

    const onTtsEnd = () => {
      clearFade();
      fadeTimer.current = setTimeout(() => {
        window.dispatchEvent(new CustomEvent("jarvis:text-fade"));
      }, FADE_AFTER_TTS_MS);
    };

    window.addEventListener("jarvis:tts-end", onTtsEnd);
    return () => {
      clearFade();
      window.removeEventListener("jarvis:tts-end", onTtsEnd);
    };
  }, []);

  const showGreeting = greeting && !jarvisText;
  const display = jarvisText || (showGreeting ? greeting : "");

  if (!display && !processing) return null;

  return (
    <div
      className={`jarvis-conversation ${browserMode ? "is-browser-mode" : ""} ${actionMode ? "is-action-mode" : ""} ${fading ? "is-fading" : "is-visible"}`}
      style={{
        ["--orb-motion-ms" as string]: `${motionMs}ms`,
        ["--jarvis-text-ms" as string]: `${JARVIS_MOTION.msText}ms`,
      }}
      aria-live="polite"
    >
      {/* key={display}: troca de texto remonta o <p> e replay da entrada (sem corte seco) */}
      {display && (
        <p key={display} className="jarvis-reply-text">
          {display}
        </p>
      )}
      {processing && !jarvisText && (
        <p className="jarvis-reply-text jarvis-reply-text--processing">Processando...</p>
      )}
    </div>
  );
}