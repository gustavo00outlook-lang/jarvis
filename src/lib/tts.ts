"use client";

import { jarvisApi, jarvisApiUrls } from "./apiBase";
import { useJarvis } from "./state";

/**
 * JARVIS TTS - Iconic Iron Man Jarvis Voice (calm, sophisticated, authoritative, natural male)
 * + "Jarvis Brasileiro" / Thomas: calm, sophisticated, clear Brazilian Portuguese MALE voice.
 * VOZ OFICIAL: Jarvis Verdadeiro — clone Fish do sample [Voz do Jarvis Verdadeiro]Bom d......0_52. (1).mp3
 * Foco: ignorar voz humana no sample, usar apenas o Thomas.
 * Hybrid: Fish Audio clone Jarvis Verdadeiro (/api/speak/fish) → Edge Antonio Neural → browser Web Speech.
 * Defaults to "Jarvis Mode" (Fish clone preferred, else Edge Antonio, else browser deep male).
 * Prioritizes deep male natural: Microsoft Antonio etc + Thomas hint.
 * Browser limited (no full SSML), premium uses <slow> tags for calm.
 *
 * TTS POLISH: Added debounce + same-text guard in speak(), currentText tracking, and special-cased
 * 'interrupted'/'canceled' (common from cancel() on rapid UI flows like voice selector tests, AÇÃO red bar, DEEP trace).
 * These no longer log as errors (just info). Reduces console noise while preserving all natural PT-BR behavior.
 */

interface TTSOptions {
  language?: string;
  voiceName?: string;
  pitch?: number;
  rate?: number;
  volume?: number;
  // Hybrid Jarvis premium: use xAI backend for high-quality calm tags + custom voice (if XAI_API_KEY on server)
  usePremium?: boolean;
  // For xAI: custom voice_id (e.g. cloned "jarvis-br-male"), speed override, lang en/pt-BR
  voiceId?: string;
  speed?: number;
}

// The iconic JARVIS voice: calm, deep, sophisticated, authoritative natural male (Iron Man style).
// Even slower rate + lower pitch for deep timbre. Brazilian: "Jarvis Brasileiro"; English: classic with en-GB for subtle British.
// Tuned further for less robotic: slower deliberate speech, deeper pitch, strong use of <slow> and [pause] tags.
const JARVIS_FISH_SPEED = 1.05; // sync voice_prefs.py thomas.speed (0701 CapCut WAV fluido)
const JARVIS_XAI_SPEED = 1.0; // sync voice_prefs.py xai.speed

export type JarvisVoiceEngine = "fish" | "edge" | "eleven" | "xai" | "local";

const JARVIS_BR_DEFAULTS = {
  language: 'pt-BR',
  rate: 1.0,      // Presente e fluido — alinhado ao Thomas 0701
  pitch: 0.88,    // Grave calmo sem soar distante
  volume: 1.0,
};

// Unified preferred deep male natural voice hints for Jarvis (pt-BR + en-GB classic British-leaning).
// Priority: Antonio (Natural) for BR, George/David for EN classic Jarvis feel. Neural/Natural/Microsoft bonus.
const MALE_VOICE_HINTS = [
  // pt-BR Brazilian Jarvis
  'microsoft antonio (natural)', 'antonio (natural)', 'microsoft antonio', 'antonio',
  'antônio', 'microsoft antônio',
  'daniel', 'ricardo', 'thiago', 'pedro', 'francisco', 'joao', 'joão',
  'google português do brasil', 'google portugues do brasil',
  'pt-br.*male', 'male.*pt-br', 'homem', 'masculino',
  // en / en-GB for classic JARVIS (slightly British, deep male authoritative like original)
  'microsoft george (natural)', 'george (natural)', 'microsoft george', 'george',
  'microsoft david (natural)', 'david (natural)', 'microsoft david', 'david',
  'microsoft mark', 'mark', 'oliver', 'thomas (focus from sample for JARVIS BR, ignore human voice)', 'thomas jarvis', 'thomas brasileiro', 'james',
  'en-gb.*male', 'male.*en-gb', 'british', 'uk english', 'england', 'en-gb', 'en_gb'
];

class JarvisTTS {
  private synth: SpeechSynthesis | null = null;
  private selectedVoice: SpeechSynthesisVoice | null = null;
  private isInitialized = false;
  private lastSelectedName: string | null = null;
  // Track current text to avoid redundant speaks + for better interrupt logging
  private currentText: string | null = null;
  private lastSpeakTime: number = 0;

  // Hybrid JARVIS MODE: default ON — Fish Jarvis Verdadeiro clone first, Edge Antonio fallback, browser last.
  // Force premium when backend available to avoid robotic browser synth.
  private usePremiumTTS = true;
  private voiceEngine: JarvisVoiceEngine = "local";
  private voiceLabel = "JARVIS Thomas (master.wav)";
  private _fishApiReady: boolean | null = null; // hint de /api/speak/status (não gateia a cadeia)
  private _ttsStatusCache: { data: any; ts: number } | null = null;
  private currentAudio: HTMLAudioElement | null = null;  // for xAI audio playback (blob)
  private _prefetchText: string | null = null;
  private _prefetchBlob: Blob | null = null;
  private _prefetchPromise: Promise<Blob | null> | null = null;
  private _currentTone = "neutro";

  // Porta-voz único: várias janelas JARVIS (app + navegador + painéis) recebem o
  // mesmo broadcast WS — sem eleição, todas falam e a voz sai duplicada.
  private _tabId = Math.random().toString(36).slice(2);
  private static readonly LEADER_KEY = 'jarvis_tts_leader';
  private static readonly LEADER_TTL_MS = 6000;
  private _leaderHeartbeat: ReturnType<typeof setInterval> | null = null;

  private _claimTtsLeadership(force = false): boolean {
    try {
      const now = Date.now();
      const raw = localStorage.getItem(JarvisTTS.LEADER_KEY);
      if (raw) {
        const { id, ts } = JSON.parse(raw) as { id?: string; ts?: number };
        if (id && id !== this._tabId && now - (ts || 0) < JarvisTTS.LEADER_TTL_MS && !force) {
          return false;
        }
      }
      localStorage.setItem(JarvisTTS.LEADER_KEY, JSON.stringify({ id: this._tabId, ts: now }));
      return true;
    } catch {
      return true;
    }
  }

  private _initLeaderElection() {
    if (typeof window === 'undefined') return;
    const takeover = () => { this._claimTtsLeadership(true); };
    window.addEventListener('focus', takeover);
    window.addEventListener('pointerdown', takeover);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) takeover();
    });
    window.addEventListener('beforeunload', () => {
      try {
        const raw = localStorage.getItem(JarvisTTS.LEADER_KEY);
        if (raw && (JSON.parse(raw) as { id?: string }).id === this._tabId) {
          localStorage.removeItem(JarvisTTS.LEADER_KEY);
        }
      } catch { /* ignore */ }
    });
    this._leaderHeartbeat = setInterval(() => {
      try {
        const raw = localStorage.getItem(JarvisTTS.LEADER_KEY);
        const id = raw ? (JSON.parse(raw) as { id?: string }).id : null;
        if (id === this._tabId) {
          localStorage.setItem(
            JarvisTTS.LEADER_KEY,
            JSON.stringify({ id: this._tabId, ts: Date.now() }),
          );
        }
      } catch { /* ignore */ }
    }, 2500);
    if (!document.hidden) takeover();
  }

  // Analisador de amplitude: alimenta useJarvis.audioLevel para o orb reagir à voz real
  private _audioCtx: AudioContext | null = null;
  private _levelRaf = 0;
  private _syntheticTimer: ReturnType<typeof setInterval> | null = null;
  private _bufferSource: AudioBufferSourceNode | null = null;
  private _bufferPlaying = false;
  private _bufferData: AudioBuffer | null = null;
  private _bufferOffset = 0;
  private _bufferStartTime = 0;
  private _bufferPaused = false;
  private _gainNode: GainNode | null = null;
  private _analyser: AnalyserNode | null = null;

  private _startAnalyserLevel(analyser: AnalyserNode) {
    this._stopLevel();
    const data = new Uint8Array(analyser.frequencyBinCount);
    const setLevel = useJarvis.getState().setAudioLevel;
    const tick = () => {
      if (!this._bufferPlaying) {
        setLevel(0);
        return;
      }
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      setLevel(Math.min(1, Math.sqrt(sum / data.length) * 3.2));
      this._levelRaf = requestAnimationFrame(tick);
    };
    this._levelRaf = requestAnimationFrame(tick);
  }

  private _startSyntheticLevel() {
    // Web Speech API não expõe áudio: simula amplitude orgânica enquanto fala
    this._stopLevel();
    const setLevel = useJarvis.getState().setAudioLevel;
    const t0 = Date.now();
    this._syntheticTimer = setInterval(() => {
      const t = (Date.now() - t0) / 1000;
      const v = 0.3 + 0.22 * Math.sin(t * 7.2) + 0.16 * Math.sin(t * 13.7) + Math.random() * 0.1;
      setLevel(Math.max(0.08, Math.min(1, v)));
    }, 50);
  }

  private _stopLevel() {
    if (this._levelRaf) cancelAnimationFrame(this._levelRaf);
    this._levelRaf = 0;
    if (this._syntheticTimer) clearInterval(this._syntheticTimer);
    this._syntheticTimer = null;
    try { useJarvis.getState().setAudioLevel(0); } catch {}
  }

  /**
   * Desbloqueia AudioContext e autoplay de HTMLAudio na primeira interação do usuário.
   * Chame em onClick / onKeyDown antes do primeiro speak().
   */
  public async unlock() {
    if (typeof window === 'undefined') return;
    if (!this._audioCtx) {
      const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (Ctx) this._audioCtx = new Ctx();
    }
    if (this._audioCtx && this._audioCtx.state === 'suspended') {
      await this._audioCtx.resume().catch(() => {});
    }
    // Amostra silenciosa para desbloqueio de autoplay do HTMLAudio
    const a = new Audio();
    a.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
    a.volume = 0;
    try { await a.play(); a.pause(); } catch {}
    window.dispatchEvent(new CustomEvent('jarvis:audio-unlocked'));
  }

  constructor() {
    // Only initialize on client side
    if (typeof window !== 'undefined') {
      this.synth = window.speechSynthesis;
      // Restore persisted preference for consistent "Jarvis Brasileiro" across reloads
      try {
        this.lastSelectedName = localStorage.getItem('jarvis_br_voice_name');
        if (this.lastSelectedName && this._isFemaleVoiceName(this.lastSelectedName)) {
          this.lastSelectedName = null;
          localStorage.removeItem('jarvis_br_voice_name');
        }
        const mode = localStorage.getItem('jarvis_jarvis_mode');
        if (mode !== null) {
          this.usePremiumTTS = mode === '1';
        } else {
          this.usePremiumTTS = true;
          localStorage.setItem('jarvis_jarvis_mode', '1');
        }
        this.voiceEngine = 'local';
        try {
          localStorage.setItem('jarvis_voice_engine', 'local');
          localStorage.setItem('jarvis_voice_label', 'JARVIS Thomas (master.wav)');
        } catch { /* ignore */ }
        this.voiceLabel = 'JARVIS Thomas (master.wav)';
      } catch {}
      this.initializeVoices();
      this._initLeaderElection();
      void this._refreshTtsStatus(true);
    }
  }

  private _isFemaleVoiceName(name: string): boolean {
    return /zira|maria|francisca|helena|heloisa|heloísa|luciana|leticia|letícia|camila|female|mulher|woman|fem\b|eve\b|google português do brasil/i.test(name || '');
  }

  private initializeVoices() {
    if (!this.synth || typeof window === 'undefined') return;

    const isFemale = (name: string) => this._isFemaleVoiceName(name);
    const isMale = (name: string) =>
      /antonio|antônio|daniel|ricardo|thiago|pedro|fabio|fábio|male|masculino|homem|george|david|mark|guy|ryan|james|oliver|thomas/i.test(name || '');

    const loadVoices = () => {
      const voices = this.synth!.getVoices();
      if (voices.length === 0) return;

      let chosen: SpeechSynthesisVoice | null = null;

      const ptBR = voices.filter(v => v.lang.toLowerCase().includes('pt-br') || v.lang === 'pt_BR');
      const ptAny = voices.filter(v => v.lang.toLowerCase().startsWith('pt'));

      // 1. Voz MASCULINA pt-BR (ideal: Antonio)
      chosen = this.pickBestMaleBRVoice(ptBR) || ptBR.find(v => isMale(v.name)) || ptAny.find(v => isMale(v.name)) || null;

      // 2. Sem masculina pt: prefere QUALQUER voz masculina (en) a uma feminina pt-BR
      if (!chosen) {
        chosen = voices.find(v => isMale(v.name) && /en/i.test(v.lang)) || voices.find(v => isMale(v.name)) || null;
      }

      // 3. Último recurso: pt-BR não-feminina, senão qualquer não-feminina, senão o que houver
      if (!chosen) {
        chosen = ptBR.find(v => !isFemale(v.name)) || voices.find(v => !isFemale(v.name)) || voices[0];
      }

      // Preferência salva só vale se NÃO for feminina (evita travar numa Maria escolhida sem querer)
      if (this.lastSelectedName) {
        const persisted = voices.find(v => v.name === this.lastSelectedName);
        if (persisted && !isFemale(persisted.name)) chosen = persisted;
      }

      console.log('✅ TTS: Voz do navegador (fallback):', chosen?.name, chosen?.lang, isFemale(chosen?.name || '') ? '⚠️FEM' : '♂');

      {
        this.selectedVoice = chosen;
        this.isInitialized = true;

        // Persist the effective choice for future sessions
        if (this.selectedVoice) {
          try { localStorage.setItem('jarvis_br_voice_name', this.selectedVoice.name); } catch {}
        }
      }
    };

    // Carregar vozes (alguns navegadores carregam async)
    loadVoices();
    this.synth.onvoiceschanged = loadVoices;
  }

  private pickBestMaleBRVoice(ptBRVoices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
    // Score voices: higher score = better match for calm sophisticated male BR Jarvis + classic en Jarvis
    let best: SpeechSynthesisVoice | null = null;
    let bestScore = -1;

    for (const v of ptBRVoices) {
      const nameLower = (v.name || '').toLowerCase();
      // JARVIS é masculino: vozes femininas são descartadas de imediato
      if (/zira|maria|francisca|helena|heloisa|heloísa|luciana|leticia|letícia|camila|female|mulher|woman/i.test(v.name)) continue;
      let score = 0;

      // Strong preference for known good natural male voices (BR + EN classic Jarvis)
      MALE_VOICE_HINTS.forEach((hint, idx) => {
        if (nameLower.includes(hint)) {
          score += 100 - idx * 5; // earlier hints higher
        }
      });

      // Gender / "male" / "masculino" explicit bonus
      if (/male|masculino|homem|man\b/i.test(v.name)) score += 80;
      // Demote obvious female defaults (Zira, Francisca if not wanted, Helena etc)
      if (/zira|francisca|helena|female|mulher|woman/i.test(v.name)) score -= 60;

      // Bonus for "neural", "natural", "desktop" (often better quality)
      if (/neural|natural|desktop|microsoft/i.test(v.name)) score += 25;

      // Slight preference for "Google" voices when high quality PT available in browser
      if (/google.*brasil|google.*português/i.test(v.name)) score += 40;
      // Bonus for British/en-GB for classic Jarvis accent
      if (/british|en-gb|uk|george|david/i.test(v.name)) score += 35;

      if (score > bestScore) {
        bestScore = score;
        best = v;
      }
    }

    // If no strong male match, still return first ptBR (caller will use lower pitch)
    return best;
  }

  /**
   * Listar todas as vozes disponíveis
   */
  public getAvailableVoices() {
    if (!this.synth || typeof window === 'undefined') return [];
    return this.synth.getVoices().map(v => ({
      name: v.name,
      lang: v.lang,
      isDefault: v.default,
    }));
  }

  /**
   * Enhance text for the iconic JARVIS delivery using xAI speech tags (calm, deliberate, authoritative).
   * Used by premium path. Browser path relies on rate/pitch only (Web Speech API limitation; no native SSML).
   */
  private enhanceForJarvis(text: string): string {
    const t = (text || '').trim();
    if (!t) return t;
    // If user or caller already provided tags, respect it
    if (/<(slow|soft|whisper|emphasis)>|\[pause\]|\[long-pause\]/i.test(t)) {
      return t;
    }
    // Fluido: sem tags <slow> — ritmo natural como o sample Jarvis Verdadeiro
    return t;
  }

  /**
   * Premium path: PRIORIDADE Thomas JARVIS Brasileiro do voice_sample.mp3 via ElevenLabs clone
   * (usa ELEVENLABS_VOICE_ID do .env que aponta para o Thomas clonado do sample; ignore human voice).
   * Fallback para xAI TTS ou browser Web Speech se rota indisponível.
   * Usa tags <slow> no backend para prosodia calma.
   */
  private async speakPremium(text: string, options: TTSOptions = {}) {
    if (typeof window === 'undefined' || !text.trim()) return;

    const trimmed = text.trim();
    const now = Date.now();
    if (now - this.lastSpeakTime < 10) {
      console.log('🔊 TTS (Thomas JARVIS BR): debounce skip');
      return;
    }
    if (this.isSpeaking() && this.currentText === trimmed) {
      console.log('🔊 TTS (Thomas JARVIS BR): already speaking identical text, skipping');
      return;
    }
    this.lastSpeakTime = now;
    this.currentText = trimmed;

    if (this.isSpeaking()) {
      this.stop();
      await new Promise((r) => setTimeout(r, 28));
    } else {
      this.stop();
    }

    console.log('🎙️ TTS (Thomas XTTS master.wav):', trimmed.substring(0, 60) + '...');

    if (typeof window !== 'undefined') {
      (window as any).__jarvis_tts_external = true;
      (window as any).__jarvis_tts_playing = true;
    }

    // Só clone local XTTS (master.wav). Nunca Antonio/Edge/browser.
    try {
      await this._tryPremiumChain(text, options);
    } catch {
      if (typeof window !== 'undefined') {
        (window as any).__jarvis_tts_external = false;
        (window as any).__jarvis_tts_playing = false;
      }
    }
  }

  private _clearTtsExternalFlags() {
    if (typeof window === 'undefined') return;
    (window as any).__jarvis_tts_external = false;
    (window as any).__jarvis_tts_playing = false;
  }

  /** Volume confortavel — 0.62 equilibra estilo do sample sem estourar. */
  private static readonly PLAYBACK_VOLUME = 0.92;

  /** Garante um único stream: para qualquer fala anterior (anti-eco). */
  private _interruptPlayback() {
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
        this.currentAudio.src = '';
      } catch { /* ignore */ }
      this.currentAudio = null;
    }
    this._stopBufferPlayback();
    if (this.synth?.speaking) {
      try { this.synth.cancel(); } catch { /* ignore */ }
    }
  }

  private _stopBufferPlayback() {
    const src = this._bufferSource;
    // Nulado ANTES do stop(): o onended do source vê que não é mais o ativo e não dispara tts-end
    this._bufferSource = null;
    this._bufferPlaying = false;
    this._bufferPaused = false;
    this._bufferData = null;
    this._bufferOffset = 0;
    if (src) {
      try { src.stop(); } catch { /* ignore */ }
    }
  }

  private _startBufferSource(ctx: AudioContext, offset: number) {
    const source = ctx.createBufferSource();
    source.buffer = this._bufferData;
    source.connect(this._gainNode!);
    source.onended = () => {
      if (this._bufferSource !== source) return;
      this._bufferSource = null;
      this._bufferPlaying = false;
      this._bufferData = null;
      this._bufferOffset = 0;
      this.currentText = null;
      this._stopLevel();
      this._clearTtsExternalFlags();
      window.dispatchEvent(new CustomEvent('jarvis:tts-end'));
    };
    this._bufferSource = source;
    this._bufferPlaying = true;
    this._bufferStartTime = ctx.currentTime;
    source.start(0, offset);
  }

  /**
   * WebAudio puro: decode → BufferSource → Gain (anti-estouro) → Analyser → destino.
   * Uma única saída de áudio; RMS real do analyser alimenta o orb (sem MediaElementSource = sem eco).
   */
  private async _playWebAudio(blob: Blob, label: string): Promise<boolean> {
    let ctx = this._audioCtx;
    if (!ctx) {
      const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (Ctx) ctx = this._audioCtx = new Ctx();
    }
    if (!ctx) return false;
    if (ctx.state === 'suspended') {
      try { await ctx.resume(); } catch { /* ignore */ }
    }
    if (ctx.state !== 'running') return false;
    let buffer: AudioBuffer;
    try {
      buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
    } catch {
      return false;
    }
    this._interruptPlayback();
    if (!this._gainNode || !this._analyser) {
      this._gainNode = ctx.createGain();
      this._analyser = ctx.createAnalyser();
      this._analyser.fftSize = 512;
      this._gainNode.connect(this._analyser);
      this._analyser.connect(ctx.destination);
    }
    this._gainNode.gain.value = JarvisTTS.PLAYBACK_VOLUME;
    this._bufferData = buffer;
    this._bufferOffset = 0;
    this._bufferPaused = false;
    this._startBufferSource(ctx, 0);
    (window as any).__jarvis_tts_external = true;
    (window as any).__jarvis_tts_playing = true;
    this._startAnalyserLevel(this._analyser);
    window.dispatchEvent(new CustomEvent('jarvis:tts-start'));
    window.dispatchEvent(new CustomEvent('jarvis:force-speaking'));
    console.log(`🔊 TTS (${label}): WebAudio gain=${JarvisTTS.PLAYBACK_VOLUME} + analyser (orb na voz real)`);
    return true;
  }

  /** Playback unificado: WebAudio (orb dança com a voz) → fallback HTMLAudio + nível sintético. */
  private async _playAudio(blob: Blob, label: string): Promise<boolean> {
    if (await this._playWebAudio(blob, label)) return true;
    return this._playHtmlAudio(blob, label);
  }

  private async _playHtmlAudio(blob: Blob, label: string): Promise<boolean> {
    try {
      this._interruptPlayback();

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.preload = 'auto';
      // Anti-estouro: nunca 1.0 (picos Eleven + DAC = clip/distorção)
      audio.volume = JarvisTTS.PLAYBACK_VOLUME;
      // Reprodução seca — SEM Web Audio MediaElementSource (evita eco/duplicação)
      this.currentAudio = audio;
      this._bufferPlaying = true;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (this.currentAudio === audio) this.currentAudio = null;
        this._bufferPlaying = false;
        this.currentText = null;
        this._stopLevel();
        this._clearTtsExternalFlags();
        window.dispatchEvent(new CustomEvent('jarvis:tts-end'));
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        if (this.currentAudio === audio) this.currentAudio = null;
        this._bufferPlaying = false;
        this._clearTtsExternalFlags();
        window.dispatchEvent(new CustomEvent('jarvis:tts-end'));
      };
      audio.onplay = () => {
        if (typeof window !== 'undefined') {
          (window as any).__jarvis_tts_external = true;
          (window as any).__jarvis_tts_playing = true;
        }
        this._startSyntheticLevel();
        window.dispatchEvent(new CustomEvent('jarvis:tts-start'));
        window.dispatchEvent(new CustomEvent('jarvis:force-speaking'));
      };
      console.log(`🔊 TTS (${label}): HTMLAudio vol=${JarvisTTS.PLAYBACK_VOLUME} (anti-estouro)...`);
      await audio.play();
      return true;
    } catch (err: any) {
      console.warn(`⚠️ TTS (${label}): HTMLAudio falhou —`, err?.name ?? err);
      this.currentAudio = null;
      this._bufferPlaying = false;
      return false;
    }
  }

  /** Aguarda backend confirmar engine TTS antes do primeiro speak (evita Fish sem clone). */
  public async ensureVoiceReady(): Promise<void> {
    await this._refreshTtsStatus(true);
  }

  private async _refreshTtsStatus(force = false) {
    
    // Cache TTS status for 30 seconds to avoid repeated fetches
    const now = Date.now();
    if (!force && this._ttsStatusCache && now - this._ttsStatusCache.ts < 30000) {
      const data = this._ttsStatusCache.data;
      this._fishApiReady = !!data.fish_api_ready;
      return;
    }

    try {
      let res: Response | null = null;
      for (const url of jarvisApiUrls('/api/speak/status')) {
        try {
          const r = await fetch(url, { cache: 'no-store' });
          if (r.ok) { res = r; break; }
        } catch { /* fallback */ }
      }
      if (!res) throw new Error('speak/status unreachable');
      if (res.ok) {
        const data = await res.json();
        this._ttsStatusCache = { data, ts: now };
        this._fishApiReady = !!data.fish_api_ready;
        const fishOk = !!data.fish_api_ready && !!data.fish_voice_connected;
        const localOk = !!(data.local || data.local_clone);
        const raw = String((data.voice_engine as string) || 'local').toLowerCase();
        // Canônico: clone local master.wav. Nunca Antonio/Edge.
        let eng: JarvisVoiceEngine = 'local';
        if (raw === 'eleven' || raw === 'elevenlabs') eng = 'eleven';
        else if (raw === 'xai' || raw === 'grok') eng = 'xai';
        else if (raw === 'fish' && fishOk) eng = 'fish';
        else eng = 'local';
        this.setVoiceEngine(eng, data.voice_label || 'JARVIS Thomas (master.wav)', true);
        console.log(
          '🎙️ TTS status:',
          `${this.voiceLabel} | local=${localOk} eleven=${!!data.eleven} fish=${!!data.fish_api_ready}`,
        );
      } else {
        this._fishApiReady = false;
        console.warn('🎙️ TTS status HTTP', res.status);
      }
    } catch (e) {
      this._fishApiReady = false;
      console.warn('🎙️ TTS status falhou:', e);
    }
  }

  private async _tryPremiumChain(text: string, options: TTSOptions = {}) {
    const trimmed = text.trim();
    void this._refreshTtsStatus(false);

    const local = {
      route: jarvisApi('/api/speak/local'),
      body: { text: trimmed, prefer: 'xtts', voice_id: 'thomas-0701', play_system: true },
      label: 'JARVIS Thomas (master.wav)',
      timeout: 180000,
    };
    const chain: Array<{ route: string; body?: object; label: string; timeout: number }> = [local];

    // Prefetch hit check (unchanged)
    if (this._prefetchText === trimmed) {
      let blob = this._prefetchBlob;
      if ((!blob || blob.size < 100) && this._prefetchPromise) {
        blob = await this._prefetchPromise;
      }
      if (blob && blob.size >= 100) {
        this._prefetchBlob = null;
        this._prefetchText = null;
        this._prefetchPromise = null;
        const hitLabel = local.label;
        console.log(`✅ TTS prefetch hit (${blob.size} bytes)`);
        const played = await this._playAudio(blob, hitLabel);
        if (played) return;
      }
    }

    // PARALLEL fallback: fire all requests simultaneously, use first successful
    const speakPath = (step: typeof chain[0]) => step.route.match(/\/api\/speak\/[a-z0-9_-]+/i)?.[0];
    
    const fetchWithTimeout = async (step: typeof chain[0]) => {
      const routes = speakPath(step) ? jarvisApiUrls(speakPath(step)!) : [step.route];
      for (const route of routes) {
        try {
          const ctrl = new AbortController();
          const timer = setTimeout(() => ctrl.abort(), step.timeout);
          const res = await fetch(route, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(step.body),
            signal: ctrl.signal,
          });
          clearTimeout(timer);
          if (!res.ok) continue;
          const engine = res.headers.get('x-tts-engine') || step.label;
          const blob = await res.blob();
          if (blob.size < 100) continue;
          return { step, engine, blob, label: step.label };
        } catch {
          continue;
        }
      }
      return null;
    };

    console.log(`🔊 TTS parallel: firing ${chain.length} engines simultaneously...`);
    const results = await Promise.allSettled(chain.map(fetchWithTimeout));
    
    // Return first successful result in chain order
    for (const result of results) {
      if (result.status === 'fulfilled' && result.value) {
        const { step, engine, blob, label } = result.value;
        console.log(`✅ TTS engine: ${engine} (${blob.size} bytes) — FIRST WINNER`);
        const played = await this._playAudio(blob, label);
        if (played) return;
      }
    }

    // No engine succeeded
    console.warn('⚠️ TTS: all engines failed');
  }

  /** Dispara TTS Fish em background para reduzir latência no speak() seguinte. */
  public prefetch(text: string) {
    if (typeof window === 'undefined' || !text.trim()) return;
    const trimmed = text.trim();
    if (this._prefetchText === trimmed && (this._prefetchBlob || this._prefetchPromise)) return;
    this._prefetchText = trimmed;
    this._prefetchBlob = null;
    const route = jarvisApi('/api/speak/local');
    const body = { text: trimmed, prefer: 'xtts', voice_id: 'thomas-0701', play_system: false };
    const prefetchTimeout = 180000;
    this._prefetchPromise = (async () => {
      try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), prefetchTimeout);
        const res = await fetch(route, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: ctrl.signal,
        });
        clearTimeout(timer);
        if (!res.ok) return null;
        const blob = await res.blob();
        if (blob.size < 100) return null;
        if (this._prefetchText === trimmed) {
          this._prefetchBlob = blob;
        }
        return blob;
      } catch {
        return null;
      }
    })();
  }

  /** Cumprimento com o clone Thomas (master.wav) — nunca o sample MP3. */
  public async playSampleGreeting() {
    this.speak('Olá, senhor.');
  }

  /**
   * Internal browser speak (extracted for hybrid fallback + reuse). Applies deep Jarvis tuning.
   */
  private _speakBrowser(text: string, options: TTSOptions = {}) {
    if (!this.synth || !text.trim() || typeof window === 'undefined') return;

    const trimmed = text.trim();

    // debounce/guard already handled in callers; here for direct fallback
    const now = Date.now();
    if (now - this.lastSpeakTime < 30) return; // light
    this.lastSpeakTime = now;
    this.currentText = trimmed;

    this.stop();

    const utterance = new SpeechSynthesisUtterance(text);

    // Smart lang: pt-BR default, but en-GB for classic Jarvis British sophisticated feel when English
    let lang = options.language || JARVIS_BR_DEFAULTS.language;
    const lowerText = trimmed.toLowerCase();
    const looksEnglish = /^[a-z0-9\s.,!?;:'"()-]+$/i.test(trimmed) && !/[áàâãéèêíïóôõöúçãõ]/i.test(trimmed) && !lowerText.includes('senhor') && !lowerText.includes('sistema');
    if (looksEnglish || (lang && lang.startsWith('en'))) {
      lang = 'en-GB';  // subtle British for iconic JARVIS (better than US for "sir", calm authority)
    }
    utterance.lang = lang;

    if (this.selectedVoice) {
      utterance.voice = this.selectedVoice;
    }

    utterance.pitch = options.pitch ?? JARVIS_BR_DEFAULTS.pitch;
    utterance.rate = options.rate ?? JARVIS_BR_DEFAULTS.rate;
    utterance.volume = options.volume ?? JARVIS_BR_DEFAULTS.volume;

    utterance.onstart = () => {
      console.log('🔊 TTS (Jarvis deep browser): Iniciando fala (calm deep male)... lang=', lang);
      this._startSyntheticLevel();
      window.dispatchEvent(new CustomEvent('jarvis:tts-start'));
      window.dispatchEvent(new CustomEvent('jarvis:force-speaking'));
    };

    utterance.onend = () => {
      console.log('🔊 TTS (Jarvis deep browser): Fala concluída');
      this.currentText = null;
      this._stopLevel();
      this._clearTtsExternalFlags();
      window.dispatchEvent(new CustomEvent('jarvis:tts-end'));
    };

    utterance.onerror = (event) => {
      const err = event.error;
      this.currentText = null;
      this._stopLevel();
      if (err === 'interrupted' || err === 'canceled') {
        console.log(`🔊 TTS (Jarvis deep browser): fala interrompida (esperado): ${err}`);
        window.dispatchEvent(new CustomEvent('jarvis:tts-interrupted', { detail: err }));
        return;
      }
      console.error('❌ TTS (Jarvis deep browser) Error:', err);
      window.dispatchEvent(new CustomEvent('jarvis:tts-error', { detail: err }));
    };

    this.synth.speak(utterance);
  }

  /**
   * Falar texto — JARVIS voice (hybrid).
   * If JARVIS MODE (default) or options.usePremium, tries Fish Jarvis Verdadeiro clone first, then Edge Antonio, then browser.
   * Always uses deep male tuned params (rate ~0.87, pitch 0.85). Preserves PT-BR preference + adds EN classic support.
   */
  public speak(text: string, options: TTSOptions = {}) {
    if (!text.trim() || typeof window === 'undefined') return;

    this._claimTtsLeadership(true);

    this.speakPremium(text, options).catch((e) => {
      console.warn('TTS local falhou (sem Antonio):', e);
    });
  }

  /**
   * Selecionar voz específica (chamado pelo VoiceSelector).
   * Persiste a escolha para sessões futuras como "voz do Jarvis".
   */
  public selectVoice(voiceName: string) {
    if (!this.synth || typeof window === 'undefined') return;
    const voices = this.synth.getVoices();
    const match = voices.find(v => v.name === voiceName);
    if (match) {
      this.selectedVoice = match;
      this.lastSelectedName = match.name;
      try { localStorage.setItem('jarvis_br_voice_name', match.name); } catch {}
      console.log('🎤 TTS: Voz Jarvis selecionada manualmente:', match.name, match.lang);
    }
  }

  /**
   * JARVIS MODE toggle: forces Fish Jarvis Verdadeiro clone path for iconic Iron Man voice.
   * "Yes, sir." / "At your service." now delivered calm, authoritative, sophisticated.
   */
  public setJarvisMode(enabled: boolean) {
    this.usePremiumTTS = !!enabled;
    try { localStorage.setItem('jarvis_jarvis_mode', enabled ? '1' : '0'); } catch {}
    console.log('🎩 JARVIS MODE:', enabled ? 'ON — Jarvis Verdadeiro (Fish clone → Edge → browser)' : 'OFF (standard browser)');
  }

  public getJarvisMode(): boolean {
    return this.usePremiumTTS;
  }

  /** Tom emocional do turno (humor, pegadinha…) — backend aplica risada na fala */
  public setTone(tone: string) {
    this._currentTone = (tone || "neutro").trim() || "neutro";
  }

  private _fishBody(text: string, speed: number) {
    return {
      text,
      play_system: false,
      speed,
      tone: this._currentTone,
    };
  }

  /** Voz ativa: fish=Thomas | edge=Antonio — persiste até novo pedido */
  public setVoiceEngine(engine: JarvisVoiceEngine | string, label?: string, persist = true) {
    const next: JarvisVoiceEngine = "local";
    void engine;
    this.voiceEngine = next;
    this.voiceLabel = label || "JARVIS Thomas (master.wav)";
    if (persist) {
      try {
        localStorage.setItem("jarvis_voice_engine", next);
        localStorage.setItem("jarvis_voice_label", this.voiceLabel);
      } catch {}
    }
    console.log("🎙️ Voz JARVIS:", this.voiceLabel, `(${next})`);
    window.dispatchEvent(
      new CustomEvent("jarvis:voice-changed", {
        detail: { engine: next, label: this.voiceLabel },
      })
    );
  }

  public getVoiceEngine(): JarvisVoiceEngine {
    return this.voiceEngine;
  }

  public getVoiceLabel(): string {
    return this.voiceLabel;
  }

  /**
   * Retorna a voz atualmente ativa (para UI/debug)
   */
  public getCurrentVoice() {
    return this.selectedVoice ? { name: this.selectedVoice.name, lang: this.selectedVoice.lang } : null;
  }

  /**
   * Parar fala atual (browser + premium audio)
   */
  public stop() {
    if (typeof window === 'undefined') return;
    if (this.synth && this.synth.speaking) {
      this.synth.cancel();
    }
    this._stopBufferPlayback();
    if (this.currentAudio) {
      try { this.currentAudio.pause(); this.currentAudio.currentTime = 0; } catch {}
      this.currentAudio = null;
    }
    this._stopLevel();
    this.currentText = null;
    this._clearTtsExternalFlags();
  }

  /**
   * Verificar se está falando (hybrid aware)
   */
  public isSpeaking() {
    if (typeof window === 'undefined') return false;
    const browserSpeaking = !!(this.synth && this.synth.speaking);
    const audioSpeaking = this._bufferPlaying || !!(this.currentAudio && !this.currentAudio.paused && !this.currentAudio.ended);
    return browserSpeaking || audioSpeaking;
  }

  /**
   * Parar e limpar (hybrid)
   */
  public pause() {
    if (typeof window === 'undefined') return;
    if (this.synth && this.synth.speaking) {
      this.synth.pause();
    }
    // WHY: AudioBufferSourceNode não pausa nativamente — guarda o offset decorrido
    // e resume() recria o source a partir dele (mantém uma única saída de áudio).
    if (this._bufferSource && this._audioCtx) {
      this._bufferOffset += this._audioCtx.currentTime - this._bufferStartTime;
      const src = this._bufferSource;
      this._bufferSource = null;
      this._bufferPlaying = false;
      this._bufferPaused = true;
      try { src.stop(); } catch { /* ignore */ }
      this._stopLevel();
    }
    if (this.currentAudio) {
      try { this.currentAudio.pause(); } catch {}
    }
  }

  /**
   * Retomar fala pausada (hybrid)
   */
  public resume() {
    if (typeof window === 'undefined') return;
    if (this.synth && this.synth.paused) {
      this.synth.resume();
    }
    if (this._bufferPaused && this._bufferData && this._audioCtx && this._gainNode && this._analyser) {
      this._bufferPaused = false;
      this._startBufferSource(this._audioCtx, Math.min(this._bufferOffset, this._bufferData.duration));
      this._startAnalyserLevel(this._analyser);
    }
    if (this.currentAudio && this.currentAudio.paused) {
      this.currentAudio.play().catch(() => {});
    }
  }
}

// Criar instância apenas no cliente (SSR-safe)
const jarvisTTS = typeof window !== 'undefined' ? new JarvisTTS() : ({} as JarvisTTS);

// Fazer disponível globalmente para debug/console (window.jarvisTTS.speak(...) etc)
if (typeof window !== 'undefined') {
  (window as any).jarvisTTS = jarvisTTS;
  // Also expose the class for advanced use
  (window as any).JarvisTTS = JarvisTTS;
}

export { jarvisTTS, JARVIS_BR_DEFAULTS };
export default JarvisTTS;

