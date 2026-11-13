"use client";

import { useEffect, useRef, useState } from "react";
import { useJarvis } from "@/lib/state";

interface TickerLine {
  id: number;
  kind: "thought" | "run" | "done" | "info";
  text: string;
  born: number;
}

let lineId = 0;
const FADE_MS = 11000;
const MAX_LINES = 6;

const TOOL_LABELS: Record<string, string> = {
  open_app: "Abrindo aplicativo",
  close_app: "Fechando aplicativo",
  open_url: "Abrindo Google",
  web_search: "Pesquisando",
  open_browser_search: "Pesquisando no Google",
  run_command: "Executando comando",
  browse_open: "Navegando",
  browse_read: "Lendo a página",
  browse_click: "Clicando",
  browse_type: "Digitando",
  browse_scroll: "Rolando",
  save_to_obsidian: "Salvando no Obsidian",
  search_obsidian: "Consultando memória",
  look_at_screen: "Olhando a tela",
  desktop_click: "Clicando",
  desktop_type: "Digitando",
  study_topic: "Estudando",
  focus_app: "Focando janela",
  browse_close: "Fechando painel",
  clipboard_read: "Lendo clipboard",
  clipboard_copy: "Copiando",
  open_folder: "Abrindo pasta",
  list_windows: "Listando janelas",
  save_screenshot: "Salvando captura",
  translate_text: "Traduzindo",
  desktop_press: "Atalho de teclado",
};

interface OperStatusTickerProps {
  visible: boolean;
}

const ACTIVITY_BARS = 18;

export function OperStatusTicker({ visible }: OperStatusTickerProps) {
  const [lines, setLines] = useState<TickerLine[]>([]);
  const [now, setNow] = useState(Date.now());
  const [bars, setBars] = useState<number[]>(() => Array(ACTIVITY_BARS).fill(0.12));
  const working = useJarvis((s) => s.working);
  const audioLevel = useJarvis((s) => s.audioLevel);
  const jarvisState = useJarvis((s) => s.state);
  const wasWorking = useRef(false);

  const push = (kind: TickerLine["kind"], text: string) => {
    const t = text.trim();
    if (!t) return;
    setLines((prev) => [
      ...prev.slice(-(MAX_LINES - 1)),
      { id: ++lineId, kind, text: t.slice(0, 140), born: Date.now() },
    ]);
  };

  useEffect(() => {
    if (!visible) return;
    const onTool = (e: Event) => {
      const d = (e as CustomEvent).detail;
      const label = TOOL_LABELS[d.tool] || d.tool;
      if (d.status === "running") {
        const extra = d.desc ? String(d.desc).replace(/^[^(]+\(/, "").replace(/\)$/, "") : "";
        push("run", extra ? `${label} — ${extra}` : `${label}...`);
      } else {
        const res = d.result ? ` — ${String(d.result).slice(0, 60)}` : "";
        push("done", `${label}${res}`);
      }
    };
    const onThought = (e: Event) => {
      push("thought", String((e as CustomEvent).detail?.text || ""));
    };
    window.addEventListener("jarvis:tool-call", onTool);
    window.addEventListener("jarvis:agent-thought", onThought);
    return () => {
      window.removeEventListener("jarvis:tool-call", onTool);
      window.removeEventListener("jarvis:agent-thought", onThought);
    };
  }, [visible]);

  useEffect(() => {
    if (visible && working && !wasWorking.current) {
      push("run", "Executando...");
    }
    wasWorking.current = working;
  }, [visible, working]);

  useEffect(() => {
    if (!visible || lines.length === 0) return;
    const tick = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(tick);
  }, [visible, lines.length]);

  useEffect(() => {
    setLines((prev) => prev.filter((l) => now - l.born < FADE_MS + 400));
  }, [now]);

  useEffect(() => {
    if (!visible) return;
    const tick = setInterval(() => {
      const base =
        working ? 0.42
        : jarvisState === "speaking" ? 0.25 + audioLevel * 0.75
        : jarvisState === "listening" ? 0.55
        : jarvisState === "thinking" ? 0.38
        : 0.1;
      setBars((prev) => {
        const next = prev.slice(1);
        next.push(Math.min(1, base * 0.65 + Math.random() * 0.35));
        return next;
      });
    }, 90);
    return () => clearInterval(tick);
  }, [visible, working, audioLevel, jarvisState]);

  const show = visible && (lines.length > 0 || working || jarvisState !== "idle");

  const colors: Record<TickerLine["kind"], string> = {
    thought: "rgba(200,230,255,0.72)",
    run: "rgba(255,217,127,0.88)",
    done: "rgba(127,233,176,0.75)",
    info: "rgba(255,255,255,0.65)",
  };

  return (
    <div
      className={`oper-status-ticker absolute z-[14] pointer-events-none text-right ${show ? "is-visible" : ""}`}
      style={{ right: "3vw", top: "14vh", maxWidth: "min(260px, 22vw)" }}
      aria-hidden={!show}
    >
      <div className="oper-activity-strip mb-3 flex items-end justify-end gap-[3px] h-7">
        {bars.map((h, i) => (
          <span
            key={i}
            className="oper-activity-bar"
            style={{
              height: `${Math.max(14, h * 100)}%`,
              opacity: 0.35 + h * 0.55,
            }}
          />
        ))}
      </div>
      {lines.map((l) => {
        const age = now - l.born;
        const opacity = Math.max(0, 1 - age / FADE_MS);
        if (opacity <= 0.02) return null;
        return (
          <p
            key={l.id}
            className="font-mono text-[10px] leading-relaxed mb-2.5 font-light"
            style={{
              color: colors[l.kind],
              opacity,
              textShadow: "0 1px 8px rgba(0,0,0,0.55)",
            }}
          >
            {l.kind === "run" ? "→ " : l.kind === "done" ? "✓ " : "» "}
            {l.text}
          </p>
        );
      })}
    </div>
  );
}