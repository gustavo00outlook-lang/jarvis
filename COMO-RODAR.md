# Como rodar este repositório

Este repositório é o JARVIS como está hoje: interface, backend, voz Thomas, scripts e o arquivo de documentação em `arquivo/`.

## Neste computador

`INICIAR-JARVIS.bat` ou o atalho da área de trabalho.

Orbe: http://127.0.0.1:3000

## Em outro computador

1. Instale Node.js 20+, Python 3.13 e o Ollama.
2. `ollama pull hermes3`
3. Na pasta clonada:

```bat
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
py -3.13 -m venv voice-clone-app\.venv
.\voice-clone-app\.venv\Scripts\python.exe -m pip install -r voice-clone-app\requirements.txt
.\voice-clone-app\.venv\Scripts\python.exe -m pip install TTS==0.22.0
npm install
INICIAR-JARVIS.bat
```

A primeira voz baixa o modelo XTTS e demora.

Copie `.env.example` para `.env.local` só se for usar chave própria de Google, ElevenLabs ou Fish. O caminho padrão não precisa de chave: Ollama e `voice-clone-app/voices/thomas-0701/master.wav`.

Memória e vault deste PC continuam em pastas locais (`\.hermes` e o Obsidian da Calango). Elas não vão no Git.
