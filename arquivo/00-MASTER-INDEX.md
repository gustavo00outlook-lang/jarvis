# JARVIS — Arquivo Mestre (não perder a evolução)

> **Atualizado:** 2026-06-18 | **Estado:** 100% operacional (v22 Huw)
> **Código:** `C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro`
> **Obsidian:** `C:\Agencia calango\calango.studio\JARVIS`

---

## Este folder (`C:\Users\Micro\JARVIS`)

| Arquivo | Conteúdo |
|---------|----------|
| [00-MASTER-INDEX.md](00-MASTER-INDEX.md) | Este índice |
| [01-INVENTARIO-COMPLETO.md](01-INVENTARIO-COMPLETO.md) | Todos os arquivos e funções |
| [02-ARQUITETURA.md](02-ARQUITETURA.md) | Fluxo UI → API → Agente → Tools |
| [03-EVOLUCAO-CRONOLOGIA.md](03-EVOLUCAO-CRONOLOGIA.md) | Histórico do que construímos |
| [04-COMO-INICIAR.md](04-COMO-INICIAR.md) | Launch sem erros |
| [05-TESTES-2026-06-18.md](05-TESTES-2026-06-18.md) | Testes 7/7 PASS |
| [codigo/README.md](codigo/README.md) | Ponte para jarvis-pro |
| [configs/](configs/) | requirements, scripts, env template |

---

## Estado 100% (2026-06-18)

| Componente | Status |
|------------|--------|
| UI v22 Huw dock (mic + teclado só no hover) | OK |
| Orb + animações GPU | OK |
| Painel Google + screenshot Playwright | OK |
| Voz Fish Thomas (sem eco) | OK |
| Mic 2,5s silêncio + anti-eco TTS | OK |
| Memória Obsidian + runtime | OK |
| Agente Grok + 30 tools | OK |
| Build produção | OK |
| Typecheck | OK |

---

## Iniciar agora

```bat
cd C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro
START_JARVIS.bat
```

Abrir: http://localhost:3000

---

## Não quebrar de novo

1. **Um backend** na porta 8000 (nunca dois uvicorn)
2. **Cache `.next`** — apagar se webpack crash
3. **Google** — sempre `browse_open` (Playwright), não Chrome externo
4. **Animação painel** — não re-trigger em cada screenshot (`GoogleSidePanel.tsx`)
5. **TTS** — HTMLAudio seco, mic pausa no `jarvis:tts-start`

Ver Obsidian: `docs/2026-06-18-jarvis-100-master-archive.md`