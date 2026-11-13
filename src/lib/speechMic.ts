/**
 * Microfone JARVIS — híbrido:
 * 1) Web Speech API (rápido no Edge/Chrome)
 * 2) MediaRecorder + backend /api/jarvis/stt (confiável se Web Speech falhar)
 */

import { isTauri } from "./nativeBrowser";
import { jarvisFetch } from "./apiBase";

export type SpeechMicCallbacks = {
  onStart?: () => void;
  onEnd?: () => void;
  onInterim?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (message: string, code?: string) => void;
};

export type SpeechMicController = {
  start: () => Promise<void>;
  stop: () => void;
  isActive: () => boolean;
};

const ERROR_PT: Record<string, string> = {
  "not-allowed": "Microfone bloqueado. Permita o acesso ao microfone no navegador (cadeado na barra de endereço).",
  "service-not-allowed": "Microfone bloqueado pelo sistema. Verifique permissões do Windows e do Edge.",
  "no-speech": "Não ouvi nada. Fale de novo, senhor.",
  "audio-capture": "Nenhum microfone detectado. Conecte o microfone e tente outra vez.",
  "network": "Reconhecimento de voz precisa de internet. Verifique a conexão.",
  "aborted": "Escuta interrompida.",
  "not-supported": "Reconhecimento de voz indisponível. Usando modo gravador + backend.",
};

const AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1,
  },
};

function getSR(): (new () => SpeechRecognition) | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: new () => SpeechRecognition;
    webkitSpeechRecognition?: new () => SpeechRecognition;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function isSpeechMicSupported(): boolean {
  return !!getSR() || !!(typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia);
}

export async function requestMicrophonePermission(): Promise<{ ok: boolean; message?: string }> {
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      return { ok: false, message: "Navegador sem suporte a microfone. Use Edge ou Chrome." };
    }
    const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
    stream.getTracks().forEach((t) => t.stop());
    return { ok: true };
  } catch (e: unknown) {
    const name = (e as DOMException)?.name || "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return { ok: false, message: ERROR_PT["not-allowed"] };
    }
    if (name === "NotFoundError") {
      return { ok: false, message: ERROR_PT["audio-capture"] };
    }
    return { ok: false, message: "Não foi possível acessar o microfone." };
  }
}

function stripWakeWord(text: string, wakeWord?: string): string {
  if (!wakeWord) return text.trim();
  const lower = text.toLowerCase();
  const idx = lower.indexOf(wakeWord.toLowerCase());
  if (idx === -1) return "";
  return text.slice(idx + wakeWord.length).replace(/^[\s,.!?]+/, "").trim();
}

function safeStop(rec: SpeechRecognition | null) {
  if (!rec) return;
  try {
    rec.stop();
  } catch {
    /* ignore */
  }
  try {
    rec.abort();
  } catch {
    /* ignore */
  }
}

async function transcribeViaBackend(blob: Blob): Promise<string> {
  if (blob.size < 600) return "";
  const fd = new FormData();
  const ext = blob.type.includes("wav") ? "wav" : "webm";
  fd.append("audio", blob, `chunk.${ext}`);
  try {
    const res = await jarvisFetch("/api/jarvis/stt", { method: "POST", body: fd });
    if (!res.ok) return "";
    const data = (await res.json()) as { text?: string; ok?: boolean };
    return (data.text || "").trim();
  } catch {
    return "";
  }
}

/** Gravador + STT backend — caminho confiável. */
function createRecorderMic(options: {
  callbacks: SpeechMicCallbacks;
}): SpeechMicController {
  let mediaRecorder: MediaRecorder | null = null;
  let micStream: MediaStream | null = null;
  let active = false;
  let wantActive = false;
  let transcribing = false;
  let lastText = "";
  let lastFinalAt = 0;
  let chunks: Blob[] = [];

  const releaseStream = () => {
    micStream?.getTracks().forEach((t) => t.stop());
    micStream = null;
  };

  const fireError = (code: string, fallback?: string) => {
    const msg = ERROR_PT[code] || fallback || "Erro no microfone.";
    options.callbacks.onError?.(msg, code);
  };

  const flushChunks = async () => {
    if (transcribing || !wantActive || chunks.length === 0) return;
    const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
    chunks = [];
    if (blob.size < 800) return;
    transcribing = true;
    try {
      const text = await transcribeViaBackend(blob);
      if (!text) return;
      const now = Date.now();
      if (text === lastText && now - lastFinalAt < 1500) return;
      lastText = text;
      lastFinalAt = now;
      options.callbacks.onInterim?.(text);
      options.callbacks.onFinal?.(text);
    } catch {
      fireError("network");
    } finally {
      transcribing = false;
    }
  };

  return {
    isActive: () => active || wantActive,
    stop: () => {
      wantActive = false;
      active = false;
      try {
        if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
      } catch {
        /* ignore */
      }
      mediaRecorder = null;
      chunks = [];
      releaseStream();
      options.callbacks.onEnd?.();
    },
    start: async () => {
      const perm = await requestMicrophonePermission();
      if (!perm.ok) {
        options.callbacks.onError?.(perm.message || ERROR_PT["not-allowed"], "not-allowed");
        return;
      }
      try {
        releaseStream();
        micStream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
      } catch {
        fireError("audio-capture");
        return;
      }

      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";

      wantActive = true;
      lastText = "";
      lastFinalAt = 0;
      chunks = [];
      try {
        mediaRecorder = mime
          ? new MediaRecorder(micStream!, { mimeType: mime })
          : new MediaRecorder(micStream!);
      } catch {
        fireError("audio-capture");
        wantActive = false;
        releaseStream();
        return;
      }

      mediaRecorder.ondataavailable = (ev) => {
        if (ev.data?.size > 0 && wantActive) {
          chunks.push(ev.data);
          void flushChunks();
        }
      };
      mediaRecorder.onerror = () => fireError("audio-capture");
      mediaRecorder.onstart = () => {
        active = true;
        options.callbacks.onStart?.();
      };
      mediaRecorder.onstop = () => {
        active = false;
        if (wantActive) void flushChunks();
        if (!wantActive) {
          releaseStream();
          options.callbacks.onEnd?.();
        }
      };

      try {
        // chunks a cada 2.2s — melhor para STT backend
        mediaRecorder.start(2200);
      } catch {
        fireError("audio-capture");
        wantActive = false;
        releaseStream();
      }
    },
  };
}

/**
 * Híbrido: Web Speech (rápido) + gravador STT (fallback contínuo).
 * Garante que o mic funcione mesmo se o Web Speech falhar no Edge.
 */
export function createSpeechMic(options: {
  lang?: string;
  continuous?: boolean;
  wakeWord?: string;
  callbacks: SpeechMicCallbacks;
  forceRecorder?: boolean;
}): SpeechMicController {
  if (options.forceRecorder || isTauri()) {
    return createRecorderMic({ callbacks: options.callbacks });
  }

  const SR = getSR();
  if (!SR) {
    return createRecorderMic({ callbacks: options.callbacks });
  }

  // Dual controller state
  let rec: SpeechRecognition | null = null;
  let micStream: MediaStream | null = null;
  let active = false;
  let wantActive = false;
  let restarting = false;
  let restartTimer: ReturnType<typeof setTimeout> | null = null;
  let noSpeechRetries = 0;
  let lastFinalAt = 0;
  let webSpeechBroken = false;
  let recorder: SpeechMicController | null = null;
  let usingRecorder = false;

  const clearRestart = () => {
    if (restartTimer) {
      clearTimeout(restartTimer);
      restartTimer = null;
    }
    restarting = false;
  };

  const releaseStream = () => {
    micStream?.getTracks().forEach((t) => t.stop());
    micStream = null;
  };

  const fireError = (code: string, fallback?: string) => {
    const msg = ERROR_PT[code] || fallback || "Erro no microfone.";
    options.callbacks.onError?.(msg, code);
  };

  const emitFinal = (transcript: string) => {
    let final = stripWakeWord(transcript, options.wakeWord);
    if (options.wakeWord && !final) return;
    if (!options.wakeWord) final = transcript;
    if (!final) return;
    const now = Date.now();
    if (now - lastFinalAt < 700) return;
    lastFinalAt = now;
    options.callbacks.onFinal?.(final);
  };

  const startRecorderFallback = async () => {
    if (usingRecorder && recorder?.isActive()) return;
    usingRecorder = true;
    webSpeechBroken = true;
    safeStop(rec);
    rec = null;
    releaseStream();
    recorder = createRecorderMic({
      callbacks: {
        onStart: () => {
          active = true;
          options.callbacks.onStart?.();
        },
        onEnd: () => {
          active = false;
          if (!wantActive) options.callbacks.onEnd?.();
        },
        onInterim: (t) => options.callbacks.onInterim?.(t),
        onFinal: (t) => emitFinal(t),
        onError: (m, c) => options.callbacks.onError?.(m, c),
      },
    });
    await recorder.start();
  };

  const attach = () => {
    if (!SR || webSpeechBroken) return null;
    const r = new SR();
    r.lang = options.lang || "pt-BR";
    r.interimResults = true;
    r.continuous = options.continuous !== false;
    r.maxAlternatives = 1;

    r.onstart = () => {
      active = true;
      restarting = false;
      noSpeechRetries = 0;
      options.callbacks.onStart?.();
    };

    r.onresult = (ev: SpeechRecognitionEvent) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const result = ev.results[i];
        const transcript = (result[0]?.transcript || "").trim();
        if (!transcript) continue;
        if (result.isFinal) {
          noSpeechRetries = 0;
          emitFinal(transcript);
        } else {
          interim = transcript;
        }
      }
      if (interim) options.callbacks.onInterim?.(interim);
    };

    r.onerror = (ev: SpeechRecognitionErrorEvent) => {
      const code = ev.error || "unknown";
      if (code === "aborted") return;
      if (code === "no-speech") {
        if (wantActive && noSpeechRetries < 20) {
          noSpeechRetries += 1;
          scheduleRestart(400);
          return;
        }
        // Sem fala prolongada — tenta gravador
        if (wantActive) void startRecorderFallback();
        return;
      }
      if (code === "not-allowed" || code === "service-not-allowed") {
        wantActive = false;
        active = false;
        releaseStream();
        fireError(code);
        return;
      }
      // network / not-supported / outros → fallback STT backend
      if (wantActive && (code === "network" || code === "not-allowed" === false)) {
        console.warn("[mic] Web Speech falhou, usando STT backend:", code);
        void startRecorderFallback();
        return;
      }
      if (wantActive) {
        void startRecorderFallback();
        return;
      }
      wantActive = false;
      active = false;
      releaseStream();
      fireError(code);
    };

    r.onend = () => {
      active = false;
      if (wantActive && !webSpeechBroken && !usingRecorder) {
        scheduleRestart(280);
        return;
      }
      if (!wantActive) {
        releaseStream();
        options.callbacks.onEnd?.();
      }
    };

    return r;
  };

  const scheduleRestart = (ms: number) => {
    if (restarting || webSpeechBroken || usingRecorder) return;
    clearRestart();
    restarting = true;
    restartTimer = setTimeout(() => {
      if (!wantActive || webSpeechBroken) {
        restarting = false;
        return;
      }
      safeStop(rec);
      rec = attach();
      if (!rec) {
        void startRecorderFallback();
        restarting = false;
        return;
      }
      try {
        rec.start();
      } catch {
        restarting = false;
        scheduleRestart(500);
      }
    }, ms);
  };

  return {
    isActive: () => active || wantActive || !!recorder?.isActive(),
    stop: () => {
      wantActive = false;
      clearRestart();
      safeStop(rec);
      rec = null;
      active = false;
      recorder?.stop();
      recorder = null;
      usingRecorder = false;
      releaseStream();
    },
    start: async () => {
      const perm = await requestMicrophonePermission();
      if (!perm.ok) {
        options.callbacks.onError?.(perm.message || ERROR_PT["not-allowed"], "not-allowed");
        return;
      }

      // Preferência: híbrido Web Speech + se falhar, gravador
      // No Edge app mode, Web Speech às vezes quebra — se start falhar, cai pro STT
      clearRestart();
      safeStop(rec);
      recorder?.stop();
      recorder = null;
      usingRecorder = false;
      webSpeechBroken = false;
      releaseStream();

      try {
        micStream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
      } catch {
        fireError("audio-capture");
        return;
      }

      wantActive = true;
      noSpeechRetries = 0;
      lastFinalAt = 0;
      rec = attach();
      if (!rec) {
        await startRecorderFallback();
        return;
      }

      await new Promise((r) => setTimeout(r, 100));
      try {
        rec.start();
      } catch {
        await startRecorderFallback();
      }
    },
  };
}
