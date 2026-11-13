/**
 * Orb WhatsApp — risco azul principal + 3 riscos cinzas girando (ref. vídeo).
 */

const TAU_7 = (Math.PI * 2) / 7;
const TAU_9 = (Math.PI * 2) / 9;

/** Espaçamento uniforme entre riscos brancos (levemente afastados da orb) */
const GRAY_RISCO_BASE = 1.26;
const GRAY_RISCO_GAP = 0.10;
const PURE_WHITE = "#ffffff";
/** 3 lados — 120° entre cada risco cinza */
const GRAY_SIDE_SPREAD = (Math.PI * 2) / 3;
const GRAY_SIDE_ORIGIN = -Math.PI / 2;

/** Gap do anel principal — abertura centrada embaixo */
export const OPEN_RING_GAP = {
  center: Math.PI / 2,
  span: Math.PI * 0.32,
} as const;

export function getOpenRingArc(): { start: number; end: number } {
  const half = OPEN_RING_GAP.span / 2;
  return {
    start: OPEN_RING_GAP.center + half,
    end: OPEN_RING_GAP.center - half + Math.PI * 2,
  };
}

export function isInRingGap(angle: number): boolean {
  let d = angle - OPEN_RING_GAP.center;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return Math.abs(d) < OPEN_RING_GAP.span / 2;
}

export function drawOpenOrbRing(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  strokeStyle: string,
  lineWidth: number,
  opts?: { shadowBlur?: number; shadowColor?: string }
) {
  const { start, end } = getOpenRingArc();
  ctx.save();
  ctx.lineCap = "round";
  if (opts?.shadowBlur) {
    ctx.shadowBlur = opts.shadowBlur;
    ctx.shadowColor = opts.shadowColor ?? "rgba(255,255,255,0.4)";
  }
  ctx.beginPath();
  ctx.arc(cx, cy, radius, start, end);
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth;
  ctx.stroke();
  ctx.restore();
}

/** Risco único — levemente fora do disco (ref. vídeo WhatsApp) */
export const RING_SCANNER = {
  radiusMul: 1.06,
  speed: TAU_7 * 0.72,
  dir: 1,
  /** ~1.34π ≈ 67% */
  span: Math.PI * 1.34,
  coreWidth: 1.35,
  midWidth: 2.35,
  haloWidth: 8.8,
  phase: -Math.PI / 2,
} as const;

/**
 * 3 riscos cinzas girando — pequeno (perto) → médio → grande (longe).
 * Direções alternadas; spans proporcionais ao tamanho.
 */
export const GRAY_RISCOS = [
  /** 1º pequeno — lado oposto (embaixo), gira horário */
  {
    radiusMul: GRAY_RISCO_BASE,
    speed: TAU_9,
    dir: 1 as const,
    span: Math.PI * 0.3,
    lineWidth: 0.82,
    alpha: 0.72,
    phase: GRAY_SIDE_ORIGIN + Math.PI,
  },
  /** 2º médio — lado direito, gira anti-horário (fase adiantada) */
  {
    radiusMul: GRAY_RISCO_BASE + GRAY_RISCO_GAP,
    speed: TAU_7 * 0.88,
    dir: -1 as const,
    span: Math.PI * 0.48,
    lineWidth: 1.28,
    alpha: 0.78,
    phase: GRAY_SIDE_ORIGIN + GRAY_SIDE_SPREAD + 0.52,
  },
  /** 3º grande — lado esquerdo, gira horário */
  {
    radiusMul: GRAY_RISCO_BASE + GRAY_RISCO_GAP * 2,
    speed: TAU_7 * 0.74,
    dir: 1 as const,
    span: Math.PI * 0.58,
    lineWidth: 1.52,
    alpha: 0.85,
    phase: GRAY_SIDE_ORIGIN + GRAY_SIDE_SPREAD * 2,
  },
] as const;

/** Raio do último risco cinza (grande) */
export const GRAY_RISCO_OUTER =
  GRAY_RISCO_BASE + GRAY_RISCO_GAP * 2;

export const FAR_DETAIL = {
  dotCount: 24,
  dotDrift: 0.009,
  ringMul: GRAY_RISCO_OUTER + 0.14,
  tickCount: 24,
  outerRingMul: GRAY_RISCO_OUTER + 0.18,
} as const;

const COMET_TINT_DEFAULT = { r: 48, g: 128, b: 188 };
const COMET_HOT = { r: 88, g: 158, b: 205 };

function mixChannel(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export type HuwScannerCtx = {
  ctx: CanvasRenderingContext2D;
  cx: number;
  cy: number;
  R: number;
  RStable: number;
  RSpin?: number;
  t: number;
  maxDrawR?: number;
  tint?: { r: number; g: number; b: number };
};

function resolveRadius(baseR: number, mul: number, maxDrawR?: number): number {
  const r = baseR * mul;
  if (maxDrawR == null) return r;
  const cap = maxDrawR - 1;
  return r > cap ? cap : r;
}

function paintCometRingArc(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  head: number,
  span: number,
  scanner: typeof RING_SCANNER,
  tint?: { r: number; g: number; b: number },
) {
  const SEG = 56;
  const tr = tint ?? COMET_TINT_DEFAULT;
  const hot = COMET_HOT;
  const tail = head - span;

  ctx.save();
  ctx.lineCap = "round";

  // Halo cinematográfico — difuso, sem pico LED
  ctx.globalCompositeOperation = "source-over";
  ctx.shadowBlur = scanner.haloWidth * 2;
  ctx.shadowColor = `rgba(${tr.r},${tr.g},${tr.b},0.18)`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, tail, head);
  ctx.strokeStyle = `rgba(${tr.r},${tr.g},${tr.b},0.06)`;
  ctx.lineWidth = scanner.haloWidth * 1.5;
  ctx.stroke();

  ctx.shadowBlur = scanner.haloWidth * 1.25;
  ctx.shadowColor = `rgba(${tr.r},${tr.g},${tr.b},0.14)`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, tail, head);
  ctx.strokeStyle = `rgba(${tr.r},${tr.g},${tr.b},0.1)`;
  ctx.lineWidth = scanner.haloWidth * 0.95;
  ctx.stroke();

  ctx.shadowBlur = scanner.haloWidth * 0.55;
  ctx.shadowColor = `rgba(${tr.r},${tr.g},${tr.b},0.22)`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, tail, head);
  ctx.strokeStyle = `rgba(${tr.r},${tr.g},${tr.b},0.22)`;
  ctx.lineWidth = scanner.haloWidth * 0.42;
  ctx.stroke();

  // Núcleo fino — tom natural, sem branco puro
  ctx.shadowBlur = scanner.haloWidth * 0.35;
  ctx.shadowColor = `rgba(${tr.r},${tr.g},${tr.b},0.28)`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, tail, head);
  ctx.strokeStyle = `rgba(${tr.r},${tr.g},${tr.b},0.42)`;
  ctx.lineWidth = scanner.midWidth;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(cx, cy, radius, tail, head);
  ctx.strokeStyle = `rgba(${hot.r},${hot.g},${hot.b},0.48)`;
  ctx.lineWidth = scanner.coreWidth;
  ctx.stroke();

  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < SEG; i++) {
    const f = (i + 1) / SEG;
    const a0 = tail + span * (i / SEG);
    const a1 = tail + span * f;
    const bright = Math.pow(f, 0.55);
    const mix = Math.pow(f, 1.1);
    const alpha = 0.08 + 0.38 * bright;
    const r = mixChannel(tr.r, hot.r, mix);
    const g = mixChannel(tr.g, hot.g, mix);
    const b = mixChannel(tr.b, hot.b, mix);
    const lw = scanner.coreWidth * (0.32 + 0.72 * bright);

    ctx.shadowBlur = 6 + 14 * bright;
    ctx.shadowColor = `rgba(${r | 0},${g | 0},${b | 0},${alpha * 0.65})`;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, a0, a1);
    ctx.strokeStyle = `rgba(${r | 0},${g | 0},${b | 0},${alpha})`;
    ctx.lineWidth = lw;
    ctx.stroke();
  }

  const hx = cx + Math.cos(head) * radius;
  const hy = cy + Math.sin(head) * radius;
  const hg = ctx.createRadialGradient(hx, hy, 0, hx, hy, scanner.haloWidth * 0.9);
  hg.addColorStop(0, `rgba(${hot.r},${hot.g},${hot.b},0.38)`);
  hg.addColorStop(0.4, `rgba(${tr.r},${tr.g},${tr.b},0.14)`);
  hg.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalCompositeOperation = "source-over";
  ctx.shadowBlur = scanner.haloWidth * 0.5;
  ctx.shadowColor = `rgba(${tr.r},${tr.g},${tr.b},0.25)`;
  ctx.fillStyle = hg;
  ctx.beginPath();
  ctx.arc(hx, hy, scanner.haloWidth * 0.9, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

/** Luz ambiente mínima — tingir levemente o entorno próximo */
export function drawCinematicAmbientSpill(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  R: number,
  col: { r: number; g: number; b: number },
  ringR: number,
) {
  ctx.save();
  ctx.globalCompositeOperation = "source-over";

  const spill = ctx.createRadialGradient(cx, cy, R * 0.88, cx, cy, ringR + R * 0.14);
  spill.addColorStop(0, `rgba(${col.r},${col.g},${col.b},0.012)`);
  spill.addColorStop(0.55, `rgba(${col.r},${col.g},${col.b},0.005)`);
  spill.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = spill;
  ctx.beginPath();
  ctx.arc(cx, cy, ringR + R * 0.14, 0, Math.PI * 2);
  ctx.fill();

  const rim = ctx.createRadialGradient(cx, cy, R * 0.96, cx, cy, R * 1.04);
  rim.addColorStop(0, "rgba(0,0,0,0)");
  rim.addColorStop(0.9, `rgba(${col.r},${col.g},${col.b},0.008)`);
  rim.addColorStop(1, `rgba(${col.r},${col.g},${col.b},0.014)`);
  ctx.fillStyle = rim;
  ctx.beginPath();
  ctx.arc(cx, cy, R * 1.08, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

function paintGraySpinArc(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  start: number,
  end: number,
  lineWidth: number,
  alpha: number,
  confirmationPending: boolean,
) {
  const a = confirmationPending ? alpha * 0.85 : alpha;

  ctx.save();
  ctx.lineCap = "round";
  ctx.globalCompositeOperation = "lighter";

  ctx.shadowBlur = 5;
  ctx.shadowColor = `rgba(255,255,255,${a * 0.35})`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, start, end);
  ctx.strokeStyle = PURE_WHITE;
  ctx.globalAlpha = a * 0.55;
  ctx.lineWidth = lineWidth * 1.5;
  ctx.stroke();

  ctx.shadowBlur = 3;
  ctx.shadowColor = `rgba(255,255,255,${a * 0.5})`;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, start, end);
  ctx.strokeStyle = PURE_WHITE;
  ctx.globalAlpha = a * 0.82;
  ctx.lineWidth = lineWidth;
  ctx.stroke();

  ctx.shadowBlur = 0;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, start, end);
  ctx.strokeStyle = PURE_WHITE;
  ctx.globalAlpha = Math.min(1, a);
  ctx.lineWidth = Math.max(0.45, lineWidth * 0.5);
  ctx.stroke();
  ctx.globalAlpha = 1;

  ctx.restore();
}

/** Riscos cinzas — desenha do maior (fundo) ao menor (frente) */
export function drawGrayRiscos(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  R: number,
  t: number,
  confirmationPending: boolean,
  maxDrawR?: number,
  spinBase?: number,
) {
  const base = spinBase ?? R;

  ctx.save();
  ctx.globalCompositeOperation = "source-over";

  for (let i = GRAY_RISCOS.length - 1; i >= 0; i--) {
    const layer = GRAY_RISCOS[i];
    const rad = resolveRadius(base, layer.radiusMul, maxDrawR);
    const head = t * layer.speed * layer.dir + layer.phase;
    paintGraySpinArc(
      ctx,
      cx,
      cy,
      rad,
      head - layer.span,
      head,
      layer.lineWidth,
      layer.alpha,
      confirmationPending,
    );
  }

  ctx.restore();
}

/** Anel circular — riscos retos (radiais) misturados com pontos brancos */
export const WHITE_TICK_DOT_RING = {
  radiusMul: GRAY_RISCO_OUTER + 0.16,
  count: 64,
  drift: 0.0032,
} as const;

export function drawWhiteTickDotRing(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  R: number,
  t: number,
  maxDrawR?: number,
) {
  const { radiusMul, count, drift } = WHITE_TICK_DOT_RING;
  const ringR = resolveRadius(R, radiusMul, maxDrawR);
  const driftA = t * drift - Math.PI / 2;

  ctx.save();
  ctx.lineCap = "butt";
  ctx.globalCompositeOperation = "lighter";

  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2 + driftA;
    const px = cx + Math.cos(a) * ringR;
    const py = cy + Math.sin(a) * ringR;
    const mod = i % 5;

    if (mod === 0 || mod === 3) {
      const inner = ringR - (mod === 0 ? 3.8 : 2.4);
      const outer = ringR + (mod === 0 ? 4.2 : 2.8);
      const flicker = 0.55 + Math.sin(t * 1.4 + i * 0.55) * 0.2;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
      ctx.lineTo(cx + Math.cos(a) * outer, cy + Math.sin(a) * outer);
      ctx.strokeStyle = PURE_WHITE;
      ctx.globalAlpha = flicker;
      ctx.lineWidth = mod === 0 ? 0.7 : 0.5;
      ctx.stroke();
      ctx.globalAlpha = 1;
      continue;
    }

    if (mod === 1 || mod === 4) {
      const sz = mod === 1 ? 0.95 : 0.55;
      const flicker = 0.72 + Math.sin(t * 1.8 + i * 0.7) * 0.22;
      ctx.beginPath();
      ctx.arc(px, py, sz, 0, Math.PI * 2);
      ctx.fillStyle = PURE_WHITE;
      ctx.globalAlpha = flicker;
      ctx.fill();
      ctx.globalAlpha = 1;
      continue;
    }

    const tangent = a + Math.PI / 2;
    const half = 2.2 + (i % 3) * 0.8;
    ctx.beginPath();
    ctx.moveTo(px - Math.cos(tangent) * half, py - Math.sin(tangent) * half);
    ctx.lineTo(px + Math.cos(tangent) * half, py + Math.sin(tangent) * half);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = 0.55 + (i % 4) * 0.1;
    ctx.lineWidth = 0.45;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  ctx.restore();
}

/** Pontos + rabiscos brancos puros — estilo @huwprosser (sem círculos) */
const HUW_SCRIBBLE_ARCS = [
  { mul: 1.17, span: 0.14, phase: 0.4, speed: 0.005, dir: 1, lw: 0.55 },
  { mul: 1.22, span: 0.2, phase: 2.3, speed: -0.004, dir: -1, lw: 0.65 },
  { mul: 1.29, span: 0.17, phase: 4.8, speed: 0.0035, dir: 1, lw: 0.6 },
  { mul: 1.36, span: 0.24, phase: 1.1, speed: -0.003, dir: -1, lw: 0.72 },
  { mul: 1.44, span: 0.19, phase: 5.5, speed: 0.0028, dir: 1, lw: 0.58 },
  { mul: 1.52, span: 0.22, phase: 3.6, speed: -0.0025, dir: -1, lw: 0.68 },
] as const;

export function drawHuwWhiteScribbles(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  R: number,
  t: number,
  maxDrawR?: number,
) {
  ctx.save();
  ctx.lineCap = "round";
  ctx.globalCompositeOperation = "lighter";

  const dotBands = [1.16, 1.21, 1.28, 1.36, 1.44, 1.53];
  for (let b = 0; b < dotBands.length; b++) {
    const dist = resolveRadius(R, dotBands[b], maxDrawR);
    const count = 8 + b * 3;
    const drift = t * (0.005 + b * 0.0015);
    for (let i = 0; i < count; i++) {
      if ((i + b) % 5 === 2) continue;
      const a = (i / count) * Math.PI * 2 - Math.PI / 2 + drift + b * 0.55;
      const flicker = 0.55 + Math.sin(t * 1.6 + i * 0.8 + b) * 0.35;
      const sz = i % 4 === 0 ? 1.05 : i % 2 === 0 ? 0.7 : 0.45;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(a) * dist, cy + Math.sin(a) * dist, sz, 0, Math.PI * 2);
      ctx.fillStyle = PURE_WHITE;
      ctx.globalAlpha = flicker;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  for (const s of HUW_SCRIBBLE_ARCS) {
    const rad = resolveRadius(R, s.mul, maxDrawR);
    const head = t * s.speed * s.dir + s.phase;
    const tail = head - s.span;
    ctx.shadowBlur = 2;
    ctx.shadowColor = "rgba(255,255,255,0.3)";
    ctx.beginPath();
    ctx.arc(cx, cy, rad, tail, head);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = 0.7;
    ctx.lineWidth = s.lw;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, rad, tail, head);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = 1;
    ctx.lineWidth = s.lw * 0.45;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  for (let i = 0; i < 14; i++) {
    if (i % 3 === 0) continue;
    const a = (i / 14) * Math.PI * 2 - Math.PI / 2 + t * 0.003 + i * 0.2;
    const r0 = resolveRadius(R, 1.18 + (i % 4) * 0.04, maxDrawR);
    const len = 3 + (i % 3) * 2;
    const px = cx + Math.cos(a) * r0;
    const py = cy + Math.sin(a) * r0;
    const dx = Math.cos(a + 0.35) * len;
    const dy = Math.sin(a + 0.35) * len;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px + dx, py + dy);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = 0.45 + (i % 4) * 0.1;
    ctx.lineWidth = 0.45;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  ctx.restore();
}

/** Detalhes extras — pontos, ticks, micro-riscos, partículas brancas */
export function drawDistantOrbDetails(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  R: number,
  t: number,
  maxDrawR?: number,
  col?: { r: number; g: number; b: number }
) {
  const { dotCount, dotDrift, ringMul, tickCount } = FAR_DETAIL;
  const drift = t * dotDrift;
  const ringR = resolveRadius(R, ringMul, maxDrawR);

  ctx.save();
  ctx.lineCap = "round";

  // Ticks tracejados no anel distante (giram lentamente)
  const tickDrift = t * 0.006;
  for (let i = 0; i < tickCount; i++) {
    if (i % 3 === 1) continue;
    const a = (i / tickCount) * Math.PI * 2 - Math.PI / 2 + tickDrift;
    const inner = ringR - 3;
    const outer = ringR + 3;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
    ctx.lineTo(cx + Math.cos(a) * outer, cy + Math.sin(a) * outer);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = i % 5 === 0 ? 0.75 : 0.55;
    ctx.lineWidth = i % 5 === 0 ? 0.75 : 0.5;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Pontos no anel distante
  for (let i = 0; i < dotCount; i++) {
    const a = (i / dotCount) * Math.PI * 2 - Math.PI / 2 + drift;
    const band = ringMul + (i % 3) * 0.05;
    const dist = resolveRadius(R, band, maxDrawR);
    const flicker = 0.5 + Math.sin(t * 1.3 + i * 0.65) * 0.35;
    const sz = i % 4 === 0 ? 1.05 : 0.6;
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * dist, cy + Math.sin(a) * dist, sz, 0, Math.PI * 2);
    ctx.fillStyle = PURE_WHITE;
    ctx.globalAlpha = flicker;
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  // Micro-riscos radiais entre anéis
  for (let i = 0; i < 12; i++) {
    if (i % 2 !== 0) continue;
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2 + t * 0.004;
    const r0 = resolveRadius(R, 1.18, maxDrawR);
    const r1 = resolveRadius(R, 1.28, maxDrawR);
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
    ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
    ctx.strokeStyle = PURE_WHITE;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 0.45;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Partículas brancas esparsas (sem ciano)
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * Math.PI * 2 + t * 0.035 + i * 0.5;
    const dist = resolveRadius(R, 1.22 + (i % 3) * 0.05, maxDrawR);
    const flicker = 0.45 + Math.sin(t * 1.5 + i) * 0.35;
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * dist, cy + Math.sin(a) * dist, 0.65, 0, Math.PI * 2);
    ctx.fillStyle = PURE_WHITE;
    ctx.globalAlpha = flicker;
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  ctx.restore();
}

export function drawHuwScannerArcs({
  ctx,
  cx,
  cy,
  R,
  RStable,
  RSpin,
  t,
  maxDrawR,
  tint,
}: HuwScannerCtx) {
  const spinBase = RSpin ?? RStable;
  const scanner = RING_SCANNER;
  const ringR = resolveRadius(spinBase, scanner.radiusMul, maxDrawR);
  const head = t * scanner.speed * scanner.dir + scanner.phase;

  paintCometRingArc(ctx, cx, cy, ringR, head, scanner.span, scanner, tint);
}