# JARVIS — Arquitetura v22

```
┌─────────────────────────────────────────────────────────┐
│  Browser localhost:3000                                  │
│  WhatsAppJarvisScreen (data-jarvis-ui=wa-v22-huw)       │
│    ├─ OrbWhatsAppCanvas (orbScannerHuw)                 │
│    ├─ OperPanels → GoogleSidePanel + OperStatusTicker    │
│    └─ JarvisInputBar (dock mic + teclado)               │
│         ├─ speechMic.ts (Web Speech, 2.5s silêncio)    │
│         └─ tts.ts → /api/speak/fish (Thomas)            │
└────────────────────┬────────────────────────────────────┘
                     │ WS ws://127.0.0.1:8000/ws
                     │ POST /api/jarvis/chat
┌────────────────────▼────────────────────────────────────┐
│  FastAPI main.py :8000                                   │
│    jarvis_agent.run_agent_turn()                        │
│      ├─ fast-path browse_open (Google/sites)            │
│      ├─ fast conversation (saudações + memória)         │
│      └─ Grok loop (30 tools, 12 rounds)                 │
│           ├─ web_browser.py (Playwright → painel)       │
│           ├─ obsidian_notes.py (memória vault)          │
│           ├─ fish_tts.py (voz Thomas)                   │
│           └─ actions.py (PC Windows)                    │
└─────────────────────────────────────────────────────────┘
```

## Memória (3 camadas)

1. **Runtime** — `C:\Users\Micro\.hermes\jarvis_conversation_state.json`
2. **Obsidian** — `JARVIS/memoria/Conversas/`, `Ensinando-JARVIS/`, `Aprendizado/`
3. **Confirmação** — `jarvis_pending_action.json` (ações de risco)

## Eventos WebSocket principais

- `state` — idle/listening/thinking/speaking
- `browser_preview` — screenshot + URL no painel
- `jarvis_narration` — JARVIS fala o que aprende
- `tool_call` — status execução
- `action_requires_confirmation` — barra vermelha