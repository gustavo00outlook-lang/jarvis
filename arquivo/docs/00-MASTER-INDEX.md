# JARVIS — Índice Mestre do Projeto

> Última atualização: 2026-06-18 | Estado: **v22 Huw dock**

## Pastas neste PC

| Pasta | Conteúdo |
|-------|----------|
| `C:\Users\Micro\JARVIS\` | Este índice + docs locais |
| `C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro\` | **Código fonte** (Next.js + FastAPI) |
| `C:\Agencia calango\calango.studio\JARVIS\` | **Obsidian vault** (memória, reviews, sessões) |
| `C:\Users\Micro\.hermes\` | Voz Fish, credenciais, estado conversa |

## Como iniciar

```bat
cd C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro
START_JARVIS.bat
```

- Frontend: http://localhost:3000
- Backend: http://127.0.0.1:8000
- WebSocket: ws://127.0.0.1:8000/ws

## UI v22 (estilo @huwprosser)

- Orb central idle → dock canto ao executar/pesquisar
- **Dock inferior centro:** só 2 ícones (microfone + teclado)
- Mic: envio automático após **2,5s de silêncio**
- Painel Google embutido à esquerda (screenshot live)
- Animações GPU (`translate3d`, `will-change`, `contain`)

## Voz Thomas/JARVIS

- Motor: Fish Audio s2-pro (clone Thomas)
- Volume Fish prosody: **3** (mais alto)
- HTMLAudio seco, sem Web Audio routing (sem eco)
- Mic pausa durante TTS (`jarvis:tts-start/end`)

## Memória

- Runtime: `C:\Users\Micro\.hermes\jarvis_conversation_state.json`
- Obsidian: `memoria/Conversas/`, `Ensinando-JARVIS/`, `Aprendizado/`
- Toda conversa auto-salva no vault

## Arquivos críticos (não quebrar)

| Arquivo | Função |
|---------|--------|
| `src/components/whatsapp/WhatsAppJarvisScreen.tsx` | Tela principal |
| `src/components/whatsapp/JarvisInputBar.tsx` | Dock Huw mic/teclado |
| `src/components/hud/GoogleSidePanel.tsx` | Painel browser |
| `src/lib/speechMic.ts` | Microfone Web Speech |
| `src/lib/tts.ts` | Voz Fish sem eco |
| `src/lib/ws.ts` | WebSocket + narração |
| `backend/jarvis_agent.py` | Agente Grok + tools |
| `backend/fish_tts.py` | TTS Thomas |
| `backend/obsidian_notes.py` | Memória vault |

## Referência visual

- Vídeo canônico: `JARVIS/recordings/jarvis-ui-demo-2026-06-09.mp4`
- WhatsApp Huw: `JARVIS/recordings/whatsapp-video-2026-06-16-23-25-08.mp4`
- Instagram: @huwprosser

## Histórico de sessões

Ver Obsidian: `LIVE_CHANGES.md` e `docs/2026-06-18-revisao-completa-v22.md`