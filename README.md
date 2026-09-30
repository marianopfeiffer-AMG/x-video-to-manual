# x-video-to-manual

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3.x-blue.svg)](https://www.python.org/)
[![Requiere](https://img.shields.io/badge/requiere-yt--dlp%20%C2%B7%20ffmpeg%20%C2%B7%20whisper-lightgrey.svg)](#requisitos)

Convierte un **video** (de X/Twitter, YouTube o un archivo local) en un **manual estructurado**
(Markdown + PDF), todo con herramientas locales. **Sin APIs pagas.**

```
video → audio → transcripción (Whisper) → slides (OCR) → manual (redacción)
```

Nació de una necesidad concreta: te pasan un link de X con una charla técnica de 12 minutos y
querés sacarle un documento útil — el texto, las slides y la estructura — sin mirarlo entero.

## Cómo funciona

| Paso | Herramienta | Qué hace |
|---|---|---|
| 1 | `yt-dlp` | baja el video de X o YouTube (o copia uno local) |
| 2 | `ffmpeg` | extrae audio mono 16 kHz + un frame cada N segundos |
| 3 | `whisper` | transcribe el audio (local), sesgado con el vocabulario de las slides |
| 4 | `tesseract` | OCR de los frames → texto de las slides |
| 5 | `align_slides.py` | pega cada tramo del relato a la slide que estaba en pantalla |
| 6 | `build_manual.py` | arma un borrador-índice (tramo, pantalla, arranque del relato) |
| 7 | agente/redactor | escribe el manual con el template y lo exporta con `to_pdf.sh` |

Los frames y el OCR corren **antes** que la transcripción: el texto de las slides alimenta
el vocabulario que se le pasa a Whisper como `--initial_prompt`.

## Requisitos

- `yt-dlp`, `ffmpeg`/`ffprobe`, `whisper` (openai-whisper), `python3`
- `tesseract` (recomendado: es lo que rescata el texto de las slides)
- Para el PDF: `wkhtmltopdf` + `pip install markdown` (o `pandoc`); `scripts/to_pdf.sh` elige solo
- Opcional: `pip install tiktoken` para contar exacto los tokens del vocabulario (si no, se estima)

```bash
command -v yt-dlp ffmpeg whisper tesseract python3
```

## Quickstart

```bash
# 1) descargar + transcribir + frames + OCR  → kit en ./xvm-out
./scripts/x-video-to-manual.sh "https://x.com/<user>/status/<id>" --out ./xvm-out --model small

# 2) corregir los errores típicos de Whisper (opt-in, con diccionario)
./scripts/normalize_transcript.py xvm-out/transcript.txt \
    --fixes anthropic-agents -o xvm-out/transcript.clean.txt --report

# 3) pegar el relato a las slides
./scripts/align_slides.py xvm-out

# 4) armar el borrador-índice del manual (→ xvm-out/manual-draft.md)
./scripts/build_manual.py xvm-out --title "Mi charla"

# 5) redactar el manual final (lo hace el agente) y exportarlo
./scripts/to_pdf.sh mi-manual.md
```

Los scripts resuelven solos las rutas de la skill (`--fixes anthropic-agents` busca en
`references/fixes/`) y dejan todas sus salidas **dentro del kit**: se pueden correr desde
cualquier directorio.

Para bajar el ruido en la fuente, pasale a Whisper el vocabulario del video:

```bash
./scripts/x-video-to-manual.sh <url> --vocab "Claude, Anthropic, MCP, harness, sandbox"
```

## Reanudar sin reprocesar

Whisper sin GPU es lento: `small` tarda ~1,8× la duración del audio (medido: 31 min de
audio → 57 min en 2 vCPU). El pipeline guarda una **firma de cada etapa** en
`xvm-out/.stages.json` y la saltea si nada cambió.

**Reanuda entre etapas, no dentro de una.** Si se corta durante la transcripción, al volver a
correrlo el video, el audio, los frames y el OCR salen de la caché, pero la transcripción se
rehace entera. El kit es movible: la caché guarda rutas relativas.

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

Por defecto, al terminar se borran `video.mp4` y `audio.wav` (~250 MB por video): el kit queda
con los textos y los frames. Si pensás iterar sobre el mismo video (otro modelo, otro
vocabulario), usá `--keep-media`; si no, una nueva corrida vuelve a bajarlo.

## En un host compartido

Pensado para correr en un servidor chico que también atiende otros servicios:

| Protección | Default | Para cambiarlo |
|---|---|---|
| Una corrida a la vez (lock global) | espera hasta 2 h | `--lock-wait`, `XVM_LOCK` |
| Prioridad baja de CPU y disco | `nice 19` + `ionice -c3` | — |
| Deja un core libre | cores − 1 hilos | `XVM_THREADS` |
| Modelos pesados | solo `tiny`/`base`/`small` | `--allow-big-model` |
| Duración máxima | 60 min | `--max-minutes`, `--allow-long` |
| Descargas | sin playlists, ≤ 1 GB, timeout 30 s | — |
| Dominios | X, Twitter, YouTube | `--any-domain` |
| Archivos locales | tienen que ser video | `XVM_INPUT_ROOTS` para limitar directorios |

> Los archivos grandes de entrada (video, audio) no se hashean enteros: se muestrean los
> primeros y últimos 64 KB más el tamaño. Detecta un cambio real sin leer 2 GB dos veces.

## Línea de tiempo: relato ↔ slide

El kit tiene la transcripción (con timestamps) y el OCR de las slides, pero separados. Falta
lo obvio: **qué se veía mientras se decía cada cosa**.

`align_slides.py` agrupa los frames que muestran la misma slide y le cuelga a cada una el
relato que le corresponde:

```bash
scripts/align_slides.py xvm-out                 # → timeline.md + timeline.json
scripts/align_slides.py xvm-out --visual-thresh 0.05   # más exigente agrupando
scripts/align_slides.py xvm-out --group-by text        # si no tenés ffmpeg
```

**Agrupa por imagen, no por texto.** Comparar las palabras del OCR parece lo natural, pero
se rompe con OCR sucio: a 360p el OCR devuelve basura distinta en cada frame, el umbral de
similitud nunca se alcanza y cada frame termina siendo una "slide". Medido en un video real
de 30 minutos:

| Señal | Resultado |
|---|---|
| Texto (Jaccard) | 94 frames → **79 slides** ❌ |
| Imagen (16×16 gris) | 94 frames → **25 slides** ✅ |

La señal visual además separa limpio: misma slide ≤ 0,05 de diferencia media entre frames;
distinta slide ≥ 0,14. El umbral por defecto es 0,08, en el medio del hueco.

Compara cada frame con el anterior, así que una variación chica (el orador moviéndose, una
animación) no parte la slide en dos. Si no hay ffmpeg o los frames no están, cae solo al
método por texto.

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
`--vocab "a, b, c"` agregás tus propios términos (máxima prioridad), y con `--no-auto-vocab`
lo desactivás.

**Presupuesto de tokens.** openai-whisper se queda con los **últimos** 223 tokens del
`--initial_prompt` y descarta el principio. Un vocabulario de 900 caracteres con
identificadores de código llega a ~295 tokens: se perdían justo los términos más importantes,
que iban primero. Ahora el prompt se recorta a 200 tokens (exacto con `tiktoken`, estimado sin
él) y se escribe de menor a mayor importancia: lo tuyo y lo mejor quedan al final.

> Ojo: el OCR también mete basura. El pipeline usa `--min-count 2` y descarta interfaz de
> navegador (Chrome, Bookmarks, Window…), identificadores de código (`EMA_9_21_Cross`),
> palabras cortadas (`PRODUCTION-SCRI`) y tiras aleatorias (`GWJOttwiXHO7IWAIP`). En
> tutoriales de pantalla conviene `--no-auto-vocab` directamente.

## Correcciones de transcripción (lo que el vocabulario no atrapó)

El normalizador **no trae reglas hardcodeadas**: las lee de un TSV, así el mismo motor
sirve para dominios distintos.

- **Sin `--fixes` no modifica nada.** Nada de reglas globales que rompan texto legítimo
  ("Google Cloud" ≠ "Google Claude", "the cloud" ≠ "the Claude").
- Formato: `<patrón regex> \t <reemplazo literal> \t <nota> \t [<prioridad>]`.
  Las reglas se ordenan por prioridad y longitud, así las específicas ganan a las genéricas.
- `--report` escribe un `corrections.json` junto a la salida, con cada cambio (original, corregido, regla, origen).
- Diccionario incluido: `references/fixes/anthropic-agents.tsv` (charlas sobre agentes y Anthropic),
  usable como `--fixes anthropic-agents`.
- Las correcciones de un video concreto van a `KIT/fixes.tsv` (`--fixes KIT/fixes.tsv`), no al
  diccionario del dominio.

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
│   ├── build_manual.py          # kit → borrador-índice del manual
│   └── to_pdf.sh                # manual.md → manual.pdf (wkhtmltopdf o pandoc)
├── references/
│   ├── whisper-fixes.md         # errores conocidos y cómo extender el diccionario
│   └── fixes/
│       └── anthropic-agents.tsv # diccionario de correcciones del dominio
├── templates/
│   └── manual-template.md       # estructura sugerida del manual
├── tests/                       # pytest
└── examples/
    └── claude-managed-agents-manual.md   # extracto (sin la transcripción de la charla)
```

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest -q
```

## Notas / gotchas

- **Sin GPU es lento**: Whisper `small` ≈ **1,8× la duración del audio** en 2 vCPU
  (medido: 31 min → 57 min). `base` es ~4× más rápido pero comete más errores.
- **La resolución de origen es un techo.** X puede ofrecer solo 640×360 para un post (no es
  un bug de descarga: `yt-dlp -F` lo confirma). A esa resolución tesseract pega las palabras
  (`CLAUDE.md` → `CLAWE.ed`) **y ese ruido envenena el vocabulario** que se le pasa a Whisper.
  El pipeline lo detecta y escala los frames a ~1600px antes del OCR (`--ocr-scale auto`,
  x3 como máximo); en HD queda x1.
- **No fuerces el idioma** con `--lang` por el idioma del post: un post en español puede traer
  un video en inglés. Autodetectar transcribe mejor.
- **Verificá el orador** en la placa de título del video, no en el post que lo compartió.
  Quien tuitea un video no siempre es quien habla.
- Los frames se sacan a resolución nativa: si los achicás, el OCR lee peor.
- **Reanudar es automático.** Si tenés dudas de si la caché te está mintiendo, mirá
  `stages.py show` o corré con `--force`. Nunca vas a quedarte con una salida vieja por
  accidente: cualquier cambio en un parámetro o en una entrada invalida la etapa.
- Si tenés un modelo de visión disponible, usalo para describir los diagramas; si no,
  el OCR de `tesseract` cubre el texto de las slides.

## Instalarla en un agente

La skill instalada en un agente tiene que ser **este repo**, no una copia suelta (una copia
se desfasa y los arreglos nunca llegan). Con OpenClaw:

```bash
git clone https://github.com/marianopfeiffer-AMG/x-video-to-manual.git <workspace>/repos/x-video-to-manual
ln -sfn <workspace>/repos/x-video-to-manual <workspace>/skills/x-video-to-manual
openclaw skills list | grep x-video-to-manual          # debe figurar "ready"
# actualizar:  git -C <workspace>/repos/x-video-to-manual pull --ff-only
```

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
