/** Backend JARVIS — mesma origem no browser (Next rewrite → :8000), direto no SSR. */
export const JARVIS_API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_JARVIS_API) ||
  "http://127.0.0.1:8000";

function browserDevOrigin(): string | null {
  if (typeof window === "undefined") return null;
  const o = window.location.origin;
  if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(o)) {
    return o;
  }
  return null;
}

export function jarvisApi(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const origin = browserDevOrigin();
  if (origin) return `${origin}${p}`;
  return `${JARVIS_API_BASE}${p}`;
}

/** WS direto no backend — usa mesmo hostname da página (evita PNA no WebView2). */
export function jarvisWsUrl(): string {
  const origin = browserDevOrigin();
  if (origin && typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    return `ws://${host}:8000/ws`;
  }
  const base = JARVIS_API_BASE.replace(/^http/i, "ws");
  return `${base.replace(/\/$/, "")}/ws`;
}

/** URLs de health — proxy same-origin primeiro (sem abort-storm no :8000). */
export function jarvisHealthUrls(): string[] {
  const urls: string[] = [];
  try {
    const origin = browserDevOrigin();
    if (origin) urls.push(`${origin}/health/live`);
  } catch {
    /* ignore */
  }
  urls.push("http://127.0.0.1:8000/health/live");
  return [...new Set(urls)];
}

export async function jarvisHealthOk(timeoutMs = 5000): Promise<boolean> {
  for (const url of jarvisHealthUrls()) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      if (!res.ok) continue;
      const data = await res.json().catch(() => null);
      if (data?.ok === true) return true;
    } catch {
      /* próxima URL */
    } finally {
      clearTimeout(timer);
    }
  }
  return false;
}

/** Aguarda backend :8000 (boot UI/TTS — evita voz browser + "núcleo em carregamento"). */
export async function waitForJarvisBackend(maxMs = 90000, stepMs = 1500): Promise<boolean> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    if (await jarvisHealthOk(2500)) return true;
    await new Promise((r) => setTimeout(r, stepMs));
  }
  return false;
}

/** URLs para API — no browser, proxy Next (mesma origem) primeiro. */
export function jarvisApiUrls(path: string): string[] {
  const p = path.startsWith("/") ? path : `/${path}`;
  const urls: string[] = [];
  const viaProxy = jarvisApi(p);
  urls.push(viaProxy);
  const direct = `${JARVIS_API_BASE.replace(/\/$/, "")}${p}`;
  if (!urls.includes(direct)) urls.push(direct);
  const localhost = `http://localhost:8000${p}`;
  if (!urls.includes(localhost)) urls.push(localhost);
  return urls;
}

/** fetch com fallback :3000 proxy → :8000 direto (Edge/app mode). */
export async function jarvisFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  let last: Response | null = null;
  for (const url of jarvisApiUrls(path)) {
    try {
      const res = await fetch(url, { ...init, cache: "no-store" });
      if (res.ok) return res;
      last = res;
    } catch {
      /* tenta próxima URL */
    }
  }
  if (last) return last;
  throw new Error("JARVIS backend inacessível");
}