---
name: "x-video-to-manual"
description: "Convertir videos de X (o locales) en manuales Markdown/PDF: descarga, transcripción con Whisper, OCR de slides y redacción."
status: proposal
version: "v1"
date: "2026-09-26T20:35:26.774Z"
---

# x-video-to-manual

Pipeline local (sin APIs pagas) para convertir un video en material de lectura:
**video → audio → transcripción → slides (OCR) → manual**.

Pensado para charlas técnicas, workshops y demos donde el valor está en lo que se
dice **y** en las slides.

## Cuándo usarla

- Te pasan un link de un video de X/Twitter y piden "un manual", "apuntes", "resumen" o "transcripción".
- Tenés un `.mp4` local y querés estructura + texto.
- Querés rescatar las slides de un video (texto en pantalla).

## Requisitos (host)

`yt-dlp`, `ffmpeg`/`ffprobe`, `whisper` (openai-whisper), `tesseract` (opcional pero recomendado),
`python3`. Para PDF: un venv con el paquete `markdown` + `wkhtmltopdf` (o pandoc si está).

Verificá rápido:

```bash
command -v yt-dlp ffmpeg whisper tesseract
```

## Pipeline (5 pasos)

### 1. Correr el extractor

```bash
scripts/x-video-to-manual.sh "<url-x-o-archivo>" --out ./xvm-out --model small --frames-every 20
```

Deja en el kit:

| Archivo | Contenido |
|---|---|
| `video.mp4` | el video (bajado o copiado) |
| `audio.wav` | audio mono 16 kHz (input del ASR) |
| `transcript.srt` / `transcript.txt` | transcripción con y sin timestamps |
| `frames/f_*.jpg` | un frame cada N segundos |
| `slides-ocr.txt` | texto de las slides (tesseract) |
| `meta.txt` | duración, resolución, fuente, fecha |

### 2. Corregir la transcripción

Whisper mete errores sistemáticos de dominio. Pasá el diccionario:

```bash
scripts/normalize_transcript.py xvm-out/transcript.txt -o xvm-out/transcript.clean.txt --report
```

### 3. Armar el borrador

```bash
scripts/build_manual.py xvm-out --title "Mi charla" --out manual-draft.md
```

### 4. Redactar (esto lo hace el agente, no el script)

Con el borrador + `slides-ocr.txt`, escribir el manual final:
resumen ejecutivo, secciones temáticas con timestamps, diagramas reconstruidos,
takeaways, recursos y **apéndice con la transcripción corregida**.
Nunca presentar la transcripción cruda como definitiva: marcar `[?]` lo dudoso.

### 5. Exportar a PDF (opcional)

```bash
python3 -m venv /tmp/mdvenv && /tmp/mdvenv/bin/pip install -q markdown
/tmp/mdvenv/bin/python -c "
import markdown
md=open('manual.md',encoding='utf-8').read()
body=markdown.markdown(md, extensions=['tables','fenced_code','sane_lists'])
open('_m.html','w',encoding='utf-8').write(f\"<html><head><meta charset='utf-8'></head><body>{body}</body></html>\")
"
wkhtmltopdf -q _m.html manual.pdf
```

## Gotchas (leer antes de correr)

- **Sin GPU tarda.** Whisper `small` va a ~0.5x realtime en 2 vCPU: 12 min de audio ≈ 25 min de proceso.
  Lanzarlo en background y seguir con otra cosa. `base` es ~4x más rápido pero comete más errores.
- **Errores típicos de Whisper**: `agentic/agent` → *"Asian"*, `Claude` → *"Cloud"*,
  `harness` → *"furnace"*, `MCP servers` → *"MCT servers"*, `Vault` → *"Waltz"*,
  `checkpointing` → *"checkwining"*. Siempre normalizar (paso 2).
- **Whisper no acepta `--language auto`**: omitir el flag = autodetección.
- **Whisper nombra la salida por el input** (`audio.srt`). El script ya la renombra a `transcript.srt`.
- **La tool `image` puede estar caída** (créditos Anthropic). Fallback para slides: **tesseract OCR**.
  `--psm 3` para layouts de slide; frames a resolución nativa (no escalar) para que el OCR lea bien.
- La tool `image` rechaza paths **fuera del workspace**: copiar frames adentro antes de analizarlos.
- **Verificá el orador en la placa de título**, no en el post que compartió el video. Quien tuitea
  un video no siempre es quien habla (caso real: el post era de Mo Elgaraihy y el orador Gagan Bhat).
- Los slides suelen tener texto estilizado sobre imágenes: el OCR de un solo frame puede ser pobre.
  Pedir varios frames (o subir el frame rate) mejora la cobertura.

## Referencias

- `references/whisper-fixes.md` — diccionario de correcciones y cómo extenderlo.
- `templates/manual-template.md` — estructura sugerida del manual final.