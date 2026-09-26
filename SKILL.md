---
name: x-video-to-manual
description: Convertir un video (de X/Twitter o un archivo local) en un manual estructurado en Markdown/PDF. Baja el video con yt-dlp, extrae audio, transcribe con Whisper, saca frames y les hace OCR, y entrega un kit + borrador de manual. Usar cuando te pasan un link de video y piden un manual, apuntes, resumen o transcripción.
---

# x-video-to-manual

Pipeline local (sin APIs pagas) para convertir un video en material de lectura:
**video → audio → transcripción → slides (OCR) → manual**.

Pensado para charlas técnicas, workshops y demos, donde el valor está en lo que se
dice **y** en lo que se muestra.

## Cuándo usarla

- Te pasan un link de un video de X/Twitter y piden un manual, apuntes, resumen o transcripción.
- Tenés un `.mp4` local y querés estructura + texto.
- Querés rescatar las slides de un video (texto en pantalla).

## Requisitos

`yt-dlp`, `ffmpeg`/`ffprobe`, `whisper` (openai-whisper), `python3`.
`tesseract` es opcional pero es lo que rescata las slides.
Para PDF: `markdown` (pip) + `wkhtmltopdf` o `pandoc`.

```bash
command -v yt-dlp ffmpeg whisper tesseract python3
```

## Pipeline

### 1. Extraer el kit

```bash
scripts/x-video-to-manual.sh "<url-x-o-archivo>" --out ./xvm-out --model small \
    --vocab "Claude, Anthropic, MCP, harness, sandbox"
```

| Archivo | Contenido |
|---|---|
| `video.mp4` | el video (bajado o copiado) |
| `audio.wav` | audio mono 16 kHz (input del ASR) |
| `transcript.srt` / `transcript.txt` | transcripción con y sin timestamps |
| `frames/f_*.jpg` | un frame cada N segundos |
| `slides-ocr.txt` | texto de las slides (tesseract) |
| `meta.txt` | duración, resolución, fuente, fecha |

### 2. Corregir la transcripción (opt-in)

Sin `--fixes` el texto pasa intacto. Con el diccionario, corrige la jerga del dominio:

```bash
scripts/normalize_transcript.py xvm-out/transcript.txt \
    --fixes fixes/anthropic-agents.tsv -o xvm-out/transcript.clean.txt --report
```

Editar `transcript.clean.txt` a mano es válido: `build_manual.py` lo respeta y no lo
vuelve a tocar.

### 3. Armar el borrador

```bash
scripts/build_manual.py xvm-out --title "Mi charla" --fixes fixes/anthropic-agents.tsv
```

### 4. Redactar (esto lo hace el agente, no el script)

Con el borrador + `slides-ocr.txt`, escribir el manual final: resumen ejecutivo,
secciones temáticas con timestamps, diagramas reconstruidos, takeaways, recursos y
**apéndice con la transcripción**. Marcar `[?]` lo dudoso; no presentar la
transcripción cruda como definitiva.

## Gotchas

- **Sin GPU es lento.** Whisper `small` ≈ 0.5x realtime en 2 vCPU (12 min de audio ≈ 25 min).
  Correrlo en background. `base` es ~4x más rápido pero comete más errores.
- **Whisper alucina homófonos**: `agentic` → *"Asian"*, `Claude` → *"Cloud"*,
  `harness` → *"furnace"*, `MCP servers` → *"MCT servers"*. Corregir con el diccionario.
- **Whisper no acepta `--language auto`**: omitir el flag = autodetección.
- **Whisper nombra la salida por el input** (`audio.srt`); el script la renombra.
- **Whisper puede desobedecer `--initial_prompt`**: ayuda, no garantiza.
- **Verificá el orador en la placa de título del video**, no en el post que lo compartió.
  Quien tuitea un video no siempre es quien habla.
- Los frames se sacan a resolución nativa: si los achicás, el OCR lee peor.
- Los slides suelen tener texto estilizado sobre imágenes: un solo frame puede dar OCR pobre.

## Referencias

- `references/whisper-fixes.md` — errores conocidos y cómo extender el diccionario.
- `templates/manual-template.md` — estructura sugerida del manual final.
- `fixes/anthropic-agents.tsv` — diccionario del dominio agentes/Anthropic.
