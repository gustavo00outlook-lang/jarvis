# JARVIS — Inventário Completo (v22 Huw)

> **Atualizado:** 2026-06-19 | **Estado:** 100% operacional + snapshot canonico
> **Código fonte:** `C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro`
> **Runtime:** `C:\Users\Micro\.hermes\`
> **Obsidian:** `C:\Agencia calango\calango.studio\JARVIS`

---

## 1. Pastas principais

| Pasta | Função |
|-------|--------|
| `jarvis-pro/` | Projeto Next.js + FastAPI (código ativo) |
| `jarvis-pro/src/` | Frontend React/Next.js |
| `jarvis-pro/backend/` | Backend Python FastAPI + agente Grok |
| `jarvis-pro/public/` | Assets estáticos + referências HTML |
| `jarvis-pro/scripts/` | Scripts de captura, testes, galeria |
| `jarvis-pro/referencia/` | Scripts Instagram/Huw referência |
| `jarvis-pro/.vscode/` | Tasks VS Code (build, launch) |
| `C:\Users\Micro\JARVIS\` | **Arquivo mestre** (esta pasta — evolução preservada) |
| `C:\Agencia calango\calango.studio\JARVIS\` | Vault Obsidian (memória permanente) |
| `C:\Users\Micro\.hermes\` | Estado runtime, voz, credenciais, pending |
| `C:\Users\Micro\JARVIS\snapshots\2026-06-19\` | **Snapshot canonico** — restore: `restaurar jarvis 19-06` |

---

## 2. Frontend — `src/`

### App & rotas
| Arquivo | Função |
|---------|--------|
| `src/app/page.tsx` | UI principal — monta `WhatsAppJarvisScreen` |
| `src/app/layout.tsx` | Layout root Next.js |
| `src/app/globals.css` | Estilos globais, dock Huw, painéis GPU |
| `src/app/orb-gallery/page.tsx` | Galeria de variantes do orb |

### API routes (TTS proxy)
| Arquivo | Função |
|---------|--------|
| `src/app/api/speak/fish/route.ts` | Proxy Fish Audio TTS (Thomas) |
| `src/app/api/speak/status/route.ts` | Status motores TTS disponíveis |
| `src/app/api/speak/sample/route.ts` | Sample MP3 boot/greeting |
| `src/app/api/speak/edge/route.ts` | Fallback Edge TTS |
| `src/app/api/speak/xai/route.ts` | Fallback xAI TTS |
| `src/app/api/speak/elevenlabs/route.ts` | Fallback ElevenLabs |

### UI v22 Huw (ativa)
| Arquivo | Função |
|---------|--------|
| `src/components/whatsapp/WhatsAppJarvisScreen.tsx` | Tela principal `data-jarvis-ui="wa-v22-huw"` |
| `src/components/whatsapp/JarvisInputBar.tsx` | Dock centro: mic + teclado; mic 2,5s silêncio |
| `src/components/hud/GoogleSidePanel.tsx` | Painel Google com screenshot Playwright |
| `src/components/hud/OperPanels.tsx` | Wrapper painéis laterais + ticker |
| `src/components/hud/OperStatusTicker.tsx` | Ticker de status à direita |
| `src/components/hud/Caption.tsx` | Legenda das falas do JARVIS |
| `src/components/hud/ChatWidget.tsx` | Widget chat (legado/auxiliar) |
| `src/components/hud/MusicWidget.tsx` | Card Thunderstruck AC/DC |
| `src/components/hud/SuggestionPanels.tsx` | Painéis "I can help..." |
| `src/components/hud/Grid.tsx` | Grid de fundo holográfico |
| `src/components/hud/ActivityPanel.tsx` | Painel de atividade |
| `src/components/hud/VoiceSelector.tsx` | Seletor de voz |
| `src/components/hud/JarvisLabel.tsx` | Label JARVIS |

### Orb (canvas)
| Arquivo | Função |
|---------|--------|
| `src/components/orb/OrbWhatsAppCanvas.tsx` | Orb ativo na UI v22 |
| `src/components/orb/orbScannerHuw.ts` | Animação riscos Huw (GPU) |
| `src/components/orb/jarvisOrbLabel.ts` | Texto JARVIS no canvas |
| `src/components/Orb2D.tsx` | Orb 2D legado + estados vermelho confirmação |
| `src/components/orb/OrbHuwCanvas.tsx` | Variante Huw |
| `src/components/orb/OrbHudV4Canvas.tsx` | Variante HUD v4 |
| `src/components/orb/JarvisRingOrb.tsx` | Anel ciano |
| `src/components/orb/ParticleOrb.tsx` | Orb partículas |
| `src/components/orb/HuwprosserOrb.tsx` | Ref. huwprosser |
| `src/components/orb/JarvisOrb.tsx` | Orb 3D base |
| `src/components/orb/OrbRings.tsx` | Anéis concêntricos |
| `src/components/orb/OrbParticles.tsx` | Partículas |
| `src/components/orb/HudOrb.tsx` | Orb HUD |
| `src/components/orb/JarvisHudScreen.tsx` | Tela HUD |
| `src/components/orb/JarvisHudOperScreen.tsx` | Tela operacional |
| `src/components/orb/HuwprosserScreen.tsx` | Tela huwprosser |
| `src/components/orb/JarvisClockScreen.tsx` | Tela relógio |
| `src/components/JarvisScene.tsx` | Cena 3D |
| `src/components/Jarvis3DCore.tsx` | Core Three.js |
| `src/components/OrbPostProcessing.tsx` | Pós-processamento bloom |
| `src/shaders/orb.vert.glsl` | Vertex shader orb |
| `src/shaders/orb.frag.glsl` | Fragment shader orb |

### Libs (estado, WS, voz)
| Arquivo | Função |
|---------|--------|
| `src/lib/state.ts` | Zustand store (orb, browser, confirmação, caption) |
| `src/lib/ws.ts` | WebSocket client + narração contínua |
| `src/lib/tts.ts` | Cadeia TTS: Fish → Edge → browser |
| `src/lib/speechMic.ts` | Web Speech API + anti-eco TTS |
| `src/types/speech.d.ts` | Tipos Web Speech |

---

## 3. Backend — `backend/`

### Core
| Arquivo | Função |
|---------|--------|
| `main.py` | FastAPI: `/api/jarvis/chat`, `/ws`, TTS, confirmação |
| `jarvis_agent.py` | Agente Grok: fast-path, 30 tools, 12 rounds |
| `xai_client.py` | Cliente xAI centralizado (modelos fast/smart) |
| `conversation_state.py` | Histórico, prefs, response_id chaining |
| `pending_state.py` | Ações de risco pendentes (JSON + TTL) |
| `jarvis_memory.py` | Memória runtime + contexto Obsidian |
| `obsidian_notes.py` | CRUD notas vault Obsidian |
| `intent_resolver.py` | Fast-path ações (browse, apps, sites) |

### xAI 5 Fases
| Arquivo | Função |
|---------|--------|
| `xai_reasoning.py` | Fase 1: Deep Reasoning streaming |
| `xai_structured_action.py` | Fase 2: Ações estruturadas |
| `xai_tools.py` | Fase 4: web_search + x_search |
| `xai_tts.py` | Fase 5: TTS xAI |
| `action_schema.py` | Schema Pydantic ações |
| `structured_to_legacy.py` | Conversor structured → legacy |

### PC Control & Browser
| Arquivo | Função |
|---------|--------|
| `actions.py` | Executa ações Windows (volume, apps, notas) |
| `desktop_control.py` | Visão de tela: look_at, watch, click, type |
| `web_browser.py` | Playwright: browse_open, screenshot, preview WS |

### Voz
| Arquivo | Função |
|---------|--------|
| `fish_tts.py` | Fish Audio TTS Thomas (volume 3, s2-pro) |
| `edge_tts_jarvis.py` | Fallback Edge Antonio |
| `clone_fish_voice.py` | Clonar voz Fish do sample |
| `connect_fish_voice.py` | Conectar voz ao team Fish |
| `setup_fish_team.py` | Setup API key Fish |
| `extract_thomas_sample.py` | Extrair trechos Thomas do voice_sample |
| `find_thomas_in_voice_sample.py` | Análise whisper Thomas vs humano |
| `clone_jarvis_voice.py` | Clone xAI voice |

### Design & Credenciais
| Arquivo | Função |
|---------|--------|
| `jarvis_design_memory.py` | Memória design PhD + Calango Studio |
| `jarvis_credentials.py` | Credenciais locais (jarvis_secrets.json) |
| `vault_reorganize.py` | Reorganizar vault Obsidian |
| `vault_consolidate.py` | Consolidar duplicatas vault |

### Scripts auxiliares
| Arquivo | Função |
|---------|--------|
| `scripts/explore_studio.py` | Explorar Calango Studio |
| `diag_voice.py` | Diagnóstico voz |
| `diag_edge.py` | Diagnóstico Edge TTS |
| `requirements.txt` | Dependências Python |

---

## 4. Scripts de launch

| Arquivo | Função |
|---------|--------|
| `START_JARVIS.bat` | Launch backend + frontend (mata :8000 e :3000 duplicados) |
| `CLEAN_RESTART.bat` | Apaga `.next` + reinicia |
| `ABRIR_JARVIS.bat` | Abre browser em :3000 |
| `START_FRONTEND.bat` | Só frontend |
| `FIX_NEXT.bat` | Fix cache Next.js |
| `CONECTAR_FISH_JARVIS.bat` | Conectar Fish TTS |

---

## 5. Runtime — `C:\Users\Micro\.hermes\`

| Arquivo/Pasta | Função |
|---------------|--------|
| `jarvis_conversation_state.json` | Histórico + prefs runtime |
| `jarvis_pending_action.json` | Ação de risco pendente |
| `fish_voice_id.json` | ID voz Fish Thomas clonada |
| `jarvis_secrets.json` | Credenciais (NÃO copiar para vault) |
| `xai_api_key` / env | Chave xAI Grok |

---

## 6. Obsidian vault — estrutura

| Pasta | Conteúdo |
|-------|----------|
| `memoria/Conversas/` | Auto-save cada turno |
| `memoria/Ensinando-JARVIS/` | O que Gustavo ensina |
| `memoria/Aprendizado/` | Pesquisas web + Calango |
| `memoria/Design/` | Design PhD + Studio |
| `memoria/Reflexões/` | Auto-reflexão pós-tools |
| `docs/` | Sessões de dev datadas |
| `reviews/` | Browser reviews + screenshots |
| `recordings/` | MP4 referência 2026-06-09 |
| `screenshots/` | Frames da gravação canônica |
| `assets/` | Samples voz, refs visuais |

### Docs-chave
- `00-INDEX.md` — MOC central
- `LIVE_CHANGES.md` — Log ao vivo
- `01-GROK-BUILD-STATUS.md` — Estado 5 fases
- `SHARED_CONTEXT.md` — Contexto Claude ↔ Grok
- `TAG-LEGEND.md` — Cores do grafo

---

## 7. Tools do agente (30)

**Browser:** `browse_open`, `browse_click`, `browse_type`, `browse_scroll`, `browse_press_key`, `browse_close`, `browse_carousel_slide`

**Desktop:** `look_at_screen`, `watch_screen`, `desktop_click`, `desktop_type`, `desktop_press`, `desktop_scroll`, `desktop_move`

**PC:** `open_app`, `close_app`, `run_command`, `set_volume`, `media_control`, `system_status`

**Memória:** `search_obsidian`, `write_obsidian_note`, `teach_jarvis`, `study_topic`, `save_design_knowledge`

**Web:** `web_search`, `x_search` (nativos Grok)

**Risco (confirmação vermelha):** `run_command`, `close_app`

---

## 8. WebSocket eventos

| Evento | Payload |
|--------|---------|
| `state` | idle / listening / thinking / speaking |
| `browser_preview` | screenshot base64 + URL |
| `jarvis_narration` | Texto narração ao vivo |
| `tool_call` | Tool em execução |
| `action_requires_confirmation` | Barra vermelha |
| `caption` | Legenda TTS |
| `agent_thought` | Pensamento streaming |

---

## 9. UI v22 — especificações

- **Dock:** centro inferior, 2 ícones (mic + teclado)
- **Mic:** envia após 2500ms silêncio; pausa durante TTS (`jarvis:tts-start/end`)
- **Orb:** `OrbWhatsAppCanvas` + `orbScannerHuw`, GPU `translate3d`
- **Painel Google:** 62vw, animação Huw estável, sem re-trigger em screenshot
- **Voz:** Fish Thomas, prosody volume 3, HTMLAudio único (sem eco)
- **Confirmação:** barra vermelha `#ff4444`, orb borda vermelha em pending

---

## 10. Testes validados (2026-06-18)

| Teste | Resultado |
|-------|-----------|
| `tsc --noEmit` | PASS |
| `npm run build` | PASS |
| Porta 3000 única | PASS |
| Porta 8000 única | PASS |
| Chat "oi" | PASS (canned) |
| Chat "oi jarvis" | PASS (sem enrich) |
| Google `browse_open` | PASS (~93KB screenshot) |
| Memória Obsidian | PASS |
| Fish TTS status | PASS |

---

## 11. Regras de ouro (não quebrar)

1. **Um backend** na :8000 — `START_JARVIS.bat` mata duplicados
2. **Google** sempre `browse_open` (Playwright), nunca Chrome externo
3. **`.next` corrompido** → `CLEAN_RESTART.bat`
4. **Painel Google** — não re-animar em cada screenshot update
5. **TTS** — um HTMLAudio; mic pausa no `jarvis:tts-start`
6. **Saudações** — `_is_pure_greeting()` sem memória Obsidian nem enrich

---

*Arquivo mestre em `C:\Users\Micro\JARVIS` — sincronizar com Obsidian após cada sessão.*