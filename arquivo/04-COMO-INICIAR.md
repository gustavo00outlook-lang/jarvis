# JARVIS — Como iniciar (sempre 100%)

## Início rápido (recomendado)

```bat
cd C:\Users\Micro\Documents\Claude\Projects\Jarvis\jarvis-pro
START_JARVIS.bat
```

Aguarde ~8s → abre `http://localhost:3000`

## Regra de ouro: UM backend só

Antes de iniciar, verifique:

```powershell
netstat -ano | findstr ":8000" | findstr LISTENING
```

Se aparecer **mais de uma linha**, mate todos os PIDs e reinicie:

```bat
CLEAN_RESTART.bat
```

Depois inicie o backend **uma vez**:

```bat
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

## Frontend com cache limpo (se tela branca/erro webpack)

```bat
CLEAN_RESTART.bat
```

Ou manualmente: apagar pasta `.next` e `npm run dev`.

## URLs

| Serviço | URL |
|---------|-----|
| UI | http://localhost:3000 |
| API | http://127.0.0.1:8000 |
| WebSocket | ws://127.0.0.1:8000/ws |
| Docs API | http://127.0.0.1:8000/docs |

## Uso

- **Mic** (centro embaixo): fala → envia após 2,5s de silêncio
- **Teclado**: expande campo de digitação
- `CTRL+ESPAÇO`: alterna microfone
- `F`: tela cheia