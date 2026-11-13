"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useJarvis } from "@/lib/state";
import { jarvisTTS } from "@/lib/tts";
import { createSpeechMic, type SpeechMicController } from "@/lib/speechMic";
import { preferPanelSearch } from "@/lib/jarvisClient";
import { wantsBrowserPanel } from "@/lib/browserIntent";
import { applyChatToolsToUi, scheduleReleaseWorking, usesPanel } from "@/lib/toolUi";
import { dispatchUserSent } from "./JarvisUserEcho";

import { jarvisApi, jarvisFetch, jarvisHealthOk } from "@/lib/apiBase";

const API = jarvisApi("");

// Silêncio um pouco maior = frase completa antes de enviar
const SILENCE_SEND_MS = 1800;

const QUICK_SUGGESTIONS = [
  "Pesquisa IA e clica no primeiro resultado",
  "Assista comigo um vídeo do instagram",
  "Veja minha tela em tempo real",
  "Me ajuda com isso",
];

interface JarvisInputBarProps {
  onReply?: (text: string) => void;
}

export function JarvisInputBar({ onReply }: JarvisInputBarProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const [micError, setMicError] = useState("");
  const [typingOpen, setTypingOpen] = useState(true);
  const [dockHovered, setDockHovered] = useState(false);
  const [pending, setPending] = useState<any>(null);

  const micCtrlRef = useRef<SpeechMicController | null>(null);
  const micOnRef = useRef(false);
  const micWantedRef = useRef(false);
  const loadingRef = useRef(false);
  const lastSendAt = useRef(0);
  const utteranceBuf = useRef("");
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { startThinking, startListening, startSpeaking, goIdle, setConfirmationPending, setWorking } =
    useJarvis();

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimer.current) {
      clearTimeout(silenceTimer.current);
      silenceTimer.current = null;
    }
  }, []);

  useEffect(() => {
    setTypingOpen(true);
    const focus = window.setTimeout(() => inputRef.current?.focus(), 500);
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.length !== 1) return;
      if (document.activeElement === inputRef.current) return;
      setTypingOpen(true);
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(focus);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    fetch(`${API}/api/pending-action`)
      .then((r) => r.json())
      .then((d) => {
        if (d.pending) {
          setPending(d.pending);
          setConfirmationPending(true);
        }
      })
      .catch(() => {});
  }, [setConfirmationPending]);

  useEffect(() => {
    const onConfirm = (e: Event) => {
      setPending((cur: any) => cur ?? (e as CustomEvent).detail);
      setConfirmationPending(true);
    };
    window.addEventListener("jarvis:confirmation-required", onConfirm);
    return () => window.removeEventListener("jarvis:confirmation-required", onConfirm);
  }, [setConfirmationPending]);

  const showCaptionOnly = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t) return;
      onReply?.(t);
      useJarvis.getState().setCaption(t);
      goIdle();
    },
    [onReply, goIdle],
  );

  const speakAndShow = useCallback(
    (text: string, opts?: { silent?: boolean }) => {
      const t = text.trim();
      if (!t) return;
      if (opts?.silent || t.includes("Núcleo em carregamento") || t.includes("backend")) {
        showCaptionOnly(t);
        return;
      }
      if (typeof window !== "undefined") {
        const w = window as Window & { __jarvis_http_reply?: string };
        w.__jarvis_http_reply = t;
        window.setTimeout(() => {
          if (w.__jarvis_http_reply === t) w.__jarvis_http_reply = undefined;
        }, 8000);
      }
      onReply?.(t);
      startSpeaking(t);
      void jarvisTTS.unlock?.().then(() => jarvisTTS.speak(t));
    },
    [onReply, startSpeaking, showCaptionOnly],
  );

  const clearTtsPlaying = useCallback(() => {
    if (typeof window !== "undefined") {
      (window as Window & { __jarvis_tts_playing?: boolean }).__jarvis_tts_playing = false;
    }
  }, []);

  const stopMic = useCallback(() => {
    micOnRef.current = false;
    setMicOn(false);
    micCtrlRef.current?.stop();
    micCtrlRef.current = null;
    clearSilenceTimer();
    utteranceBuf.current = "";
    if (useJarvis.getState().state === "listening") goIdle();
  }, [goIdle, clearSilenceTimer]);

  const send = useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim();
      if (!text) return;
      if (loadingRef.current && Date.now() - lastSendAt.current < 6000) return;
      lastSendAt.current = Date.now();
      // Mantém intenção de escuta após a resposta (mãos livres)
      const keepListening = micWantedRef.current || micOnRef.current;
      dispatchUserSent(text);
      clearSilenceTimer();
      utteranceBuf.current = "";
      stopMic();
      if (keepListening) micWantedRef.current = true;
      await jarvisTTS.unlock?.();
      setInput("");
      setTypingOpen(true);
      loadingRef.current = true;
      setLoading(true);
      if (typeof window !== "undefined") {
        (window as Window & { __jarvis_http_pending?: boolean }).__jarvis_http_pending = true;
      }
      startThinking();
      if (wantsBrowserPanel(text)) {
        useJarvis.getState().setBrowserActive(true);
      }
      let uiResult = { panelClosing: false, keepWorking: false };
      let hasPanel = false;

      try {
        let data: Record<string, unknown> | null = null;
        let lastErr: unknown = null;
        // 2 tentativas: evita esperar 4×90s se backend/LLM estiver lento
        for (let attempt = 0; attempt < 2; attempt++) {
          if (attempt > 0) {
            if (!(await jarvisHealthOk(4000))) {
              await new Promise((r) => setTimeout(r, 600 + attempt * 400));
            }
          }
          try {
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), 50000);
            const res = await jarvisFetch("/api/jarvis/chat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                text,
                browser_active: useJarvis.getState().browserActive,
                prefer_panel: preferPanelSearch(),
              }),
              signal: ctrl.signal,
            });
            clearTimeout(timer);
            if (!res.ok) {
              const errBody = await res.text().catch(() => "");
              throw new Error(`HTTP ${res.status}${errBody ? `: ${errBody.slice(0, 120)}` : ""}`);
            }
            data = await res.json();
            break;
          } catch (e) {
            lastErr = e;
            // Só re-tenta se backend sumiu; timeout de LLM não deve loopar
            const msg = String((e as Error)?.message || e || "");
            if (attempt < 1 && (msg.includes("Failed to fetch") || msg.includes("NetworkError"))) {
              continue;
            }
            throw e;
          }
        }
        if (!data) throw lastErr ?? new Error("sem resposta");

        if (data.requires_confirmation) {
          setPending(data);
          setConfirmationPending(true);
          setWorking(true);
          speakAndShow(String(data.confirmation_prompt || "Ação de risco. Confirma, senhor?"));
        } else if (data.error && !data.response) {
          // Distingue erro de app vs backend caído (evita falso "offline")
          const alive = await jarvisHealthOk(2500);
          if (alive) {
            speakAndShow(
              String(data.error).slice(0, 180) ||
                "Tive um contratempo, senhor. Pode repetir?",
            );
          } else {
            showCaptionOnly("Backend offline — rode INICIAR-JARVIS.bat e aguarde 30s.");
          }
        } else {
          jarvisTTS.setVoiceEngine?.(
            "local",
            (data.voice_label as string | undefined) || "JARVIS Thomas (master.wav)",
          );
          uiResult = applyChatToolsToUi(data.tools_used as { tool?: string }[] | undefined);
          hasPanel = usesPanel(data.tools_used as { tool?: string }[] | undefined);
          const reply = String(data.response || "Sim, senhor.");
          if (data.agent_suggestion || data.ruflo_active) {
            useJarvis.getState().setActiveAgent({
              id: String(data.agent_suggestion || data.ruflo_mode || "ruflo"),
              name: String(
                data.agent_name ||
                  data.ruflo_label ||
                  data.agent_suggestion ||
                  "Ruflo",
              ),
              reason: (data.orchestrator as { suggestion_reason?: string } | undefined)
                ?.suggestion_reason || (data.ruflo_reason as string | undefined),
            });
          }
          void jarvisTTS.prefetch?.(reply);
          await jarvisTTS.unlock?.();
          speakAndShow(reply);
        }
      } catch (err) {
        useJarvis.getState().setBrowserActive(false);
        window.dispatchEvent(new CustomEvent("jarvis:browser-clear"));
        await jarvisTTS.unlock?.();
        const aborted = err instanceof Error && err.name === "AbortError";
        if (aborted) {
          speakAndShow("Demorou mais que o esperado, senhor. Tente um pedido mais curto ou repita.");
        } else {
          const alive = await jarvisHealthOk(2500);
          if (alive) {
            speakAndShow("Falha na resposta, senhor. Pode repetir o pedido?");
          } else {
            showCaptionOnly("Backend offline. Duplo-clique em INICIAR-JARVIS.bat na pasta jarvis-pro.");
          }
        }
        scheduleReleaseWorking({ panelClosing: true, keepWorking: false, hasPanel: false });
      } finally {
        if (typeof window !== "undefined") {
          (window as Window & { __jarvis_http_pending?: boolean }).__jarvis_http_pending = false;
        }
        loadingRef.current = false;
        setLoading(false);
        scheduleReleaseWorking({
          panelClosing: uiResult.panelClosing,
          keepWorking: uiResult.keepWorking,
          hasPanel,
        });
        // Reativa mic se estava em mãos-livres (tts-end também reativa; isto é backup)
        if (keepListening && micWantedRef.current) {
          window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent("jarvis:mic-resume-request"));
          }, 2600);
        }
      }
    },
    [input, onReply, setConfirmationPending, speakAndShow, startThinking, stopMic, setWorking, clearSilenceTimer]
  );

  const scheduleSendAfterSilence = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t) return;
      utteranceBuf.current = t;
      clearSilenceTimer();
      silenceTimer.current = setTimeout(() => {
        const ready = utteranceBuf.current.trim();
        if (ready && !loadingRef.current) void send(ready);
      }, SILENCE_SEND_MS);
    },
    [send, clearSilenceTimer]
  );

  const startMicRaw = useCallback(() => {
    jarvisTTS.stop();
    clearTtsPlaying();
    void jarvisTTS.unlock?.();
    setMicError("");

    const ctrl = createSpeechMic({
      lang: "pt-BR",
      continuous: true,
      callbacks: {
        onStart: () => {
          micOnRef.current = true;
          setMicOn(true);
          startListening();
        },
        onInterim: (text) => {
          setInput(text);
          scheduleSendAfterSilence(text);
        },
        onFinal: (final) => {
          setInput(final);
          scheduleSendAfterSilence(final);
        },
        onError: (msg, code) => {
          if (code === "no-speech" && micWantedRef.current) return;
          if (!micWantedRef.current) {
            micOnRef.current = false;
            setMicOn(false);
            if (useJarvis.getState().state === "listening") goIdle();
          }
          if (code !== "no-speech" && code !== "aborted") {
            setMicError(msg);
            console.warn("[mic]", msg);
          }
        },
        onEnd: () => {
          if (!micWantedRef.current) {
            micOnRef.current = false;
            setMicOn(false);
            if (useJarvis.getState().state === "listening") goIdle();
          }
        },
      },
    });

    micCtrlRef.current = ctrl;
    void ctrl.start();
  }, [scheduleSendAfterSilence, startListening, goIdle, clearTtsPlaying]);

  const toggleMic = useCallback(() => {
    void jarvisTTS.unlock?.();
    jarvisTTS.stop();
    clearTtsPlaying();
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (micOnRef.current) {
      micWantedRef.current = false;
      const pendingText = utteranceBuf.current.trim() || input.trim();
      stopMic();
      if (pendingText && !loadingRef.current) void send(pendingText);
    } else {
      micWantedRef.current = true;
      setTypingOpen(false);
      void startMicRaw();
    }
  }, [startMicRaw, stopMic, send, input, clearTtsPlaying]);

  useEffect(() => {
    const pauseMicForTts = () => {
      if (micOnRef.current) {
        micWantedRef.current = true;
        stopMic();
      }
    };
    const resumeMicAfterTts = () => {
      // Anti-eco: espera cauda do áudio antes de reabrir o mic
      if (micWantedRef.current && !loadingRef.current) {
        setTimeout(() => {
          if (micWantedRef.current && !loadingRef.current && !micOnRef.current) {
            void startMicRaw();
          }
        }, 700);
      }
    };
    const resumeRequest = () => {
      if (micWantedRef.current && !loadingRef.current && !micOnRef.current) {
        const ttsPlaying = !!(window as Window & { __jarvis_tts_playing?: boolean })
          .__jarvis_tts_playing;
        if (!ttsPlaying) void startMicRaw();
      }
    };
    window.addEventListener("jarvis:tts-start", pauseMicForTts);
    window.addEventListener("jarvis:tts-end", resumeMicAfterTts);
    window.addEventListener("jarvis:mic-resume-request", resumeRequest);
    return () => {
      window.removeEventListener("jarvis:tts-start", pauseMicForTts);
      window.removeEventListener("jarvis:tts-end", resumeMicAfterTts);
      window.removeEventListener("jarvis:mic-resume-request", resumeRequest);
    };
  }, [startMicRaw, stopMic]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" && e.ctrlKey) {
        e.preventDefault();
        toggleMic();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleMic]);

  useEffect(() => () => clearSilenceTimer(), [clearSilenceTimer]);

  const confirm = async () => {
    void jarvisTTS.unlock?.();
    setPending(null);
    setConfirmationPending(false);
    setWorking(true);
    startThinking();
    try {
      const r = await fetch(`${API}/api/jarvis/confirm`, { method: "POST" });
      const d = await r.json();
      speakAndShow(d.response || d.execution_feedback || "Executado, senhor.");
    } catch {
      speakAndShow("Falha ao confirmar, senhor.");
    }
  };

  const cancel = async () => {
    try {
      await fetch(`${API}/api/jarvis/cancel`, { method: "POST" });
    } catch {}
    setPending(null);
    setConfirmationPending(false);
    speakAndShow("Ação cancelada, senhor.");
  };

  const openTyping = () => {
    setTypingOpen(true);
    stopMic();
    micWantedRef.current = false;
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const forceVisible = !!pending || loading || micOn || typingOpen;
  const zoneOpen = dockHovered || forceVisible;

  return (
    <div
      className={`jarvis-huw-dock-zone${zoneOpen ? " is-hovered" : ""}${forceVisible ? " is-active" : ""}`}
      onPointerEnter={() => setDockHovered(true)}
      onPointerLeave={() => setDockHovered(false)}
      onFocusCapture={() => setDockHovered(true)}
      onBlurCapture={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDockHovered(false);
      }}
    >
    <div className="jarvis-huw-dock">
      {!pending && !loading && zoneOpen && (
        <div className="jarvis-huw-suggestions" aria-label="Sugestões rápidas">
          {QUICK_SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="jarvis-huw-chip"
              onClick={() => {
                void jarvisTTS.unlock?.();
                void send(s);
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {pending && (
        <div className="jarvis-huw-confirm">
          <span className="text-[10px] text-red-300/90">{pending.confirmation_prompt || "Confirmar execução?"}</span>
          <div className="flex gap-2 mt-2 justify-center">
            <button type="button" onClick={confirm} className="wa-confirm-btn">CONFIRMAR</button>
            <button type="button" onClick={cancel} className="wa-cancel-btn">CANCELAR</button>
          </div>
        </div>
      )}

      <div className={`jarvis-huw-input-expand ${typingOpen ? "is-open" : ""}`}>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              void jarvisTTS.unlock?.();
              void send();
            }
            if (e.key === "Escape") setTypingOpen(false);
          }}
          placeholder={loading ? "Processando..." : micOn ? "Ouvindo..." : "Digite..."}
          className="jarvis-huw-input-field"
          disabled={loading}
        />
        {typingOpen && (
          <button
            type="button"
            onClick={() => { void jarvisTTS.unlock?.(); void send(); }}
            disabled={loading || !input.trim()}
            className="jarvis-huw-send"
            aria-label="Enviar"
          >
            {loading ? "•••" : "↵"}
          </button>
        )}
      </div>

      <div className="jarvis-huw-dock-icons">
        <button
          type="button"
          onClick={toggleMic}
          className={`jarvis-huw-icon-btn ${micOn ? "is-active" : ""}`}
          aria-label={micOn ? "Parar microfone" : "Falar com JARVIS"}
        >
          {micOn && <span className="jarvis-huw-pulse" aria-hidden />}
          <MicIcon active={micOn} />
        </button>

        <button
          type="button"
          onClick={openTyping}
          className={`jarvis-huw-icon-btn ${typingOpen ? "is-active" : ""}`}
          aria-label="Digitar mensagem"
        >
          <KeyboardIcon active={typingOpen} />
        </button>
      </div>

      {micOn && (
        <p className="jarvis-huw-hint">Ouvindo — envio automático após {SILENCE_SEND_MS / 1000}s de silêncio</p>
      )}
      {micError && !micOn && (
        <p className="jarvis-huw-hint jarvis-huw-hint-error">{micError}</p>
      )}
    </div>
    </div>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={active ? "#7fe9ff" : "rgba(255,255,255,0.7)"} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
  );
}

function KeyboardIcon({ active }: { active: boolean }) {
  const stroke = active ? "#7fe9ff" : "rgba(255,255,255,0.7)";
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <circle cx="6" cy="10" r="0.8" fill={stroke} stroke="none" />
      <circle cx="10" cy="10" r="0.8" fill={stroke} stroke="none" />
      <circle cx="14" cy="10" r="0.8" fill={stroke} stroke="none" />
      <circle cx="18" cy="10" r="0.8" fill={stroke} stroke="none" />
      <line x1="7" y1="14" x2="17" y2="14" />
    </svg>
  );
}