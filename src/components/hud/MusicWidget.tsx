"use client";

import { useJarvis } from "@/lib/state";
import { useEffect, useRef } from "react";

function formatTime(progress: number, totalSec = 216) {
  const cur = Math.floor((progress / 100) * totalSec);
  const m = Math.floor(cur / 60);
  const s = cur % 60;
  const tm = Math.floor(totalSec / 60);
  const ts = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")} / ${tm}:${String(ts).padStart(2, "0")}`;
}

/** Widget música estilo Spotify — TikTok 763349 */
export function MusicWidget() {
  const nowPlaying = useJarvis((s) => s.nowPlaying);
  const isPlaying = useJarvis((s) => s.isMusicPlaying);
  const progress = useJarvis((s) => s.musicProgress);
  const setMusicProgress = useJarvis((s) => s.setMusicProgress);
  const pauseMusic = useJarvis((s) => s.pauseMusic);
  const playMusic = useJarvis((s) => s.playMusic);

  const progressRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isPlaying) return;
    const t = setInterval(() => {
      const p = useJarvis.getState().musicProgress;
      setMusicProgress(p >= 99 ? 12 : p + 0.35);
    }, 1000);
    return () => clearInterval(t);
  }, [isPlaying, setMusicProgress]);

  useEffect(() => {
    if (progressRef.current) progressRef.current.style.width = `${progress}%`;
  }, [progress]);

  const title = nowPlaying?.title || "Still Into You";
  const artist = nowPlaying?.artist || "Paramore";

  return (
    <div
      className="absolute z-40 pointer-events-auto w-[min(260px,30vw)]"
      style={{
        left: "max(28vw, 320px)",
        top: "38%",
        transform: "translateY(-50%)",
      }}
    >
      <div
        className="rounded-xl border border-cyan-500/15 bg-[#0a0f18]/90 backdrop-blur-lg px-3.5 py-3"
        style={{ boxShadow: "0 0 36px rgba(0,120,200,0.1)" }}
      >
        <p className="font-mono text-[9px] tracking-[3px] text-cyan-300/70 mb-2 uppercase">Spotify</p>

        <div className="flex gap-3">
          <div
            className="w-14 h-14 rounded-md shrink-0 overflow-hidden"
            style={{
              background: "linear-gradient(135deg, #e85d3a 0%, #c41e3a 45%, #8b1538 100%)",
              boxShadow: "inset 0 0 20px rgba(0,0,0,0.3)",
            }}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="text-white text-sm font-semibold tracking-wide truncate">{title}</p>
            <p className="text-cyan-300/75 text-xs mt-0.5 font-mono truncate">{artist}</p>
            <p className="text-white/35 text-[10px] mt-1 font-mono">{formatTime(progress)}</p>
          </div>
        </div>

        <div className="mt-3 h-1 bg-zinc-800/80 rounded overflow-hidden">
          <div
            ref={progressRef}
            className="h-full rounded"
            style={{
              background: "linear-gradient(to right, rgba(0,212,255,0.9), rgba(0,140,255,0.6))",
              width: `${progress}%`,
            }}
          />
        </div>

        <div className="mt-2.5 flex items-center justify-center gap-4 text-white/55 text-sm">
          <button type="button" className="hover:text-cyan-300 transition-colors" aria-label="Anterior">
            ⏮
          </button>
          <button
            type="button"
            onClick={() => (isPlaying ? pauseMusic() : playMusic())}
            className="text-cyan-300 hover:text-cyan-200 transition-colors text-base"
            aria-label={isPlaying ? "Pausar" : "Tocar"}
          >
            {isPlaying ? "⏸" : "▶"}
          </button>
          <button type="button" className="hover:text-cyan-300 transition-colors" aria-label="Próxima">
            ⏭
          </button>
        </div>
      </div>
    </div>
  );
}