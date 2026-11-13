"use client";

import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type WheelEvent as ReactWheelEvent } from "react";
import {
  useNativeBrowser,
  nativeBrowserShow,
  nativeBrowserSetBounds,
  nativeBrowserNavigate,
  nativeBrowserHide,
} from "@/lib/nativeBrowser";
import { JARVIS_MOTION } from "@/lib/motion";
import { useJarvis } from "@/lib/state";

const API = "http://127.0.0.1:8000";

export type BrowserPreview = {
  url?: string;
  title?: string;
  query?: string;
  text?: string;
  image?: string | null;
};

interface GoogleSidePanelProps {
  visible: boolean;
}

const OPEN_MS = JARVIS_MOTION.ms;
const CLOSE_MS = JARVIS_MOTION.msClose;

/** Painel de navegação embutido — animação única na abertura (preview não re-anima) */
export function GoogleSidePanel({ visible }: GoogleSidePanelProps) {
  const [preview, setPreview] = useState<BrowserPreview | null>(null);
  const [open, setOpen] = useState(false);
  const [displayImage, setDisplayImage] = useState<string | null>(null);
  const [imageReady, setImageReady] = useState(false);
  const [sessionAlive, setSessionAlive] = useState(false);
  const [searchDraft, setSearchDraft] = useState("");
  const [searching, setSearching] = useState(false);
  const [nativeMode, setNativeMode] = useState(false);
  const [nativeFailed, setNativeFailed] = useState(false);
  const [cowatch, setCowatch] = useState(false);
  const [closing, setClosing] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openRaf = useRef(0);
  const openedRef = useRef(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const nativeCreatedRef = useRef(false);
  const nativeUrlRef = useRef<string | null>(null);

  // Guardas em ref, não em estado: com deps [closing, open] o beginClose mudava de
  // identidade a cada fechamento, o efeito que o observa re-rodava e a limpeza dele
  // matava o próprio closeTimer — o painel travava meio-fechado para sempre.
  const closingRef = useRef(false);
  const openRef = useRef(false);

  const scheduleOpen = useCallback(() => {
    if (openRaf.current) cancelAnimationFrame(openRaf.current);
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    closingRef.current = false;
    openRef.current = false;
    setClosing(false);
    setOpen(false);
    openRaf.current = requestAnimationFrame(() => {
      openRaf.current = requestAnimationFrame(() => {
        openRef.current = true;
        setOpen(true);
      });
    });
  }, []);

  const beginClose = useCallback(() => {
    if (closingRef.current && !openRef.current) return;
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closingRef.current = true;
    openRef.current = false;
    setClosing(true);
    setOpen(false);
    openedRef.current = false;
    nativeCreatedRef.current = false;
    nativeUrlRef.current = null;
    void nativeBrowserHide();
    closeTimer.current = setTimeout(() => {
      closingRef.current = false;
      setClosing(false);
      setSessionAlive(false);
      setPreview(null);
      setDisplayImage(null);
      setImageReady(false);
      closeTimer.current = null;
    }, CLOSE_MS);
  }, []);

  useEffect(() => {
    const onPreview = (e: Event) => {
      const d = (e as CustomEvent<BrowserPreview>).detail;
      if (!d) return;
      // Preview sem página real (about:blank) renderiza um retângulo branco/preto
      const purl = (d.url || "").trim().toLowerCase();
      const hasPage = purl.startsWith("http") || purl.startsWith("file://");
      const hasQuery = !!(d.query || "").trim();
      const hasImage = !!(d.image || "").trim();
      if (!hasPage && !hasQuery && !hasImage) return;
      setSessionAlive(true);
      setPreview((prev) => ({
        url: d.url || prev?.url,
        title: d.title || prev?.title,
        query: d.query || prev?.query,
        text: d.text || prev?.text,
        image: d.image ?? prev?.image,
      }));
      // Abre animação só com conteúdo real (evita moldura preta vazia)
      if (!openedRef.current) {
        openedRef.current = true;
        scheduleOpen();
      }
    };

    const onClear = () => beginClose();

    window.addEventListener("jarvis:browser-preview", onPreview);
    window.addEventListener("jarvis:browser-clear", onClear);
    return () => {
      window.removeEventListener("jarvis:browser-preview", onPreview);
      window.removeEventListener("jarvis:browser-clear", onClear);
      if (closeTimer.current) clearTimeout(closeTimer.current);
      if (openRaf.current) cancelAnimationFrame(openRaf.current);
    };
  }, [beginClose, scheduleOpen]);

  useEffect(() => {
    setNativeMode(useNativeBrowser());
    // Webview nativa órfã de uma sessão anterior fica sobreposta ao app como um
    // retângulo preto (não está no DOM) — no boot sempre manda esconder.
    void nativeBrowserHide();
    const onNativeErr = () => setNativeFailed(true);
    const onCowatchStart = () => setCowatch(true);
    const onCowatchEnd = () => setCowatch(false);
    window.addEventListener("jarvis:native-browser-error", onNativeErr);
    window.addEventListener("jarvis:cowatch-start", onCowatchStart);
    window.addEventListener("jarvis:cowatch-end", onCowatchEnd);
    return () => {
      window.removeEventListener("jarvis:native-browser-error", onNativeErr);
      window.removeEventListener("jarvis:cowatch-start", onCowatchStart);
      window.removeEventListener("jarvis:cowatch-end", onCowatchEnd);
    };
  }, []);

  useEffect(() => {
    if (visible) {
      if (closeTimer.current) {
        clearTimeout(closeTimer.current);
        closeTimer.current = null;
      }
      closingRef.current = false;
      setClosing(false);
      // NÃO abrir moldura preta só com browserActive: espera preview real
      // (url/imagem). Antes: quadrado preto vazio ao redor do JARVIS.
      const hasContent =
        !!(preview?.url || preview?.image || preview?.query || displayImage);
      if (!hasContent) return;
      setSessionAlive(true);
      if (!open) {
        openedRef.current = true;
        scheduleOpen();
      }
      return;
    }

    if ((open || sessionAlive) && !closing) {
      beginClose();
    }
  }, [visible, open, closing, scheduleOpen, beginClose, preview, displayImage, sessionAlive]);

  const nextImage = preview?.image ?? null;
  useEffect(() => {
    if (!nextImage) return;
    if (nextImage === displayImage) {
      setImageReady(true);
      return;
    }

    setImageReady(false);
    const img = new Image();
    const apply = () => {
      requestAnimationFrame(() => {
        setDisplayImage(nextImage);
        requestAnimationFrame(() => setImageReady(true));
      });
    };
    img.onload = apply;
    img.onerror = apply;
    img.src = `data:image/jpeg;base64,${nextImage}`;
  }, [nextImage, displayImage]);

  // Etapa 2: no app (Tauri) dirige o navegador REAL embutido sobre a região do painel.
  // Fora do Tauri é no-op (o painel segue com o screenshot).
  useEffect(() => {
    if (!useNativeBrowser()) return;
    const shown = open && (visible || !!preview);
    const url = preview?.url ?? null;

    const getRect = () => {
      const el = viewportRef.current;
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return null;
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    };

    if (!shown || !url) {
      void nativeBrowserHide();
      return;
    }

    const onResize = () => {
      const rr = getRect();
      if (rr) void nativeBrowserSetBounds(rr);
    };
    window.addEventListener("resize", onResize);

    if (!nativeCreatedRef.current) {
      const t = setTimeout(() => {
        const rr = getRect();
        if (!rr) return;
        void nativeBrowserShow(url, rr);
        nativeCreatedRef.current = true;
        nativeUrlRef.current = url;
      }, OPEN_MS);
      return () => {
        clearTimeout(t);
        window.removeEventListener("resize", onResize);
      };
    }

    if (url !== nativeUrlRef.current) {
      void nativeBrowserNavigate(url);
      nativeUrlRef.current = url;
    }
    const rr = getRect();
    if (rr) void nativeBrowserSetBounds(rr);

    return () => window.removeEventListener("resize", onResize);
  }, [open, visible, preview]);

  const query =
    preview?.query ||
    (preview?.url?.includes("google.com/search")
      ? decodeURIComponent((preview.url.match(/[?&]q=([^&]+)/) || [])[1] || "").replace(/\+/g, " ")
      : "") ||
    preview?.title ||
    "";

  const runPanelSearch = useCallback(async () => {
    const q = searchDraft.trim();
    if (!q || searching) return;
    setSearching(true);
    setSessionAlive(true);
    if (!openedRef.current) {
      openedRef.current = true;
      scheduleOpen();
    }
    try {
      await fetch(`${API}/api/jarvis/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: `pesquisa no painel ${q}`, browser_active: true }),
      });
    } catch {
      /* WS atualiza o preview quando o backend navegar */
    } finally {
      setSearching(false);
    }
  }, [searchDraft, searching]);

  const interact = useCallback(async (body: Record<string, unknown>) => {
    try {
      await fetch(`${API}/api/browse/interact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      /* o WS atualiza o frame quando o backend responder */
    }
  }, []);

  const handleFrameClick = useCallback(
    (e: ReactMouseEvent<HTMLImageElement>) => {
      const img = e.currentTarget;
      const rect = img.getBoundingClientRect();
      const iw = img.naturalWidth || 1366;
      const ih = img.naturalHeight || 854;
      const scale = Math.min(rect.width / iw, rect.height / ih);
      const dispW = iw * scale;
      const dispH = ih * scale;
      const offX = (rect.width - dispW) / 2;
      const offY = (rect.height - dispH) / 2;
      const px = e.clientX - rect.left - offX;
      const py = e.clientY - rect.top - offY;
      if (px < 0 || py < 0 || px > dispW || py > dispH) return;
      void interact({ action: "click", x: px / dispW, y: py / dispH });
    },
    [interact]
  );

  const wheelAccum = useRef(0);
  const wheelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleWheel = useCallback(
    (e: ReactWheelEvent) => {
      wheelAccum.current += e.deltaY;
      if (wheelTimer.current) clearTimeout(wheelTimer.current);
      wheelTimer.current = setTimeout(() => {
        const dy = Math.round(wheelAccum.current);
        wheelAccum.current = 0;
        if (Math.abs(dy) > 20) void interact({ action: "scroll", dy });
      }, 120);
    },
    [interact]
  );

  const host = preview?.url
    ? (() => {
        try {
          return new URL(preview.url).hostname.replace(/^www\./, "");
        } catch {
          return preview.url;
        }
      })()
    : "google.com";

  const panelOpen = open && (visible || !!preview);

  useEffect(() => {
    // Gate em sessionAlive (não em panelOpen): estados intermediários — painel
    // montado mas sem animação de abertura — ficavam sem nenhuma limpeza
    if (!sessionAlive || nativeMode) return;
    const ms = cowatch ? 1400 : 2200;
    // 2 respostas vazias seguidas = navegador sem página; fecha em vez de exibir branco
    let emptyStrikes = 0;
    const tick = async () => {
      try {
        const res = await fetch(`${API}/api/browse/preview`, { cache: "no-store" });
        const data = (await res.json()) as { empty?: boolean };
        emptyStrikes = data?.empty ? emptyStrikes + 1 : 0;
        if (emptyStrikes >= 2) {
          // browserActive preso reabriria o painel logo em seguida (moldura escura
          // sem imagem = quadrado preto) — desliga na origem, não só localmente
          useJarvis.getState().setBrowserActive(false);
          beginClose();
        }
      } catch {
        /* backend offline — mantém o último frame */
      }
    };
    void tick(); // primeira leitura imediata — encurta o tempo de moldura vazia na tela
    const id = setInterval(() => void tick(), ms);
    return () => clearInterval(id);
  }, [sessionAlive, nativeMode, cowatch, beginClose]);

  // Sem conteúdo real = não monta o painel (evita quadrado preto em volta do orb)
  const hasVisual =
    !!displayImage ||
    nativeMode ||
    !!(preview?.url && (preview.url.startsWith("http") || preview.url.startsWith("file://"))) ||
    searching;
  if ((!sessionAlive || !hasVisual) && !closing) return null;

  const panelAnimOpen = panelOpen && !closing;
  const panelAnimClosing = closing && !panelOpen;

  return (
    <div
      className={`huw-browser-panel ${panelAnimOpen ? "is-open" : ""} ${panelAnimClosing ? "is-closing" : ""}`}
      aria-hidden={!panelAnimOpen}
    >
      <div className="huw-browser-panel-inner relative h-full flex flex-col overflow-hidden">
        <span className="huw-browser-bracket huw-browser-bracket--tl" aria-hidden />
        <span className="huw-browser-bracket huw-browser-bracket--tr" aria-hidden />
        <span className="huw-browser-bracket huw-browser-bracket--bl" aria-hidden />
        <span className="huw-browser-bracket huw-browser-bracket--br" aria-hidden />

        <div className="huw-browser-chrome huw-browser-chrome--interactive flex items-center gap-2.5 px-4 py-3 shrink-0">
          <GoogleMark />
          <form
            className="flex-1 min-w-0 rounded-full bg-[#141418]/90 border border-white/10 px-3 py-1.5 flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void runPanelSearch();
            }}
          >
            <span className="w-2 h-2 rounded-full bg-emerald-400/80 shrink-0 animate-pulse" />
            <input
              type="search"
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder={query || host || "Pesquisar no Google..."}
              className="flex-1 min-w-0 bg-transparent text-[12px] text-white/90 font-light tracking-wide outline-none placeholder:text-white/35"
              disabled={searching}
              aria-label="Pesquisar no painel"
            />
            <button
              type="submit"
              disabled={searching || !searchDraft.trim()}
              className="text-[10px] text-violet-300/90 uppercase tracking-wider shrink-0 disabled:opacity-30"
            >
              {searching ? "..." : "Buscar"}
            </button>
          </form>
          <span className="text-[9px] font-mono text-white/35 tracking-[0.2em] uppercase shrink-0">
            {nativeMode && !nativeFailed ? "Google Live" : "Preview"}
          </span>
        </div>

        <div
          ref={viewportRef}
          className={`huw-browser-viewport flex-1 min-h-0 relative overflow-hidden ${
            displayImage || nativeMode ? "bg-[#08090c]" : "bg-transparent"
          }`}
          onWheel={handleWheel}
        >
          {displayImage ? (
            <img
              src={`data:image/jpeg;base64,${displayImage}`}
              alt="Página em navegação"
              onClick={handleFrameClick}
              className={`huw-browser-screenshot absolute inset-0 w-full h-full object-contain cursor-pointer ${
                imageReady ? "is-ready" : "is-loading"
              }`}
            />
          ) : null}
          {!displayImage && !nativeMode && (
            <div className="huw-browser-shimmer absolute inset-0 opacity-40" aria-hidden />
          )}

          <div className="huw-browser-scanline absolute inset-0 pointer-events-none" aria-hidden />

          {!imageReady && (
            <div className="absolute bottom-0 left-0 right-0 px-4 py-3 bg-gradient-to-t from-black/85 via-black/50 to-transparent pointer-events-none">
              {!displayImage && (
                <p className="text-[11px] text-white/40 font-light italic">Abrindo página...</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden className="shrink-0">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  );
}