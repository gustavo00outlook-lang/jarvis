"""
Motor de clone de voz local — Thomas 0701 / qualquer sample.

Estratégia (melhor → fallback):
1. Coqui XTTS-v2  — zero-shot, copia o timbre do reference.wav (melhor qualidade)
2. Edge + morph   — Antonio Neural + match de pitch/timbre do sample (sem modelo pesado)

Saída: bytes WAV (pcm16) ou MP3 via ffmpeg.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent
VOICES_DIR = ROOT / "voices"
DEFAULT_VOICE_ID = "thomas-0701"
_MASTER = VOICES_DIR / DEFAULT_VOICE_ID / "master.wav"
DEFAULT_REF = _MASTER if _MASTER.exists() else (VOICES_DIR / DEFAULT_VOICE_ID / "reference.wav")

_lock = threading.Lock()
_xtts = None
_xtts_err: Optional[str] = None
_xtts_latents = None  # (gpt_cond_latent, speaker_embedding) — 1x a partir do master.wav
_tts_cache: Dict[str, Tuple[bytes, str]] = {}
_TTS_CACHE_MAX = 64
_f5 = None
_f5_err: Optional[str] = None
_f5_ref_text: Optional[str] = None
_f5_ref_wav: Optional[str] = None
_active_voice = DEFAULT_VOICE_ID


def list_voices() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    for d in sorted(VOICES_DIR.iterdir() if VOICES_DIR.exists() else []):
        if not d.is_dir():
            continue
        master = d / "master.wav"
        ref = master if master.exists() else (d / "reference.wav")
        if not ref.exists():
            for cand in list(d.glob("*.wav")) + list(d.glob("*.mp3")):
                ref = cand
                break
        if not ref.exists():
            continue
        out[d.name] = {
            "id": d.name,
            "label": d.name.replace("-", " ").title(),
            "reference": str(ref),
            "bytes": ref.stat().st_size,
        }
    return out


def get_active_voice() -> str:
    return _active_voice


def set_active_voice(voice_id: str) -> Dict[str, Any]:
    global _active_voice
    voices = list_voices()
    if voice_id not in voices:
        raise ValueError(f"Voz desconhecida: {voice_id}. Disponíveis: {list(voices)}")
    _active_voice = voice_id
    # marca ativa
    marker = VOICES_DIR / "_active.txt"
    marker.write_text(voice_id, encoding="utf-8")
    return voices[voice_id]


def _load_active_from_disk() -> None:
    global _active_voice
    marker = VOICES_DIR / "_active.txt"
    if marker.exists():
        vid = marker.read_text(encoding="utf-8").strip()
        if vid in list_voices():
            _active_voice = vid


def resolve_reference(voice_id: Optional[str] = None) -> Path:
    _load_active_from_disk()
    vid = (voice_id or _active_voice or DEFAULT_VOICE_ID).strip()
    master = VOICES_DIR / vid / "master.wav"
    if master.exists():
        return master
    voices = list_voices()
    if vid in voices:
        return Path(voices[vid]["reference"])
    if DEFAULT_REF.exists():
        return DEFAULT_REF
    raise FileNotFoundError(
        f"Reference não encontrada para '{vid}'. "
        f"Coloque um .wav em voice-clone-app/voices/{vid}/reference.wav"
    )


def register_voice(
    voice_id: str,
    source_audio: str | Path,
    *,
    start_s: float = 1.0,
    duration_s: float = 14.0,
) -> Path:
    """Copia/normaliza sample de voz para o catálogo local."""
    voice_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", (voice_id or "custom").strip()) or "custom"
    dest_dir = VOICES_DIR / voice_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "reference.wav"
    src = Path(source_audio)
    if not src.exists():
        raise FileNotFoundError(str(src))

    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg não encontrado no PATH")

    cmd = [
        ff, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-ss", str(max(0.0, start_s)),
        "-t", str(max(4.0, duration_s)),
        "-ac", "1", "-ar", "22050",
        "-af", "highpass=f=80,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg falhou: {proc.stderr[:300]}")
    set_active_voice(voice_id)
    return dest


def engine_status() -> Dict[str, Any]:
    xtts_ok, xtts_msg = _probe_xtts()
    ref_ok = False
    ref_path = None
    try:
        ref_path = str(resolve_reference())
        ref_ok = Path(ref_path).exists()
    except Exception as e:
        xtts_msg = f"{xtts_msg}; ref: {e}"
    loaded = _xtts is not None
    return {
        "xtts": xtts_ok,
        "xtts_loaded": loaded,
        "xtts_detail": (
            "XTTS carregado — master.wav"
            if loaded
            else xtts_msg
        ),
        "reference_ok": ref_ok,
        "reference": ref_path,
        "active_voice": get_active_voice(),
        "voices": list_voices(),
        "device": "cpu",
        "canonical_wav": str(_MASTER),
    }


def _probe_xtts() -> Tuple[bool, str]:
    global _xtts_err
    try:
        import TTS  # noqa: F401
        return True, "TTS package instalado (modelo carrega no 1º speak)"
    except Exception as e:
        _xtts_err = str(e)
        return False, f"XTTS não instalado: {e}"


def _get_xtts():
    """Lazy-load XTTS-v2 (1ª vez demora — download do modelo)."""
    global _xtts, _xtts_err
    if _xtts is not None:
        return _xtts
    with _lock:
        if _xtts is not None:
            return _xtts
        try:
            # force CPU + aceita licença CPML não-comercial automaticamente
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
            os.environ["COQUI_TOS_AGREED"] = "1"
            import builtins

            # PyTorch 2.6+ defaults weights_only=True — XTTS precisa False
            import torch
            try:
                n = int(os.cpu_count() or 4)
                torch.set_num_threads(max(2, min(n, 8)))
            except Exception:
                pass
            import soundfile as sf
            import torchaudio

            _orig_torch_load = torch.load

            def _torch_load(*args, **kwargs):
                kwargs.setdefault("weights_only", False)
                return _orig_torch_load(*args, **kwargs)

            torch.load = _torch_load  # type: ignore

            # torchaudio 2.11 exige torchcodec — usamos soundfile
            def _sf_load(path, *args, **kwargs):
                data, sr = sf.read(str(path), dtype="float32", always_2d=True)
                return torch.from_numpy(data.T.copy()), int(sr)

            torchaudio.load = _sf_load  # type: ignore

            _orig_input = builtins.input

            def _yes(_prompt: str = "") -> str:
                return "y"

            builtins.input = _yes  # type: ignore
            try:
                from TTS.api import TTS

                model = TTS(
                    model_name="tts_models/multilingual/multi-dataset/xtts_v2",
                    progress_bar=True,
                    gpu=False,
                )
            finally:
                builtins.input = _orig_input
            _xtts = model
            _xtts_err = None
            return _xtts
        except Exception as e:
            _xtts_err = str(e)
            raise RuntimeError(f"Falha ao carregar XTTS: {e}") from e


def _clean_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"#{1,6}\s+", "", t)
    t = re.sub(r"(?m)^\s*[-•*]\s+", "", t)
    t = re.sub(r"\s+", " ", t)
    # XTTS gosta de frases não gigantes
    if len(t) > 420:
        t = t[:417].rsplit(" ", 1)[0] + "..."
    return t.strip()


def _wav_bytes_from_array(wav: np.ndarray, sr: int = 22050) -> bytes:
    import soundfile as sf

    wav = np.asarray(wav, dtype=np.float32)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    # peak normalize suave
    peak = float(np.max(np.abs(wav)) or 1.0)
    if peak > 0:
        wav = wav / peak * 0.92
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _to_mp3(wav_bytes: bytes) -> bytes:
    ff = shutil.which("ffmpeg")
    if not ff or not wav_bytes:
        return wav_bytes
    try:
        with tempfile.TemporaryDirectory(prefix="vc-") as td:
            src = Path(td) / "in.wav"
            dst = Path(td) / "out.mp3"
            src.write_bytes(wav_bytes)
            cmd = [
                ff, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src),
                "-codec:a", "libmp3lame", "-b:a", "192k",
                str(dst),
            ]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 200:
                return dst.read_bytes()
    except Exception:
        pass
    return wav_bytes


def _speaker_wavs_for(voice_id: Optional[str] = None) -> list:
    """Só o arquivo chamado master.wav — o sample canônico do Thomas."""
    ref = resolve_reference(voice_id)
    vdir = ref.parent
    master = vdir / "master.wav"
    if master.exists() and master.stat().st_size > 4000:
        return [str(master)]
    if ref.exists():
        return [str(ref)]
    return []


def _median_f0(sig: np.ndarray, srate: int) -> float:
    sig = np.asarray(sig, dtype=np.float32)
    if sig.ndim > 1:
        sig = sig.mean(axis=1)
    sig = sig - float(np.mean(sig))
    hop = max(1, int(srate * 0.02))
    win = max(8, int(srate * 0.045))
    minlag, maxlag = int(srate / 280), int(srate / 70)
    f0s = []
    for i in range(0, max(0, len(sig) - win), hop):
        w = sig[i : i + win]
        if float(np.sqrt(np.mean(w * w))) < 0.02:
            continue
        c = np.correlate(w, w, mode="full")
        c = c[len(c) // 2 :]
        seg = c[minlag:maxlag]
        if len(seg) == 0:
            continue
        lag = int(np.argmax(seg)) + minlag
        if lag > 0:
            f0s.append(srate / lag)
    return float(np.median(f0s)) if f0s else 0.0


def _match_to_master(wav_bytes: bytes, master_path: Path) -> bytes:
    """Puxa pitch/loudness do XTTS para o master.wav (mesma voz, não Antonio)."""
    import soundfile as sf

    try:
        gen, gsr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    except Exception:
        return wav_bytes
    if gen.ndim > 1:
        gen = gen.mean(axis=1)
    try:
        ref, rsr = sf.read(str(master_path), dtype="float32")
    except Exception:
        return wav_bytes
    if ref.ndim > 1:
        ref = ref.mean(axis=1)
    f0_m = _median_f0(ref, rsr)
    f0_g = _median_f0(gen, gsr)
    if f0_m > 60 and f0_g > 60:
        ratio = float(np.clip(f0_m / f0_g, 0.82, 1.22))
        if abs(ratio - 1.0) >= 0.012:
            ff = shutil.which("ffmpeg")
            if ff:
                try:
                    with tempfile.TemporaryDirectory(prefix="pitch-") as td:
                        src = Path(td) / "in.wav"
                        dst = Path(td) / "out.wav"
                        sf.write(str(src), gen, gsr, subtype="PCM_16")
                        new_rate = max(8000, int(gsr * ratio))
                        subprocess.run(
                            [
                                ff, "-y", "-hide_banner", "-loglevel", "error",
                                "-i", str(src),
                                "-af", f"asetrate={new_rate},aresample={gsr}",
                                str(dst),
                            ],
                            check=False,
                            timeout=20,
                        )
                        if dst.exists() and dst.stat().st_size > 200:
                            gen2, _ = sf.read(str(dst), dtype="float32")
                            if gen2.ndim > 1:
                                gen2 = gen2.mean(axis=1)
                            gen = gen2
                except Exception:
                    pass
            else:
                try:
                    import librosa

                    semis = 12.0 * np.log2(ratio)
                    gen = librosa.effects.pitch_shift(gen, sr=gsr, n_steps=float(semis))
                except Exception:
                    pass
    rms_m = float(np.sqrt(np.mean(ref * ref)) or 0.1)
    rms_g = float(np.sqrt(np.mean(gen * gen)) or 0.1)
    gen = gen * float(np.clip(rms_m / rms_g, 0.55, 1.8))
    peak = float(np.max(np.abs(gen)) or 1.0)
    if peak > 0.95:
        gen = gen / peak * 0.92
    return _wav_bytes_from_array(gen, gsr)


def _get_f5():
    """F5-TTS — clona o master.wav com fidelidade bem maior que XTTS."""
    global _f5, _f5_err, _f5_ref_text, _f5_ref_wav
    if _f5 is not None:
        return _f5
    with _lock:
        if _f5 is not None:
            return _f5
        try:
            from f5_tts.api import F5TTS
            import soundfile as sf

            _f5 = F5TTS(device="cpu")
            master = DEFAULT_REF if DEFAULT_REF.exists() else (VOICES_DIR / DEFAULT_VOICE_ID / "master.wav")
            txtp = master.parent / "master.txt"
            if txtp.exists():
                _f5_ref_text = txtp.read_text(encoding="utf-8").strip()
            else:
                _f5_ref_text = "Exatamente chefe."
            # F5 clona melhor com 8–15s do próprio master.wav
            x, sr = sf.read(str(master), dtype="float32")
            if x.ndim > 1:
                x = x.mean(axis=1)
            n = min(len(x), int(sr * 12))
            clip = master.parent / "_f5_from_master.wav"
            sf.write(str(clip), x[:n], sr, subtype="PCM_16")
            _f5_ref_wav = str(clip)
            print(f"[f5] pronto ref={clip.name} text={_f5_ref_text[:80]!r}")
            return _f5
        except Exception as e:
            _f5_err = str(e)
            print(f"[f5] load fail: {e}")
            raise


def _speak_f5(text: str, ref: Path) -> Tuple[bytes, str]:
    model = _get_f5()
    wav, sr, _spec = model.infer(
        ref_file=_f5_ref_wav or str(ref),
        ref_text=_f5_ref_text or "",
        gen_text=text,
        nfe_step=32,
        speed=1.0,
        cfg_strength=2,
        remove_silence=True,
        show_info=lambda *_a, **_k: None,
    )
    audio = np.asarray(wav, dtype=np.float32).squeeze()
    sr = int(sr or 24000)
    raw = _wav_bytes_from_array(audio, sr)
    master = VOICES_DIR / DEFAULT_VOICE_ID / "master.wav"
    matched = _match_to_master(raw, master if master.exists() else Path(ref))
    return matched, "f5-tts-master.wav"


def _get_xtts_latents():
    """Latents 1x: Coqui recomenda 6s do sample — o arquivo continua master.wav."""
    global _xtts_latents
    if _xtts_latents is not None:
        return _xtts_latents
    model = _get_xtts()
    tts_model = model.synthesizer.tts_model
    master = str(_MASTER if _MASTER.exists() else resolve_reference())
    with _lock:
        if _xtts_latents is not None:
            return _xtts_latents
        gpt, emb = tts_model.get_conditioning_latents(
            audio_path=[master],
            gpt_cond_len=6,
            gpt_cond_chunk_len=6,
            max_ref_length=8,
            sound_norm_refs=True,
        )
        _xtts_latents = (gpt, emb)
        print("[xtts] latents em cache (6s do master.wav — padrao Coqui)")
    return _xtts_latents


def _wav_from_xtts_out(wav, tts_model) -> bytes:
    audio = wav
    if isinstance(wav, dict):
        audio = wav.get("wav")
        if audio is None:
            audio = wav.get("audio")
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    audio = np.asarray(audio, dtype=np.float32).squeeze()
    sr = int(getattr(tts_model, "output_sample_rate", None) or 24000)
    return _wav_bytes_from_array(audio, sr)


def _speak_xtts(text: str, ref: Path) -> Tuple[bytes, str]:
    """XTTS rapido: latents cacheados + 6s do master.wav (nao 47s a cada frase)."""
    key = text.strip().lower()
    hit = _tts_cache.get(key)
    if hit:
        return hit[0], hit[1] + "+cache"

    model = _get_xtts()
    tts_model = model.synthesizer.tts_model
    gpt, emb = _get_xtts_latents()
    split = len(text) > 80
    try:
        wav = tts_model.inference(
            text=text,
            language="pt",
            gpt_cond_latent=gpt,
            speaker_embedding=emb,
            temperature=0.2,
            length_penalty=1.0,
            repetition_penalty=5.0,
            top_k=30,
            top_p=0.7,
            speed=1.0,
            enable_text_splitting=split,
        )
        raw = _wav_from_xtts_out(wav, tts_model)
        used = "infer-6s-cached"
    except Exception as e:
        print(f"[xtts] infer rapido falhou, tts_to_file: {e}")
        with tempfile.TemporaryDirectory(prefix="xtts-") as td:
            out = Path(td) / "out.wav"
            model.tts_to_file(
                text=text,
                file_path=str(out),
                speaker_wav=str(_MASTER if _MASTER.exists() else ref),
                language="pt",
                split_sentences=split,
            )
            if not out.exists() or out.stat().st_size < 200:
                raise RuntimeError("XTTS gerou arquivo vazio")
            raw = out.read_bytes()
        used = "tts_to_file"

    if len(_tts_cache) >= _TTS_CACHE_MAX:
        try:
            _tts_cache.pop(next(iter(_tts_cache)))
        except Exception:
            _tts_cache.clear()
    label = f"xtts-v2-thomas-master(master.wav+{used})"
    _tts_cache[key] = (raw, label)
    return raw, label


async def _speak_edge_morph(text: str, ref: Path) -> Tuple[bytes, str]:
    """Fallback: Edge Antonio + match de pitch mediano do sample de referência."""
    import edge_tts
    import soundfile as sf

    # 1) sintetiza base com parâmetros mais naturais
    # rate -3% = levemente mais lento = mais natural
    # pitch -4Hz = mais grave = mais próximo de voz masculina madura
    communicate = edge_tts.Communicate(text, "pt-BR-AntonioNeural", rate="-3%", pitch="-4Hz")
    chunks = []
    async for ch in communicate.stream():
        if ch["type"] == "audio":
            chunks.append(ch["data"])
    mp3 = b"".join(chunks)
    if len(mp3) < 200:
        raise RuntimeError("Edge TTS vazio")

    # 2) decode para wav via ffmpeg
    ff = shutil.which("ffmpeg")
    if not ff:
        return mp3, "edge-antonio"

    with tempfile.TemporaryDirectory(prefix="morph-") as td:
        src_mp3 = Path(td) / "edge.mp3"
        base_wav = Path(td) / "base.wav"
        out_wav = Path(td) / "out.wav"
        src_mp3.write_bytes(mp3)
        subprocess.run(
            [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src_mp3),
             "-ac", "1", "-ar", "22050", str(base_wav)],
            check=False,
        )
        if not base_wav.exists():
            return mp3, "edge-antonio"

        base, sr = sf.read(str(base_wav), dtype="float32")
        ref_audio, ref_sr = sf.read(str(ref), dtype="float32")
        if ref_audio.ndim > 1:
            ref_audio = ref_audio.mean(axis=1)
        if base.ndim > 1:
            base = base.mean(axis=1)

        # pitch match aproximado (mediana de pitch via autocorrelation simplificada)
        def median_f0(x: np.ndarray, srate: int) -> float:
            x = x - np.mean(x)
            if len(x) < srate // 2:
                return 0.0
            # janela central
            mid = len(x) // 2
            w = x[max(0, mid - srate): mid + srate]
            if len(w) < 2048:
                return 0.0
            corr = np.correlate(w, w, mode="full")
            corr = corr[len(corr) // 2:]
            # busca período 60–250 Hz
            min_lag = int(srate / 250)
            max_lag = int(srate / 60)
            seg = corr[min_lag:max_lag]
            if len(seg) == 0:
                return 0.0
            lag = int(np.argmax(seg)) + min_lag
            return float(srate / lag) if lag > 0 else 0.0

        f0_ref = median_f0(ref_audio, ref_sr)
        f0_base = median_f0(base, sr)
        semis = 0.0
        if f0_ref > 40 and f0_base > 40:
            semis = 12.0 * np.log2(f0_ref / f0_base)
            semis = float(np.clip(semis, -6.0, 6.0))

        # aplica pitch_shift se librosa disponível
        try:
            import librosa

            if abs(semis) >= 0.3:
                base = librosa.effects.pitch_shift(base, sr=sr, n_steps=semis)
        except Exception:
            pass

        # equalização suave de loudness + timbre (matching RMS do ref)
        def rms(x: np.ndarray) -> float:
            return float(np.sqrt(np.mean(np.square(x)) + 1e-12))

        r_ref = rms(ref_audio)
        r_base = rms(base)
        if r_base > 0:
            base = base * (r_ref / r_base) * 0.95

        # filtro de presença (aproxima brilho do sample) - mais suave
        try:
            from scipy.signal import butter, filtfilt

            b, a = butter(2, [100 / (sr / 2), 4500 / (sr / 2)], btype="band")
            shaped = filtfilt(b, a, base)
            base = 0.8 * base + 0.2 * shaped
        except Exception:
            pass

        # compressão suave para dinâmica mais natural
        peak = float(np.max(np.abs(base)) or 1.0)
        base = base / peak * 0.9
        sf.write(str(out_wav), base.astype(np.float32), sr)
        wav_bytes = out_wav.read_bytes()
        return wav_bytes, f"edge-morph-hq(semis={semis:.1f})"


def speak_sync(
    text: str,
    *,
    voice_id: Optional[str] = None,
    prefer: str = "xtts",
    as_mp3: bool = True,
    hq: bool = False,
) -> Tuple[bytes, str]:
    """Sintetiza texto na voz clonada. Retorna (audio_bytes, engine_label).

    prefer padrão = xtts (clone real do sample Thomas). Edge só se XTTS falhar
    e prefer=auto/fast — Edge NÃO soa como Thomas.
    
    hq=True = usa parâmetros de alta qualidade (temperature 0.4, mais clips de referência)
    """
    cleaned = _clean_text(text)
    if not cleaned:
        return b"", "empty"
    ref = resolve_reference(voice_id)
    prefer = (prefer or "xtts").lower()
    if prefer in ("auto", "clone", "thomas", "perfect", "hq"):
        prefer = "xtts"

    errors = []

    # F5-TTS só se pedido explícito (muito lento em CPU).
    if prefer == "f5":
        try:
            wav, eng = _speak_f5(cleaned, ref)
            audio = _to_mp3(wav) if as_mp3 else wav
            return audio, eng
        except Exception as e:
            errors.append(f"f5: {e}")
            print(f"[clone] F5 falhou, tentando XTTS: {e}")
            prefer = "xtts"

    # XTTS — rápido o bastante para o JARVIS falar sem travar
    if prefer in ("xtts", "auto", "clone"):
        try:
            wav, eng = _speak_xtts(cleaned, ref)
            audio = _to_mp3(wav) if as_mp3 else wav
            return audio, eng
        except Exception as e:
            errors.append(f"xtts: {e}")
            if prefer == "xtts":
                # tenta uma vez com reference principal só
                try:
                    wav, eng = _speak_xtts(cleaned, ref)
                    audio = _to_mp3(wav) if as_mp3 else wav
                    return audio, eng + "-retry"
                except Exception as e2:
                    errors.append(f"xtts-retry: {e2}")
                    raise RuntimeError("Clone XTTS falhou: " + " | ".join(errors)) from e2

    # 2) Edge morph — só sob pedido explícito (NÃO é Thomas)
    if prefer in ("edge", "morph", "fast"):
        try:
            import asyncio

            wav, eng = asyncio.run(_speak_edge_morph(cleaned, ref))
            if as_mp3 and wav[:4] == b"RIFF":
                audio = _to_mp3(wav)
            else:
                audio = wav
            if as_mp3 and audio[:4] == b"RIFF":
                audio = _to_mp3(audio)
            return audio, eng
        except Exception as e:
            errors.append(f"edge: {e}")

    raise RuntimeError("Clone falhou: " + " | ".join(errors))


async def speak_async(
    text: str,
    *,
    voice_id: Optional[str] = None,
    prefer: str = "xtts",
    as_mp3: bool = True,
    hq: bool = False,
) -> Tuple[bytes, str]:
    """Mesmo caminho do speak_sync — XTTS + master.wav. F5 só se prefer=f5."""
    import asyncio

    prefer = (prefer or "xtts").lower()
    if prefer in ("auto", "clone", "thomas", "perfect", "hq", "jarvis"):
        prefer = "xtts"
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: speak_sync(
            text, voice_id=voice_id, prefer=prefer, as_mp3=as_mp3, hq=hq
        ),
    )
