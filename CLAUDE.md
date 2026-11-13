# JARVIS Pro — Claude Code Context

## Projeto
**JARVIS Pro** — assistente pessoal Iron Man do Gustavo.
Stack: Next.js 15 + FastAPI + xAI Grok (grok-4.3) | 5 fases ativas.

## Iniciar
```batch
START_JARVIS.bat
```
- Backend: `http://127.0.0.1:8000`
- Frontend: `http://localhost:3000`

## Arquivos críticos
| Arquivo | Papel |
|---|---|
| `backend/xai_client.py` | Cliente Grok centralizado — `GROK_MODEL = "grok-4.3"` |
| `backend/main.py` | Todos os endpoints FastAPI + WebSocket |
| `src/app/page.tsx` | UI principal (HermesChatInput, Orb, HUD) |
| `src/components/Orb2D.tsx` | Orb animado — `#ff4444` no confirmationPending |
| `src/lib/state.ts` | Zustand: idle/listening/thinking/speaking |
| `next.config.js` | Proxy `/api/*` → FastAPI |

## 5 Fases Grok
| Fase | Módulo | Endpoint |
|---|---|---|
| 1 Deep Reasoning | `xai_reasoning.py` | `POST /api/hermes/reason` |
| 2 Ações estruturadas | `xai_structured_action.py` | `POST /api/hermes/action` |
| 3 Conversation chain | `conversation_state.py` | `POST /api/conversation/reset` |
| 4 Native tools | `xai_tools.py` | `POST /api/tools/search` |
| 5 TTS xAI | `xai_tts.py` | `POST /api/speak/xai` |

## Contexto compartilhado com Grok
Antes de começar qualquer sessão de desenvolvimento, leia:
```
C:\Agencia calango\calango.studio\JARVIS\SHARED_CONTEXT.md
```
Este arquivo é o ponto de encontro entre Claude Code e o Grok CLI.
Quando fizer mudanças importantes, atualize o bloco `## Último Update Claude Code`.

## Protocolo de consulta entre agentes
- Se precisar saber o que Grok fez recentemente → leia `SHARED_CONTEXT.md` bloco `## Último Update Grok`
- Se o Grok precisar saber o que Claude Code fez → ele lê `SHARED_CONTEXT.md` bloco `## Último Update Claude Code`
- Para mudanças de arquitetura → atualize `JARVIS/01-GROK-BUILD-STATUS.md` no vault

## Vault Obsidian
```
C:\Agencia calango\calango.studio\
├── JARVIS/00-INDEX.md          ← MOC principal
├── JARVIS/01-GROK-BUILD-STATUS.md
├── JARVIS/02-CLAUDE-GROK-WORKFLOW.md
├── JARVIS/SHARED_CONTEXT.md    ← LEIA AQUI (contexto compartilhado)
└── cerebro/jarvis/RETOMAR_AQUI.md
```

## Memória Claude Code
Arquivos de memória persistente em:
`C:\Users\Micro\.claude\projects\c--Users-Micro-Documents-Claude-Projects-Jarvis-jarvis-pro\memory\`
- `project_jarvis.md` — stack completo
- `project_obelidain.md` — vault + neurônios
- `feedback_grok_build.md` — preferências do Gustavo

## Chave API
`XAI_API_KEY` — lida de `C:\Users\Micro\.hermes\.env` ou `grok.txt` por `xai_client.py`.
Nunca hardcode. Nunca commite.

## Estilo de código
- Sem comentários óbvios. Comentário só quando o WHY não é claro.
- Sem imports não usados. Sem código morto.
- Python: async/await, type hints, Pydantic para schemas.
- TypeScript: sem `any`. Componentes funcionais.

## CLAUDE.md 3 camadas (Central Felipe Tâmbara)
| Camada | Arquivo | Escopo |
|--------|---------|--------|
| Computer | `~/.claude/CLAUDE.md` | Todos os projetos do Gustavo |
| Project | `jarvis-pro/CLAUDE.md` | Este repo |
| Folder | `backend/CLAUDE.md` ou subpastas | Regras locais |

Regras: específico > vago; <200 linhas; sem repetir regra entre camadas.

## Stack aplicada (Central Felipe Tâmbara)
- **Agentes:** 166 AIOS+Xquads + tools `weekly_vault_review`, `vault_cleanup`, `security_audit`
- **Segundo cérebro:** vault `C:\Agencia calango\calango.studio\JARVIS\cerebro\`
- **Voz:** Eleven pt-dubbed primária; Voicebox local documentado em `voice_prefs.py`
- **Browser QA:** dev-browser + browser-review (playwright-mcp pattern)
- **Segurança:** `backend/jarvis_security.py` — auditoria chaves
- **Executor:** `.claude/agents/executor.md` — loop Fable 5 (planeja forte → executa barato)
