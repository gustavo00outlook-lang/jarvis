"use client";

import { useEffect, useRef } from "react";
import { useJarvis } from "@/lib/state";
import {
  drawCinematicAmbientSpill,
  drawGrayRiscos,
  drawHuwScannerArcs,
  drawHuwWhiteScribbles,
  drawWhiteTickDotRing,
  RING_SCANNER,
} from "./orbScannerHuw";
import { drawJarvisOrbLabel } from "./jarvisOrbLabel";

/** rate equivalente a um lerp k-por-frame calibrado em 60fps */
const rateFromFrameK = (k: number): number => -Math.log(1 - k) * 60;

const RATE_ATTACK_SPEAKING = rateFromFrameK(0.42);
const RATE_ATTACK_RISE = rateFromFrameK(0.32);
const RATE_RELEASE = rateFromFrameK(0.14);
const RATE_COLOR_FAST = rateFromFrameK(0.2);
const RATE_COLOR = rateFromFrameK(0.14);
const RATE_STATE = 6;
const AUDIO_ATTACK_RATE = 1 / 0.06;
const AUDIO_RELEASE_RATE = 1 / 0.2;
const MAX_DT = 0.05;

const MOOD_PAL: Record<string, [number, number, number]> = {
  happy: [72, 210, 168],
  playful: [110, 200, 255],
  warm: [255, 170, 110],
  alert: [255, 120, 80],
  focused: [90, 150, 220],
  calm: [48, 128, 188],
};

const PAL_CONFIRM: [number, number, number] = [255, 70, 70];
const PAL_RESEARCH: [number, number, number] = [255, 195, 55];
const PAL_LISTEN: [number, number, number] = [52, 148, 168];

const TINT_CONFIRM = { r: 220, g: 100, b: 100 };
const TINT_RESEARCH = { r: 255, g: 195, b: 55 };
const TINT_IDLE = { r: 48, g: 128, b: 188 };

/**
 * Orb idle — escuro estilo @huwprosser: ciano contido, anéis brancos, ticks, pontos.
 * Resize via ResizeObserver (não por frame — evita flicker).
 * Suavização independente de refresh rate: fator = 1 - exp(-rate * dt).
 */
export function OrbWhatsAppCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d", { desynchronized: true, alpha: true });
    if (!ctx) return;

    let raf = 0;
    let running = true;
    const col = { r: 48, g: 128, b: 188 };
    let amp = 0.05;
    let audioEnv = 0;
    let baseEnv = 0.05;
    let pulseAmpEnv = 0;
    let pulseFreqEnv = 4.0;
    let pulsePhase = 0;
    let breatheAmpEnv = 0.005;
    let breatheFreqEnv = 1.15;
    let breathePhase = 0;
    let ampRadiusEnv = 0.006;
    let lastTs = -1;
    let W = 1;
    let H = 1;

    const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
    const rgba = (r: number, g: number, b: number, a: number) =>
      `rgba(${r | 0},${g | 0},${b | 0},${a})`;

    const applySize = () => {
      const dpr = Math.min(2.5, window.devicePixelRatio || 1);
      const rect = wrap.getBoundingClientRect();
      const nextW = Math.max(1, rect.width);
      const nextH = Math.max(1, rect.height);
      if (nextW === W && nextH === H && canvas.width === Math.floor(nextW * dpr)) {
        return;
      }
      W = nextW;
      H = nextH;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const ro = new ResizeObserver(() => applySize());
    ro.observe(wrap);
    applySize();

    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else if (running && !raf) {
        lastTs = -1;
        raf = requestAnimationFrame(draw);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    const draw = (nowMs: number) => {
      if (!running || document.hidden) return;
      const t = nowMs / 1000;
      const dt = lastTs < 0 ? 1 / 60 : Math.min(MAX_DT, Math.max(0, (nowMs - lastTs) / 1000));
      lastTs = nowMs;
      const { state, confirmationPending, audioLevel, working, browserActive, mood } = useJarvis.getState();
      const isResearching = working || browserActive || state === "thinking";

      const pal: [number, number, number] = confirmationPending
        ? PAL_CONFIRM
        : isResearching
          ? PAL_RESEARCH
          : state === "listening"
            ? PAL_LISTEN
            : MOOD_PAL[mood] || MOOD_PAL.calm;

      const kState = 1 - Math.exp(-RATE_STATE * dt);

      const baseTarget =
        state === "speaking" ? 0.38 :
        state === "listening" ? 0.24 :
        isResearching ? 0.34 : 0.05;
      baseEnv += (baseTarget - baseEnv) * kState;

      const pulseAmpTarget = state === "speaking" ? 0.06 : state === "listening" ? 0.04 : 0;
      const pulseFreqTarget = state === "speaking" ? 6.2 : 4.0;
      pulseAmpEnv += (pulseAmpTarget - pulseAmpEnv) * kState;
      pulseFreqEnv += (pulseFreqTarget - pulseFreqEnv) * kState;
      pulsePhase += pulseFreqEnv * dt;
      const pulse = pulseAmpEnv * (0.5 + 0.5 * Math.sin(pulsePhase));

      const rawAudio = audioLevel || 0;
      const audioRate = rawAudio > audioEnv ? AUDIO_ATTACK_RATE : AUDIO_RELEASE_RATE;
      audioEnv += (rawAudio - audioEnv) * (1 - Math.exp(-audioRate * dt));

      const target = Math.min(1, baseEnv + pulse + audioEnv * 0.72);
      const ampRate =
        state === "speaking" ? RATE_ATTACK_SPEAKING : target > amp ? RATE_ATTACK_RISE : RATE_RELEASE;
      amp += (target - amp) * (1 - Math.exp(-ampRate * dt));

      const kColor = 1 - Math.exp(-(isResearching || state === "speaking" ? RATE_COLOR_FAST : RATE_COLOR) * dt);
      col.r = lerp(col.r, pal[0], kColor);
      col.g = lerp(col.g, pal[1], kColor);
      col.b = lerp(col.b, pal[2], kColor);

      const cx = W / 2;
      const cy = H / 2;
      const dim = Math.min(W, H);
      const breatheFreqTarget = state === "speaking" ? 2.4 : state === "listening" ? 1.6 : 1.15;
      const breatheAmpTarget = state === "speaking" ? 0.009 : 0.005;
      breatheFreqEnv += (breatheFreqTarget - breatheFreqEnv) * kState;
      breatheAmpEnv += (breatheAmpTarget - breatheAmpEnv) * kState;
      breathePhase += breatheFreqEnv * dt;
      const breathe = Math.sin(breathePhase) * breatheAmpEnv;
      const ampRadiusTarget = state === "speaking" ? 0.011 : 0.006;
      ampRadiusEnv += (ampRadiusTarget - ampRadiusEnv) * kState;
      const RStable = dim * 0.34;
      const R = dim * (0.34 + breathe + amp * ampRadiusEnv);

      ctx.clearRect(0, 0, W, H);
      ctx.lineCap = "round";

      const maxDrawR = dim / 2 - 1;
      const RSpin = R;
      const bloomOuter = Math.min(R * 1.28 + 6, dim * 0.46);
      const bloom = ctx.createRadialGradient(cx, cy, R * 0.35, cx, cy, bloomOuter);
      bloom.addColorStop(0, rgba(col.r, col.g, col.b, 0.04 + amp * 0.035));
      bloom.addColorStop(0.3, rgba(col.r, col.g, col.b, 0.016 + amp * 0.018));
      bloom.addColorStop(0.6, rgba(col.r, col.g, col.b, 0.004));
      bloom.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = bloom;
      ctx.beginPath();
      ctx.arc(cx, cy, bloomOuter, 0, Math.PI * 2);
      ctx.fill();

      drawGrayRiscos(ctx, cx, cy, R, t, confirmationPending, maxDrawR, RSpin);

      const discGrad = ctx.createRadialGradient(cx - R * 0.06, cy - R * 0.1, R * 0.04, cx, cy, R - 2);
      discGrad.addColorStop(0, confirmationPending ? "#140808" : "#090a0e");
      discGrad.addColorStop(0.5, confirmationPending ? "#080404" : "#050608");
      discGrad.addColorStop(1, "#020508");
      ctx.beginPath();
      ctx.arc(cx, cy, R - 2, 0, Math.PI * 2);
      ctx.fillStyle = discGrad;
      ctx.fill();

      const vignette = ctx.createRadialGradient(cx, cy, R * 0.3, cx, cy, R - 2);
      vignette.addColorStop(0, "rgba(0,0,0,0)");
      vignette.addColorStop(1, "rgba(0,0,0,0.5)");
      ctx.fillStyle = vignette;
      ctx.beginPath();
      ctx.arc(cx, cy, R - 2, 0, Math.PI * 2);
      ctx.fill();

      drawJarvisOrbLabel(ctx, cx, cy, RStable);

      const ringTint = confirmationPending
        ? TINT_CONFIRM
        : isResearching
          ? TINT_RESEARCH
          : TINT_IDLE;
      drawHuwScannerArcs({
        ctx,
        cx,
        cy,
        R,
        RStable,
        RSpin,
        t,
        maxDrawR,
        tint: ringTint,
      });

      const ringR = R * RING_SCANNER.radiusMul;
      drawCinematicAmbientSpill(ctx, cx, cy, R, ringTint, ringR);

      drawWhiteTickDotRing(ctx, cx, cy, R, t, maxDrawR);
      drawHuwWhiteScribbles(ctx, cx, cy, R, t, maxDrawR);

      if (!document.hidden) raf = requestAnimationFrame(draw);
    };

    if (!document.hidden) raf = requestAnimationFrame(draw);
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div ref={wrapRef} className="orb-wa-wrap relative w-full h-full select-none pointer-events-none" aria-label="JARVIS">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" aria-hidden />
    </div>
  );
}
