"use client";

import { useEffect } from "react";
import { useJarvisWS } from "@/lib/ws";
import { useJarvis } from "@/lib/state";
import { jarvisApi, waitForJarvisBackend } from "@/lib/apiBase";
import { jarvisTTS } from "@/lib/tts";
import { WhatsAppJarvisScreen } from "@/components/whatsapp/WhatsAppJarvisScreen";
import { isTauri } from "@/lib/nativeBrowser";

/**
 * JARVIS — estilo vídeo WhatsApp 2026-06-11 (orb ciano + Olá senhor + barra fixa).
 */

export default function JarvisInterface() {
  useJarvisWS();
  const { goIdle } = useJarvis();

  useEffect(() => {
    const onEnd = () => goIdle();
    // Não limpar caption no force-speaking (antes startSpeaking("") quebrava a voz)
    const onSpeak = () => {
      const s = useJarvis.getState();
      if (s.state !== "speaking") {
        useJarvis.setState({ state: "speaking", intensity: 1.0, hudPinned: true });
      }
    };
    window.addEventListener("jarvis:tts-end", onEnd);
    window.addEventListener("jarvis:force-speaking", onSpeak);
    return () => {
      window.removeEventListener("jarvis:tts-end", onEnd);
      window.removeEventListener("jarvis:force-speaking", onSpeak);
    };
  }, [goIdle]);

  useEffect(() => {
    // Boot limpo: orb sempre no centro (evita dock preso de sessão anterior)
    const st = useJarvis.getState();
    st.setBrowserActive(false);
    st.setConfirmationPending(false);
    st.setWorking(false);
    window.dispatchEvent(new CustomEvent("jarvis:browser-clear"));
    try {
      void jarvisTTS.unlock?.();
      void fetch(jarvisApi("/api/speak/status"), { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) return;
          jarvisTTS.setVoiceEngine?.(
            "local",
            data.voice_label || "JARVIS Thomas (master.wav)",
            true,
          );
          try {
            localStorage.setItem("jarvis_voice_engine", "local");
            localStorage.setItem(
              "jarvis_voice_label",
              data.voice_label || "JARVIS Thomas (master.wav)",
            );
          } catch {
            /* ignore */
          }
        })
        .catch(() => {
          try {
            jarvisTTS.setVoiceEngine?.("local", "JARVIS Thomas (master.wav)", true);
          } catch {
            /* ignore */
          }
        });
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (isTauri()) {
      try {
        // Navegador nativo ON — tela real no painel. Opt-out: localStorage jarvis_native_browser=0
        if (localStorage.getItem("jarvis_native_browser") == null) {
          localStorage.setItem("jarvis_native_browser", "1");
        }
      } catch {
        /* ignore */
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const boot = async () => {
      try {
        const ready = await waitForJarvisBackend(45000, 1200);
        if (cancelled) return;
        if (!ready) {
          sessionStorage.removeItem("jarvis_boot_done");
          useJarvis
            .getState()
            .setCaption("Backend offline — subindo de novo… (duplo-clique INICIAR-JARVIS.bat se persistir)");
          // Re-tenta em loop leve (backend pode subir após o launcher)
          retryTimer = window.setTimeout(() => {
            if (!cancelled) void boot();
          }, 4000);
          return;
        }
        // Backend voltou — limpa aviso offline
        const cap = useJarvis.getState().caption || "";
        if (/backend offline/i.test(cap)) {
          useJarvis.getState().setCaption("");
        }
        if (sessionStorage.getItem("jarvis_boot_done")) return;
        sessionStorage.setItem("jarvis_boot_done", "1");
        await jarvisTTS.ensureVoiceReady?.();
        if (cancelled) return;
        useJarvis.setState({ state: "speaking", intensity: 0.85 });
        const onBootTtsEnd = () => useJarvis.getState().goIdle();
        window.addEventListener("jarvis:tts-end", onBootTtsEnd, { once: true });
        void jarvisTTS.prefetch?.("Olá, senhor.");
        jarvisTTS.speak("Olá, senhor.");
      } catch {}
    };
    const unlockAndBoot = () => {
      void jarvisTTS.unlock?.();
      void boot();
    };
    const bootTimer = window.setTimeout(unlockAndBoot, 600);
    const onFirstTouch = () => unlockAndBoot();
    window.addEventListener("pointerdown", onFirstTouch, { once: true, capture: true });
    window.addEventListener("keydown", onFirstTouch, { once: true, capture: true });
    return () => {
      cancelled = true;
      window.clearTimeout(bootTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
      window.removeEventListener("pointerdown", onFirstTouch, { capture: true });
      window.removeEventListener("keydown", onFirstTouch, { capture: true });
    };
  }, []);

  useEffect(() => {
    const onTtsError = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const msg = typeof detail === "string" ? detail : "Voz indisponível.";
      useJarvis.getState().setCaption(msg.slice(0, 120));
    };
    window.addEventListener("jarvis:tts-error", onTtsError);
    return () => window.removeEventListener("jarvis:tts-error", onTtsError);
  }, []);

  useEffect(() => {
    const persistSession = () => {
      try {
        fetch("http://127.0.0.1:8000/api/jarvis/session/close", {
          method: "POST",
          keepalive: true,
        }).catch(() => {});
      } catch {
        /* app fechando */
      }
    };
    window.addEventListener("beforeunload", persistSession);

    let unlistenClose: (() => void) | undefined;
    if (isTauri()) {
      void import("@tauri-apps/api/window")
        .then(({ getCurrentWindow }) =>
          getCurrentWindow().onCloseRequested(() => {
            persistSession();
          })
        )
        .then((fn) => {
          unlistenClose = fn;
        })
        .catch(() => {});
    }

    return () => {
      window.removeEventListener("beforeunload", persistSession);
      unlistenClose?.();
    };
  }, []);

  useEffect(() => {
    const toggleFs = () => {
      if (!document.fullscreenElement) void document.documentElement.requestFullscreen();
      else void document.exitFullscreen();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "f" && (e.target as HTMLElement)?.tagName !== "INPUT") {
        toggleFs();
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("jarvis:fullscreen", toggleFs);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("jarvis:fullscreen", toggleFs);
    };
  }, []);

  return (
    <div className="fixed inset-0 w-full h-full overflow-hidden wa-jarvis-bg">
      <WhatsAppJarvisScreen />
    </div>
  );
}