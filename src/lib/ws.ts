import { useEffect, useRef } from "react";
import { useJarvis } from "./state";
import { motionCloseDelay, motionReleaseDelay } from "./motion";
import { jarvisTTS } from "./tts";
import { jarvisWsUrl } from "./apiBase";

export function useJarvisWS() {
  const setState = useJarvis((s) => s.setState);
  const setCaption = useJarvis((s) => s.setCaption);
  const setIntensity = useJarvis((s) => s.setIntensity);
  const startListening = useJarvis((s) => s.startListening);
  const startThinking = useJarvis((s) => s.startThinking);
  const startSpeaking = useJarvis((s) => s.startSpeaking);
  const goIdle = useJarvis((s) => s.goIdle);
  const setMood = useJarvis((s) => s.setMood);

  // Fase 1: deep reasoning handlers
  const startDeepThinking = useJarvis((s) => s.startDeepThinking);
  const appendReasoningChunk = useJarvis((s) => s.appendReasoningChunk);
  const finishReasoning = useJarvis((s) => s.finishReasoning);
  const clearReasoning = useJarvis((s) => s.clearReasoning);

  const captionBuffer = useRef("");
  const prefetchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPrefetchLen = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: any = null;
    let hasLoggedOffline = false;

    const connect = () => {
      ws = new WebSocket(jarvisWsUrl());

      ws.onopen = () => {
        hasLoggedOffline = false;
        goIdle();
      };

      ws.onclose = () => {
        goIdle();
        // Only log once when backend is not available (normal during testing)
        if (!hasLoggedOffline) {
          console.log("%c[JARVIS] Backend offline (WS not connected) — normal during testing", "color:#666");
          hasLoggedOffline = true;
        }
        reconnectTimer = setTimeout(connect, 2200);
      };

      ws.onerror = () => {
        // Suppress noisy errors
        ws?.close();
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);

          // Normal state machine
          if (msg.type === "state") {
            const s = msg.state;
            if (s === "listening") startListening();
            else if (s === "thinking") { captionBuffer.current = ""; startThinking(); }
            else if (s === "speaking") {
              // Mantém painel browser aberto — não zera working/browserActive ao falar
              const external = typeof window !== "undefined" && (window as any).__jarvis_tts_playing;
              if (!external && msg.text) startSpeaking(msg.text);
              else if (!external) useJarvis.setState({ state: "speaking", intensity: 1.0 });
            }
            else if (s === "idle") {
              const st = useJarvis.getState();
              const win = typeof window !== "undefined" ? (window as Window & {
                __jarvis_http_pending?: boolean;
                __jarvis_tts_playing?: boolean;
              }) : null;
              const pending = !!win?.__jarvis_http_pending;
              const ttsPlaying = !!win?.__jarvis_tts_playing;
              if (pending || ttsPlaying || st.state === "speaking") {
                if (!st.browserActive) useJarvis.getState().setWorking(false);
                return;
              }
              if (!st.browserActive) {
                useJarvis.getState().setWorking(false);
                goIdle();
              } else {
                useJarvis.setState({ state: "idle", intensity: 0.15 });
              }
            }
            else { goIdle(); }
          } else if (msg.type === "caption_chunk") {
            // Streaming token from Grok chat — accumulate and show live
            captionBuffer.current += msg.delta || "";
            setCaption(captionBuffer.current.slice(-280));
            const buf = captionBuffer.current.trim();
            if (buf.length >= 48 && buf.length - lastPrefetchLen.current >= 24) {
              lastPrefetchLen.current = buf.length;
              if (prefetchDebounce.current) clearTimeout(prefetchDebounce.current);
              prefetchDebounce.current = setTimeout(() => {
                jarvisTTS.prefetch?.(buf);
              }, 120);
            }
          } else if (msg.type === "agent_suggestion") {
            useJarvis.getState().setActiveAgent({
              id: String(msg.id || ""),
              name: String(msg.name || msg.id || ""),
              reason: msg.reason ? String(msg.reason) : undefined,
            });
          } else if (msg.type === "intensity") {
            setIntensity(msg.value);
          } else if (msg.type === "tone") {
            const mood = String(msg.mood || "calm") as import("./state").JarvisMood;
            setMood(mood, msg.tone ? String(msg.tone) : undefined);
            jarvisTTS.setTone?.(msg.tone ? String(msg.tone) : "neutro");
          } else if (msg.type === "transcript" && msg.role === "jarvis") {
            const reply = String(msg.text || "").trim();
            if (msg.tone) jarvisTTS.setTone?.(String(msg.tone));
            if (reply) {
              jarvisTTS.prefetch?.(reply);
              setCaption(reply);
              window.dispatchEvent(new CustomEvent("jarvis:narration", { detail: { text: reply } }));
              const win = typeof window !== "undefined" ? (window as Window & {
                __jarvis_http_reply?: string;
              }) : null;
              const httpHandled = win?.__jarvis_http_reply === reply;
              if (!httpHandled) {
                useJarvis.setState({ state: "speaking", intensity: 1.0 });
                void jarvisTTS.unlock?.().then(() => jarvisTTS.speak(reply));
              }
            }
          } else if (msg.type === "caption") {
            setCaption(msg.text || "");
          }

          // ============================================================
          // FASE 1: Deep Reasoning events (streamed from backend)
          // ============================================================
          else if (msg.type === "reasoning_start") {
            startDeepThinking(msg.effort);
          } else if (msg.type === "reasoning_chunk") {
            appendReasoningChunk(msg.delta || "");
            if (msg.accumulated) {
              setCaption(msg.accumulated.slice(-220));
            }
          } else if (msg.type === "reasoning_complete") {
            finishReasoning(msg.reasoning_trace || "", msg.reasoning_tokens || 0);
          } else if (msg.type === "answer_chunk") {
            // Optional
          }

          // ============================================================
          // FASE 2: Action Confirmation events
          // ============================================================
          else if (msg.type === "tool_call") {
            const toolName = String(msg.tool || "");
            const isBrowserTool =
              toolName === "browse_open" ||
              toolName === "open_browser_search" ||
              toolName === "open_url" ||
              toolName === "web_search" ||
              toolName.startsWith("browse_");
            if (msg.status === "running") {
              if (isBrowserTool) {
                useJarvis.getState().setBrowserActive(true);
              } else {
                useJarvis.getState().setWorking(true);
              }
            }
            else if (msg.status === "done") {
              const tool = String(msg.tool || "");
              const { browserActive } = useJarvis.getState();
              const keepsDock =
                tool.startsWith("browse_") ||
                tool === "open_browser_search" ||
                tool === "open_url" ||
                tool === "web_search" ||
                tool === "open_full_browser" ||
                tool === "open_app" ||
                tool.startsWith("desktop_") ||
                tool === "watch_screen" ||
                tool === "look_at_screen";
              if (!browserActive && !keepsDock) {
                setTimeout(
                  () => useJarvis.getState().setWorking(false),
                  motionReleaseDelay(),
                );
              }
            }
            window.dispatchEvent(new CustomEvent("jarvis:tool-call", { detail: msg }));
            if (msg.tool === "browse_close" && msg.status === "done") {
              useJarvis.getState().setBrowserActive(false);
              setTimeout(() => useJarvis.getState().setWorking(false), motionCloseDelay());
              window.dispatchEvent(new CustomEvent("jarvis:browser-clear"));
            }
          } else if (msg.type === "panel_close") {
            useJarvis.getState().setBrowserActive(false);
            setTimeout(() => useJarvis.getState().setWorking(false), motionCloseDelay());
            window.dispatchEvent(new CustomEvent("jarvis:browser-clear"));
          } else if (msg.type === "ui_fullscreen") {
            window.dispatchEvent(new CustomEvent("jarvis:fullscreen"));
          } else if (msg.type === "voice_changed") {
            jarvisTTS.setVoiceEngine?.(
              (msg.engine as string) || (msg.voice_id as string) || "eleven",
              msg.label
            );
          } else if (msg.type === "cowatch_start") {
            window.dispatchEvent(new CustomEvent("jarvis:cowatch-start"));
          } else if (msg.type === "cowatch_end") {
            window.dispatchEvent(new CustomEvent("jarvis:cowatch-end"));
          } else if (msg.type === "browser_preview") {
            // about:blank não é navegação — abrir o painel por ele deixa um bloco
            // branco na tela e desloca o orb sem motivo
            const purl = String(msg.url || "").trim().toLowerCase();
            const hasPage = purl.startsWith("http") || purl.startsWith("file://");
            if (!hasPage && !String(msg.query || "").trim()) return;
            const st = useJarvis.getState();
            if (!st.browserActive) {
              st.setBrowserActive(true);
            }
            window.dispatchEvent(new CustomEvent("jarvis:browser-preview", { detail: msg }));
          } else if (msg.type === "jarvis_narration") {
            // UI + prefetch; a fala vem do transcript role=jarvis (evita TTS em dobro)
            const ntext = String(msg.text || "").trim();
            if (ntext) {
              jarvisTTS.prefetch?.(ntext);
              setCaption(ntext);
              window.dispatchEvent(new CustomEvent("jarvis:narration", { detail: msg }));
            }
          } else if (msg.type === "agent_thought") {
            window.dispatchEvent(new CustomEvent("jarvis:agent-thought", { detail: msg }));
          } else if (msg.type === "action_requires_confirmation") {
            console.warn("[JARVIS] Action requires confirmation:", msg);
            // Set confirmationPending directly for orb color (orb reads from Zustand store)
            useJarvis.getState().setConfirmationPending(true);
            // Also dispatch custom event for UI buttons
            window.dispatchEvent(new CustomEvent("jarvis:confirmation-required", { detail: msg }));
          } else if (msg.type === "structured_action") {
            // Hermes audit: also surface executed actions to the UI (caption/orb feedback)
            console.log("[JARVIS] Structured action executed:", msg);
            window.dispatchEvent(new CustomEvent("jarvis:structured-action", { detail: msg }));
            if (msg.execution) {
              // Let the main page speak the result if it wants
              window.dispatchEvent(new CustomEvent("jarvis:speak", { detail: msg.execution }));
            }
          } else if (msg.type === "error") {
            console.error("[JARVIS] Backend error event:", msg);
            window.dispatchEvent(new CustomEvent("jarvis:error", { detail: msg }));
          }
        } catch {}
      };
    };

    connect();
    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [
    setState, setCaption, setIntensity,
    startListening, startThinking, startSpeaking, goIdle, setMood,
    startDeepThinking, appendReasoningChunk, finishReasoning, clearReasoning
  ]);
}
