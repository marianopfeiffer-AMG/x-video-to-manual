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
    --vocab "Claude, Anthropic, MCP"
```

**Es reanudable.** Si el proceso se corta (Whisper sin GPU tarda ~0.5x realtime), volver a
correrlo **no** reprocesa: cada etapa se saltea si sus entradas no cambiaron. `--force`
ignora la caché y rehace todo; `scripts/stages.py show --state <kit>/.stages.json` muestra
qué está cacheado.

Los frames y el OCR corren **antes** que la transcripción: el script deriva el vocabulario
del texto de las slides (`build_vocab.py`) y se lo pasa a Whisper como `--initial_prompt`.
Eso reduce los homófonos en la fuente, antes de tener que parchearlos.

| Archivo | Contenido |
|---|---|
| `video.mp4` | el video (bajado o copiado) |
| `audio.wav` | audio mono 16 kHz (input del ASR) |
| `transcript.srt` / `transcript.txt` | transcripción con y sin timestamps |
| `frames/f_*.jpg` | un frame cada N segundos |
| `slides-ocr.txt` | texto de las slides (tesseract) |
| `vocab.txt` | vocabulario con el que se sesgó Whisper |
| `meta.txt` | duración, resolución, fuente, fecha, intervalo de frames |
| `.stages.json` | caché de etapas (permite reanudar) |

### 2. Corregir la transcripción (opt-in)

Sin `--fixes` el texto pasa intacto. Con el diccionario, corrige la jerga del dominio:

```bash
scripts/normalize_transcript.py xvm-out/transcript.txt \
    --fixes references/fixes/anthropic-agents.tsv -o xvm-out/transcript.clean.txt --report
```

Editar `transcript.clean.txt` a mano es válido: `build_manual.py` lo respeta y no lo
vuelve a tocar.

### 3. Pegar el relato a las slides

```bash
scripts/align_slides.py xvm-out        # → timeline.md + timeline.json
```

Agrupa los frames que muestran la misma slide y arma tramos `[inicio–fin] · slide` con el
relato adentro. Sin esto, el manual tiene texto y slides, pero desconectados.

Agrupa **por imagen** (16×16 en gris vía ffmpeg), no por texto: con OCR sucio el texto de
un frame no se parece al del anterior y cada frame queda como una slide propia (en un video
real de 30 min: 79 "slides" por texto vs 25 por imagen). `--visual-thresh` ajusta la
sensibilidad; `--group-by text` fuerza el modo viejo.

### 4. Armar el borrador

```bash
scripts/build_manual.py xvm-out --title "Mi charla" --fixes references/fixes/anthropic-agents.tsv
```

`build_manual.py` usa `timeline.md` si existe.

### 5. Redactar (esto lo hace el agente, no el script)

Con el borrador + `slides-ocr.txt`, escribir el manual final: resumen ejecutivo,
secciones temáticas con timestamps, diagramas reconstruidos, takeaways, recursos y
**apéndice con la transcripción**. Marcar `[?]` lo dudoso; no presentar la
transcripción cruda como definitiva.

## Gotchas

- **Sin GPU es lento.** Whisper `small` ≈ 0.5x realtime en 2 vCPU (12 min de audio ≈ 25 min).
  Correrlo en background. `base` es ~4x más rápido pero comete más errores. Si se corta, no
  pierde nada: volvé a correrlo y reanuda donde quedó (`--force` para empezar de cero).
- **Whisper alucina homófonos**: `agentic` → *"Asian"*, `Claude` → *"Cloud"*,
  `harness` → *"furnace"*, `MCP servers` → *"MCT servers"*. Corregir con el diccionario.
- **Whisper no acepta `--language auto`**: omitir el flag = autodetección.
- **El vocabulario automático puede traer basura** (el OCR no es perfecto). Se usa
  `--min-count 2` y aun así conviene mirar `vocab.txt`; `--no-auto-vocab` lo desactiva.
- **Whisper nombra la salida por el input** (`audio.srt`); el script la renombra.
- **Whisper puede desobedecer `--initial_prompt`**: ayuda, no garantiza.
- **Verificá el orador en la placa de título del video**, no en el post que lo compartió.
  Quien tuitea un video no siempre es quien habla.
- Los frames se sacan a resolución nativa: si los achicás, el OCR lee peor.
- **`align_slides.py` necesita saber cada cuántos segundos sacaste los frames**
  (`meta.txt` lo guarda). Si armaste el kit a mano, pasá `--frames-every`.
- **Los slides suelen tener texto estilizado sobre imágenes: un solo frame puede dar OCR pobre.**

## Referencias

- `references/whisper-fixes.md` — errores conocidos y cómo extender el diccionario.
- `templates/manual-template.md` — estructura sugerida del manual final.
- `references/fixes/anthropic-agents.tsv` — diccionario del dominio agentes/Anthropic.
