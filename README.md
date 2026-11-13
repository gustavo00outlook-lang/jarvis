# JARVIS

Assistente local: orbe no navegador, cérebro Ollama e voz Thomas.

Este repositório é o código para cada pessoa rodar na própria máquina. Ele não abre o JARVIS de outro computador e não traz chaves de API.

## O que precisa

- Windows
- [Node.js](https://nodejs.org/) 20 ou mais recente
- [Python](https://www.python.org/downloads/) 3.13 (`py -3.13`)
- [Ollama](https://ollama.com/) com o modelo `hermes3` (`ollama pull hermes3`)
- FFmpeg no PATH (a voz local usa na reprodução)

A primeira subida da voz baixa o modelo XTTS. Isso leva tempo e ocupa alguns GB.

## Subir

Na pasta do projeto:

```bat
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
py -3.13 -m venv voice-clone-app\.venv
.\voice-clone-app\.venv\Scripts\python.exe -m pip install -r voice-clone-app\requirements.txt
.\voice-clone-app\.venv\Scripts\python.exe -m pip install TTS==0.22.0
npm install
INICIAR-JARVIS.bat
```

Abra http://127.0.0.1:3000

Se o atalho disser que o venv não existe, rode antes:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure-jarvis-venv.ps1
```

O clone de voz precisa do venv em `voice-clone-app\.venv`. Sem ele o orbe sobe, mas a voz Thomas fica em silêncio até o servidor da porta 8787 existir.

## Chaves

Copie `.env.example` para `.env.local` só se for usar Google, ElevenLabs ou Fish. O caminho padrão é Ollama + `voice-clone-app\voices\thomas-0701\master.wav`.

Notas do Obsidian, quando usadas, ficam em `Documentos\JARVIS-notes` de quem está rodando.

## O que fica de fora de propósito

- `.env.local` e qualquer API key
- `node_modules`, `.venv` e o cache do Next
- histórico antigo de amostras de voz (o Git local original passa de 2 GB)
