# Clone Thomas — `master.wav`

API: `http://127.0.0.1:8787`  
Sample: `voices/thomas-0701/master.wav` (único arquivo de voz)

XTTS-v2, 6 s de latents em cache (padrão Coqui). Frase nova ~4–6 s no CPU; repetida ~0,3 s.

```http
POST /speak
{"text":"Olá, senhor.","voice_id":"thomas-0701","prefer":"xtts","mp3":false}
```

Subir: `scripts\iniciar-voice-clone.ps1` ou o atalho JARVIS.
