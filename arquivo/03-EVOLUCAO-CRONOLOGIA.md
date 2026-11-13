# JARVIS — Cronologia da evolução

## 2026-06-09 — Visual canônico
- Orb ciano + JARVIS no centro, grid escuro, estilo Homem de Ferro
- Gravação: `JARVIS/recordings/jarvis-ui-demo-2026-06-09.mp4`

## 2026-06-11–16 — UI WhatsApp + Huw
- Layout estilo vídeo WhatsApp (`wa-v21`)
- Referência @huwprosser — orb scanner, paleta `#00d4ff`
- Voz Thomas via Fish Audio clone

## 2026-06-17 — Operação + memória
- Painel Google embutido (62vw, screenshot live)
- Orb dock canto, risco amarelo ao pesquisar
- Auto-save conversas Obsidian
- Exploração multi-passo + narração ao vivo
- Design Senior PhD + Calango Studio

## 2026-06-18 — v22 100%
- **Dock Huw** — só mic + teclado centro inferior
- Mic envia após 2,5s silêncio, pausa durante TTS
- Voz volume 3, sem eco
- `browse_open` para Google (screenshot real, não Chrome externo)
- Fix webpack `.next` + backend duplicado :8000
- Pasta mestre `C:\Users\Micro\JARVIS`
- Testes 7/7 PASS + build OK

## Arquivos críticos (nunca perder)

| Arquivo | Por quê |
|---------|---------|
| `WhatsAppJarvisScreen.tsx` | UI principal |
| `JarvisInputBar.tsx` | Dock + mic |
| `GoogleSidePanel.tsx` | Painel browser |
| `jarvis_agent.py` | Cérebro |
| `web_browser.py` | Playwright |
| `obsidian_notes.py` | Memória |
| `fish_tts.py` | Voz Thomas |
| `tts.ts` / `speechMic.ts` | Frontend voz/mic |
| `globals.css` | Animações Huw |

## Vault Obsidian — sessões importantes

- `LIVE_CHANGES.md` — log vivo
- `docs/2026-06-18-jarvis-100-master-archive.md` — arquivo mestre
- `docs/2026-06-18-revisao-completa-v22.md`
- `docs/2026-06-18-conversa-live-analise.md`