# x-video-to-manual

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3.x-blue.svg)]()
[![Requires](https://img.shields.io/badge/requires-yt--dlp%20%C2%B7%20ffmpeg%20%C2%B7%20whisper%20%C2%B7%20tesseract-lightgrey.svg)]()

Convierte un **video** (de X/Twitter o un archivo local) en un **manual estructurado** (Markdown + PDF),
todo con herramientas locales. Sin APIs pagas.

```
video → audio → transcripción (Whisper) → slides (OCR) → manual (redacción)
```

Nació de una necesidad concreta: te pasan un link de X con una charla técnica de 12 minutos y
querés sacarle un documento útil — el texto, las slides y la estructura — sin mirarlo entero.

## Cómo funciona

| Paso | Herramienta | Qué hace |
|---|---|---|
| 1 | `yt-dlp` | baja el video de X (o copia uno local) |
| 2 | `ffmpeg` | extrae audio mono 16 kHz + un frame cada N segundos |
| 3 | `whisper` | transcribe el audio (local) |
| 4 | `tesseract` | OCR de los frames → texto de las slides |
| 5 | agente/redactor | cruza transcript + slides y escribe el manual |

## Requisitos

```bash
command -v yt-dlp ffmpeg whisper tesseract    # todos
```

- `yt-dlp`, `ffmpeg`, `whisper` (openai-whisper), `tesseract` (recomendado), `python3`
- Para el PDF: un venv con `markdown` + `wkhtmltopdf` (o `pandoc`)

## Quickstart

```bash
# 1) descargar + transcribir + frames + OCR  → kit en ./xvm-out
./scripts/x-video-to-manual.sh "https://x.com/<user>/status/<id>" --out ./xvm-out --model small

# 2) limpiar los errores típicos de Whisper
./scripts/normalize_transcript.py xvm-out/transcript.txt -o xvm-out/transcript.clean.txt --report

# 3) armar el borrador del manual
./scripts/build_manual.py xvm-out --title "Mi charla" --out manual-draft.md

# 4) redactar el manual final (lo hace el agente) y, si querés, exportar a PDF
```

## Estructura

```
.
├── SKILL.md                     # especificación de la skill (AgentSkills)
├── scripts/
│   ├── x-video-to-manual.sh     # orquestador: video → kit
│   ├── normalize_transcript.py  # diccionario de correcciones de Whisper
│   └── build_manual.py          # kit → borrador de manual
├── references/
│   └── whisper-fixes.md         # errores conocidos de Whisper y cómo extenderlos
├── templates/
│   └── manual-template.md       # estructura sugerida del manual
└── examples/
    ├── claude-managed-agents-manual.md    # ejemplo real (charla de Anthropic, 12 min)
    └── claude-managed-agents-manual.pdf
```

## Ejemplo incluido

`examples/` contiene un manual real generado con este pipeline a partir de un video de X
(una charla de Anthropic sobre *Claude Managed Agents*): 5 páginas, con las slides, el
walkthrough y la transcripción corregida.

## Notas / gotchas

- **Sin GPU es lento**: Whisper `small` ≈ 0.5x realtime en 2 vCPU (12 min de audio ≈ 25 min).
  `base` es ~4x más rápido pero comete más errores.
- **Whisper alucina homófonos** en jerga técnica (`agentic` → *"Asian"*, `Claude` → *"Cloud"*,
  `harness` → *"furnace"*…). Pasá siempre el normalizador.
- **Verificá el orador** en la placa de título del video, no en el post que lo compartió.
- Si tenés un modelo de visión disponible, usalo para describir los diagramas; si no,
  el OCR de `tesseract` cubre el texto de las slides.

## Licencia

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**MIT** — podés usar, copiar, modificar, distribuir y vender, gratis y sin pedir permiso.
La única condición es la atribución (abajo).

### Atribución requerida

Si usás este proyecto (total o parcialmente), tenés que:

1. Mantener el aviso de copyright del archivo [`LICENSE`](LICENSE).
2. Acreditar al autor: **Mariano Pfeiffer** — https://github.com/marianopfeiffer-AMG
3. Enlazar al repo original: https://github.com/marianopfeiffer-AMG/x-video-to-manual

El texto de MIT ya obliga a esto ("The above copyright notice and this permission
notice shall be included in all copies or substantial portions of the Software").
Acá queda dicho sin vueltas, en castellano.

## Contenido y derechos

La licencia MIT cubre el **código** de este repo. **No** cubre el contenido de los
videos que proceses: la transcripción y las slides pertenecen a quien las produjo.
Cada usuario es responsable de qué material procesa y de cómo lo distribuye.
