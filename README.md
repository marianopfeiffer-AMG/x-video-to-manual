# x-video-to-manual

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3.x-blue.svg)](https://www.python.org/)
[![Requiere](https://img.shields.io/badge/requiere-yt--dlp%20%C2%B7%20ffmpeg%20%C2%B7%20whisper-lightgrey.svg)](#requisitos)

Convierte un **video** (de X/Twitter o un archivo local) en un **manual estructurado**
(Markdown + PDF), todo con herramientas locales. **Sin APIs pagas.**

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
| 3 | `whisper` | transcribe el audio (local), sesgado con el vocabulario de las slides |
| 4 | `tesseract` | OCR de los frames → texto de las slides |
| 5 | `align_slides.py` | pega cada tramo del relato a la slide que estaba en pantalla |
| 6 | agente/redactor | cruza transcript + slides + timeline y escribe el manual |

Los frames y el OCR corren **antes** que la transcripción: el texto de las slides alimenta
el vocabulario que se le pasa a Whisper como `--initial_prompt`.

## Requisitos

- `yt-dlp`, `ffmpeg`/`ffprobe`, `whisper` (openai-whisper), `python3`
- `tesseract` (recomendado: es lo que rescata el texto de las slides)
- Para el PDF: un venv con `markdown` + `wkhtmltopdf` (o `pandoc`)

```bash
command -v yt-dlp ffmpeg whisper tesseract python3
```

## Quickstart

```bash
# 1) descargar + transcribir + frames + OCR  → kit en ./xvm-out
./scripts/x-video-to-manual.sh "https://x.com/<user>/status/<id>" --out ./xvm-out --model small

# 2) corregir los errores típicos de Whisper (opt-in, con diccionario)
./scripts/normalize_transcript.py xvm-out/transcript.txt \
    --fixes references/fixes/anthropic-agents.tsv -o xvm-out/transcript.clean.txt --report

# 3) pegar el relato a las slides
./scripts/align_slides.py xvm-out

# 4) armar el borrador del manual
./scripts/build_manual.py xvm-out --title "Mi charla" --fixes references/fixes/anthropic-agents.tsv

# 5) redactar el manual final (lo hace el agente) y, si querés, exportar a PDF
```

Para bajar el ruido en la fuente, pasale a Whisper el vocabulario del video:

```bash
./scripts/x-video-to-manual.sh <url> --vocab "Claude, Anthropic, MCP, harness, sandbox"
```

## Reanudar sin reprocesar

Whisper sin GPU corre a ~0.5x realtime: un video de 20 minutos tarda ~40. Si el proceso se
corta en el minuto 30, perder todo es un chiste pesado. El pipeline guarda una **firma de
cada etapa** en `xvm-out/.stages.json` y la saltea si nada cambió.

```bash
# corre completo la primera vez
./scripts/x-video-to-manual.sh "<url>" --out ./xvm-out

# se cortó / lo volvés a correr: reusa lo que ya está hecho
./scripts/x-video-to-manual.sh "<url>" --out ./xvm-out

# para forzar de cero
./scripts/x-video-to-manual.sh "<url>" --out ./xvm-out --force

./scripts/stages.py show --state xvm-out/.stages.json   # qué está cacheado
```

La firma se calcula con los parámetros **y** los archivos de entrada, así que reanudar no
es adivinar:

- Cambiás `--model` → sólo se rehace la transcripción.
- Cambiás `--frames-every` → se rehacen frames, OCR, vocabulario y transcripción.
- Borrás `transcript.srt` a mano → se rehace solo esa etapa (la salida faltante invalida la caché).

Medido sobre un clip real, mismas condiciones: **25 s la primera corrida → 1 s la segunda**.

> Los archivos grandes de entrada (video, audio) no se hashean enteros: se muestrean los
> primeros y últimos 64 KB más el tamaño. Detecta un cambio real sin leer 2 GB dos veces.

## Línea de tiempo: relato ↔ slide

El kit tiene la transcripción (con timestamps) y el OCR de las slides, pero separados. Falta
lo obvio: **qué se veía mientras se decía cada cosa**.

`align_slides.py` agrupa los frames que muestran la misma slide (una slide queda en pantalla
muchos segundos → varios frames), arma la línea de tiempo y le cuelga a cada slide el relato
que le corresponde:

```bash
scripts/align_slides.py xvm-out                 # → timeline.md + timeline.json
scripts/align_slides.py xvm-out --thresh 0.5    # más agresivo juntando slides parecidas
```

Salida (ejemplo real, charla de 12 min, 36 frames → 9 slides):

```
## 3. [01:21–01:40] · slide `h_005.jpg`
> 01 Messages API
> The model is provided. Everything around it is yours to build.
> Production infrastructure · Session management · Credentials

- **[01:21]** … y lo que te daban eran tokens de entrada y tokens de salida.
```

Los frames sin texto útil se cuelgan de la slide anterior; si el primer frame trae poco
texto (la placa de título) igual se conserva, porque ahí está el nombre de quien habla.

## Vocabulario: arreglarlo en el origen

Whisper alucina homófonos en jerga técnica: `agentic` → *"Asian"*, `Claude` → *"Cloud"*,
`MCP` → *"MCT"*. Corregirlo después es parchear. La jugada buena es darle a Whisper el
vocabulario correcto **antes**, con `--initial_prompt`.

Las slides son una fuente perfecta: ya tienen escrito —bien escrito— el nombre de los
productos y las siglas. El pipeline las lee primero y deriva el vocabulario solo:

```bash
scripts/build_vocab.py xvm-out/slides-ocr.txt                # lista de términos
scripts/build_vocab.py xvm-out/slides-ocr.txt --json         # + conteos
scripts/build_vocab.py xvm-out/slides-ocr.txt --min-count 2  # solo lo que repite
```

El kit guarda el vocabulario usado en `vocab.txt`, así podés inspeccionarlo. Con
`--vocab "a, b, c"` agregás tus propios términos (van primero), y con `--no-auto-vocab`
lo desactivás.

> Ojo: el OCR también mete basura. Por eso el pipeline usa `--min-count 2` por defecto
> para el vocabulario (los términos reales se repiten entre slides) y el prompt se
> trunca cerca de los 224 tokens.

## Correcciones de transcripción (lo que el vocabulario no atrapó)

El normalizador **no trae reglas hardcodeadas**: las lee de un TSV, así el mismo motor
sirve para dominios distintos.

- **Sin `--fixes` no modifica nada.** Nada de reglas globales que rompan texto legítimo
  ("Google Cloud" ≠ "Google Claude").
- Formato: `<patrón regex> \t <reemplazo literal> \t <nota> \t [<prioridad>]`.
  Las reglas se ordenan por prioridad y longitud, así las específicas ganan a las genéricas.
- `--report` escribe un `corrections.json` con cada cambio (original, corregido, regla, origen).
- Diccionario incluido: `references/fixes/anthropic-agents.tsv` (charlas sobre agentes y Anthropic).

## Estructura

```
.
├── SKILL.md                     # especificación de la skill (AgentSkills)
├── scripts/
│   ├── x-video-to-manual.sh     # orquestador: video → kit (reanudable)
│   ├── stages.py                # caché de etapas (firmas de entrada → salidas)
│   ├── srt.py                   # parser de SRT (único, soporta CRLF/BOM)
│   ├── build_vocab.py           # vocabulario para sesgar Whisper, desde el OCR
│   ├── align_slides.py          # relato ↔ slide → timeline.md
│   ├── normalize_transcript.py  # motor de correcciones (diccionario externo)
│   └── build_manual.py          # kit → borrador de manual
├── references/
│   ├── whisper-fixes.md         # errores conocidos y cómo extender el diccionario
│   └── fixes/
│       └── anthropic-agents.tsv # diccionario de correcciones del dominio
├── templates/
│   └── manual-template.md       # estructura sugerida del manual
├── tests/                       # pytest
└── examples/
    ├── claude-managed-agents-manual.md
    └── claude-managed-agents-manual.pdf
```

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest -q
```

## Notas / gotchas

- **Sin GPU es lento**: Whisper `small` ≈ 0.5x realtime en 2 vCPU (12 min de audio ≈ 25 min).
  `base` es ~4x más rápido pero comete más errores.
- **Verificá el orador** en la placa de título del video, no en el post que lo compartió.
  Quien tuitea un video no siempre es quien habla.
- Los frames se sacan a resolución nativa: si los achicás, el OCR lee peor.
- **Reanudar es automático.** Si tenés dudas de si la caché te está mintiendo, mirá
  `stages.py show` o corré con `--force`. Nunca vas a quedarte con una salida vieja por
  accidente: cualquier cambio en un parámetro o en una entrada invalida la etapa.
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
Cada usuario es responsable de qué material procesa y de cómo lo distribuye, y debe
respetar las condiciones de la plataforma de origen.
