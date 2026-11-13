/** JARVIS no disco — traço uniforme, larguras medidas, espaçamento igual. */
const GLYPHS = ["J", "A", "R", "V", "I", "S"] as const;
type Glyph = (typeof GLYPHS)[number];

/** Largura visual de cada letra (× fs) — define kerning uniforme */
const WIDTH: Record<Glyph, number> = {
  J: 0.34,
  A: 0.44,
  R: 0.38,
  V: 0.40,
  I: 0.11,
  S: 0.36,
};

const GAP_EM = 0.17;

function addGlyph(
  path: Path2D,
  g: Glyph,
  x: number,
  cy: number,
  fs: number,
  top: number,
  bot: number
) {
  const w = WIDTH[g] * fs;
  const cx = x + w / 2;
  const h = bot - top;

  switch (g) {
    case "J": {
      const jx = cx + w * 0.06;
      path.moveTo(jx, top);
      path.lineTo(jx, bot - h * 0.12);
      path.quadraticCurveTo(jx, bot + h * 0.08, jx - w * 0.62, bot);
      break;
    }
    case "A": {
      const half = w * 0.46;
      path.moveTo(cx - half, bot);
      path.lineTo(cx, top);
      path.lineTo(cx + half, bot);
      break;
    }
    case "R": {
      const lx = cx - w * 0.34;
      const rx = cx + w * 0.28;
      const midY = top + h * 0.5;
      path.moveTo(lx, top);
      path.lineTo(lx, bot);
      path.moveTo(lx, top);
      path.lineTo(rx, top);
      path.quadraticCurveTo(rx + w * 0.1, midY, lx + w * 0.3, midY);
      path.moveTo(lx + w * 0.3, midY);
      path.lineTo(rx + w * 0.04, bot);
      break;
    }
    case "V": {
      const half = w * 0.44;
      path.moveTo(cx - half, top);
      path.lineTo(cx, bot);
      path.lineTo(cx + half, top);
      break;
    }
    case "I": {
      path.moveTo(cx, top);
      path.lineTo(cx, bot);
      break;
    }
    case "S": {
      const hw = w * 0.36;
      const upper = top + h * 0.26;
      const lower = bot - h * 0.26;
      path.moveTo(cx + hw * 0.82, top + h * 0.04);
      path.bezierCurveTo(
        cx + hw * 0.15, top - h * 0.03,
        cx - hw * 0.78, top + h * 0.1,
        cx - hw * 0.62, upper
      );
      path.bezierCurveTo(
        cx - hw * 0.48, cy - h * 0.02,
        cx + hw * 0.48, cy + h * 0.02,
        cx + hw * 0.62, lower
      );
      path.bezierCurveTo(
        cx + hw * 0.78, bot - h * 0.1,
        cx - hw * 0.15, bot + h * 0.03,
        cx - hw * 0.82, bot - h * 0.04
      );
      break;
    }
  }
}

let cachedKey = "";
let cachedPath: Path2D | null = null;
let cachedStroke = 1;

function buildLabelPath(cx: number, cy: number, fs: number): Path2D {
  const gap = fs * GAP_EM;
  const total =
    GLYPHS.reduce((sum, g) => sum + WIDTH[g] * fs, 0) + gap * (GLYPHS.length - 1);
  const top = cy - fs * 0.42;
  const bot = cy + fs * 0.4;

  const path = new Path2D();
  let x = cx - total / 2;
  for (const g of GLYPHS) {
    addGlyph(path, g, x, cy, fs, top, bot);
    x += WIDTH[g] * fs + gap;
  }
  return path;
}

export function drawJarvisOrbLabel(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  RStable: number
) {
  const fs = Math.max(7, RStable * 0.258);
  const key = `${cx}|${cy}|${fs}`;
  if (!cachedPath || cachedKey !== key) {
    cachedPath = buildLabelPath(cx, cy, fs);
    cachedKey = key;
    cachedStroke = Math.max(0.55, fs * 0.05);
  }

  ctx.save();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = cachedStroke;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.shadowBlur = 0;
  ctx.stroke(cachedPath);
  ctx.restore();
}
