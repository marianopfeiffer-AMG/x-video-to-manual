#!/usr/bin/env bash
# x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.
#
# Reanudable ENTRE etapas: cada etapa se saltea si sus entradas no cambiaron (ver
# scripts/stages.py). La transcripción es una sola etapa: si se corta a mitad, se rehace entera.
# Con --force se ignora la caché y se rehace todo.
#
# Pensado para correr en un host compartido (un VPS chico con otros servicios):
#   - una sola corrida a la vez (lock global),
#   - prioridad baja de CPU y disco (nice/ionice) y deja un core libre,
#   - topes de modelo, duración y tamaño de descarga.
#
# Requiere: yt-dlp, ffmpeg/ffprobe, whisper (openai-whisper). Opcional: tesseract.
set -euo pipefail

usage() {
  cat <<'EOF'
x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.

Uso:
  x-video-to-manual.sh <url | archivo-de-video> [opciones]

Opciones:
  --out DIR            directorio de salida (default: ./xvm-out)
  --model NOMBRE       modelo de Whisper: tiny | base | small (default: small)
  --allow-big-model    permite medium/large (necesitan 5-10 GB de RAM)
  --lang CODIGO        idioma del AUDIO para Whisper (default: autodetectar).
                       No lo deduzcas del idioma del post: si dudás, no lo pases.
  --vocab "a, b, c"    términos extra para sesgar Whisper (se suman a los del OCR)
  --no-auto-vocab      no derivar el vocabulario del OCR (recomendado en screencasts)
  --frames-every N     un frame cada N segundos (default: 20)
  --no-ocr             no correr tesseract sobre los frames
  --ocr-scale N|auto   upscale de los frames antes del OCR (default: auto)
  --max-minutes N      duración máxima del video (default: 60)
  --allow-long         sin tope de duración
  --any-domain         acepta URLs fuera de x.com / twitter.com / youtube.com / youtu.be
  --keep-media         conserva video.mp4 y audio.wav al terminar (default: se borran)
  --lock-wait SEG      cuánto esperar si hay otra corrida en curso (default: 7200)
  --force              rehacer todo, ignorando la caché de etapas

Variables de entorno:
  XVM_LOCK             archivo de lock (default: /tmp/x-video-to-manual.lock)
  XVM_THREADS          hilos para Whisper (default: cores - 1, mínimo 1)
  XVM_INPUT_ROOTS      directorios permitidos para archivos locales, separados por ':'
                       (default: cualquiera, pero tiene que ser un video)

Salida (en DIR):
  video.mp4            video bajado/original (se borra al terminar salvo --keep-media)
  audio.wav            audio mono 16 kHz para ASR (ídem)
  transcript.srt       transcripción con timestamps
  transcript.txt       transcripción aplanada [hh:mm:ss] texto
  frames/              frames cada N segundos (jpg)
  slides-ocr.txt       texto extraído de las slides con tesseract
  vocab.txt            vocabulario usado para sesgar Whisper
  meta.txt             metadatos (duración, resolución, fuente, fecha)
  .stages.json         caché de etapas (permite reanudar sin reprocesar)

Siguiente paso (rutas relativas al directorio de la skill; los scripts las resuelven solos):
  scripts/normalize_transcript.py <DIR>/transcript.txt --fixes anthropic-agents -o <DIR>/transcript.clean.txt --report
  scripts/align_slides.py <DIR>            # pega el relato a las slides → timeline.md
  scripts/build_manual.py <DIR> --title "..."
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC=""; OUT="./xvm-out"; MODEL="small"; WHISPER_LANG="auto"; VOCAB=""
FRAMES_EVERY=20; DO_OCR=1; AUTO_VOCAB=1; FORCE=0; OCR_SCALE="auto"; WIDTH=""
ALLOW_BIG=0; MAX_MINUTES=60; ALLOW_LONG=0; ANY_DOMAIN=0; KEEP_MEDIA=0; LOCK_WAIT=7200

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --allow-big-model) ALLOW_BIG=1; shift;;
    --lang) WHISPER_LANG="$2"; shift 2;;
    --vocab) VOCAB="$2"; shift 2;;
    --no-auto-vocab) AUTO_VOCAB=0; shift;;
    --frames-every) FRAMES_EVERY="$2"; shift 2;;
    --no-ocr) DO_OCR=0; AUTO_VOCAB=0; shift;;
    --ocr-scale) OCR_SCALE="$2"; shift 2;;
    --max-minutes) MAX_MINUTES="$2"; shift 2;;
    --allow-long) ALLOW_LONG=1; shift;;
    --any-domain) ANY_DOMAIN=1; shift;;
    --keep-media) KEEP_MEDIA=1; shift;;
    --lock-wait) LOCK_WAIT="$2"; shift 2;;
    --force) FORCE=1; shift;;
    -h|--help) usage; exit 0;;
    -*) echo "opción desconocida: $1 (ver --help)" >&2; exit 2;;
    *) SRC="$1"; shift;;
  esac
done

# --- validación de argumentos (antes de tocar nada) --------------------------
[ -n "$SRC" ] || { echo "ERROR: falta <url | archivo> (ver --help)" >&2; exit 1; }
for pair in "frames-every:$FRAMES_EVERY" "max-minutes:$MAX_MINUTES" "lock-wait:$LOCK_WAIT"; do
  case "${pair#*:}" in ''|*[!0-9]*) echo "ERROR: --${pair%%:*} debe ser un entero" >&2; exit 2;; esac
done
[ "$FRAMES_EVERY" -gt 0 ] || { echo "ERROR: --frames-every debe ser > 0" >&2; exit 2; }
case "$OCR_SCALE" in
  auto) ;;
  ''|*[!0-9]*) echo "ERROR: --ocr-scale debe ser 'auto' o un entero" >&2; exit 2;;
esac
case "$OCR_SCALE" in *[!0]*) ;; *) OCR_SCALE=1;; esac

# Modelos: en CPU, `small` usa ~2 GB de RAM; `medium`/`large` 5-10 GB. En un host chico
# compartido eso tumba a los demás procesos.
case "$MODEL" in
  tiny|tiny.en|base|base.en|small|small.en) ;;
  medium|medium.en|large|large-v1|large-v2|large-v3|large-v3-turbo|turbo)
    if [ "$ALLOW_BIG" != "1" ]; then
      echo "ERROR: el modelo '$MODEL' necesita 5-10 GB de RAM. Usá tiny/base/small," >&2
      echo "       o --allow-big-model si esta máquina lo aguanta." >&2
      exit 2
    fi;;
  *) echo "ERROR: modelo de Whisper desconocido: '$MODEL'" >&2; exit 2;;
esac

IS_LOCAL=0
if [ -e "$SRC" ]; then
  IS_LOCAL=1
  [ -f "$SRC" ] || { echo "ERROR: '$SRC' no es un archivo regular" >&2; exit 2; }
  if [ -n "${XVM_INPUT_ROOTS:-}" ]; then
    REAL_SRC="$(cd "$(dirname "$SRC")" && pwd -P)/$(basename "$SRC")"
    OK_ROOT=0
    IFS=':' read -r -a ROOTS <<< "$XVM_INPUT_ROOTS"
    for root in "${ROOTS[@]}"; do
      [ -n "$root" ] || continue
      if root_real="$(cd "$root" 2>/dev/null && pwd -P)"; then
        case "$REAL_SRC" in "$root_real"/*) OK_ROOT=1;; esac
      fi
    done
    [ "$OK_ROOT" = "1" ] || { echo "ERROR: '$SRC' está fuera de XVM_INPUT_ROOTS" >&2; exit 2; }
  fi
else
  case "$SRC" in
    http://*|https://*) ;;
    *) echo "ERROR: '$SRC' no es un archivo existente ni una URL http(s)" >&2; exit 2;;
  esac
  HOST="${SRC#*://}"; HOST="${HOST%%/*}"; HOST="${HOST%%:*}"; HOST="${HOST##*@}"
  HOST="$(printf '%s' "$HOST" | tr '[:upper:]' '[:lower:]')"
  if [ "$ANY_DOMAIN" != "1" ]; then
    case "$HOST" in
      x.com|www.x.com|twitter.com|www.twitter.com|mobile.twitter.com|mobile.x.com) ;;
      youtube.com|www.youtube.com|m.youtube.com|youtu.be) ;;
      *) echo "ERROR: dominio no permitido: '$HOST' (X, Twitter o YouTube; --any-domain para otros)" >&2
         exit 2;;
    esac
  fi
fi

for tool in yt-dlp ffmpeg ffprobe whisper python3; do
  command -v "$tool" >/dev/null || { echo "ERROR: falta '$tool'" >&2; exit 1; }
done

if [ "$IS_LOCAL" = "1" ]; then
  # Tiene que ser un video de verdad: evita que una ruta cualquiera (/etc/…, llaves) termine
  # copiada al kit y leída por el agente.
  if ! ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$SRC" \
       2>/dev/null | grep -q video; then
    echo "ERROR: '$SRC' no es un archivo de video" >&2; exit 2
  fi
fi

# --- recursos: una corrida a la vez, prioridad baja, un core libre -----------
NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
THREADS="${XVM_THREADS:-$(( NPROC > 1 ? NPROC - 1 : 1 ))}"
case "$THREADS" in ''|*[!0-9]*|0) THREADS=1;; esac

low() {
  # Todo lo pesado corre con la menor prioridad de CPU y de disco disponible.
  if command -v ionice >/dev/null 2>&1; then
    nice -n 19 ionice -c3 "$@"
  else
    nice -n 19 "$@"
  fi
}

LOCK="${XVM_LOCK:-/tmp/x-video-to-manual.lock}"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "      otra corrida en curso ($LOCK); espero hasta ${LOCK_WAIT}s…" >&2
    flock -w "$LOCK_WAIT" 9 || { echo "ERROR: otra corrida sigue en curso ($LOCK)" >&2; exit 75; }
  fi
else
  # Sin flock (macOS): lock por directorio, con el PID adentro para detectar locks huérfanos.
  LOCKDIR="$LOCK.d"
  waited=0
  until mkdir "$LOCKDIR" 2>/dev/null; do
    holder="$(cat "$LOCKDIR/pid" 2>/dev/null || true)"
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
      rm -rf "$LOCKDIR"; continue
    fi
    if [ "$waited" -ge "$LOCK_WAIT" ]; then
      echo "ERROR: otra corrida sigue en curso ($LOCKDIR, pid ${holder:-?})" >&2; exit 75
    fi
    [ "$waited" = "0" ] && echo "      otra corrida en curso ($LOCKDIR); espero hasta ${LOCK_WAIT}s…" >&2
    sleep 5; waited=$((waited + 5))
  done
  echo $$ > "$LOCKDIR/pid"
  trap 'rm -rf "$LOCKDIR"' EXIT
fi

mkdir -p "$OUT" "$OUT/frames"
OUT="$(cd "$OUT" && pwd)"
VIDEO="$OUT/video.mp4"

# --- caché de etapas ------------------------------------------------------
STAGES_PY="$SCRIPT_DIR/stages.py"
STATE="$OUT/.stages.json"

stage_sig() { python3 "$STAGES_PY" sig "$@"; }

# ¿La etapa está al día? (firma igual y salidas presentes). Con --force, nunca.
cached() {
  if [ "$FORCE" = "1" ]; then return 1; fi
  python3 "$STAGES_PY" ok --state "$STATE" --stage "$1" --sig "$2"
}

# Registra una etapa como hecha (se le pasa --output <ruta>).
mark() {
  local stage="$1" s="$2"; shift 2
  if [ $# -gt 0 ]; then
    python3 "$STAGES_PY" mark --state "$STATE" --stage "$stage" --sig "$s" "$@"
  else
    python3 "$STAGES_PY" mark --state "$STATE" --stage "$stage" --sig "$s"
  fi
}

# 1) Obtener el video ------------------------------------------------------
if [ "$IS_LOCAL" = "1" ]; then
  S_VIDEO="$(stage_sig --param src="$SRC" --file "$SRC")"
else
  S_VIDEO="$(stage_sig --param url="$SRC")"
fi

MAX_BYTES="1G"
if cached video "$S_VIDEO" && [ -s "$VIDEO" ]; then
  echo "[1/7] Video en caché (sin cambios)"
else
  if [ "$IS_LOCAL" = "1" ]; then
    echo "[1/7] Copiando video local…"
    cp "$SRC" "$VIDEO"
  else
    echo "[1/7] Descargando con yt-dlp…"
    rm -f "$OUT"/dl.*                     # restos de una descarga cortada (.part, formatos sueltos)
    MATCH=()
    [ "$ALLOW_LONG" = "1" ] || MATCH=(--match-filter "!duration | duration <= $(( MAX_MINUTES * 60 ))")
    if ! low yt-dlp -q --no-warnings --no-playlist --max-filesize "$MAX_BYTES" --socket-timeout 30 \
                ${MATCH[@]+"${MATCH[@]}"} -f "bv*+ba/b" --merge-output-format mp4 \
                -o "$OUT/dl.%(ext)s" "$SRC"; then
      cat >&2 <<'EOF'
ERROR: yt-dlp no pudo bajar el video. Caminos posibles:
  1) yt-dlp desactualizado  →  yt-dlp -U
  2) el post requiere login →  en una máquina con navegador: yt-dlp --cookies-from-browser firefox <url>
  3) bajalo a mano y pasá el archivo local:  x-video-to-manual.sh /ruta/video.mp4
EOF
      exit 1
    fi
    FOUND=""
    for f in "$OUT"/dl.*; do
      case "$f" in *.part|*.ytdl) continue;; esac
      [ -s "$f" ] && FOUND="$f" && break
    done
    if [ -z "$FOUND" ]; then
      echo "ERROR: yt-dlp no generó archivo: el video supera --max-minutes $MAX_MINUTES o $MAX_BYTES," >&2
      echo "       o el link no tiene video (--allow-long para videos largos)" >&2
      exit 1
    fi
    if [ "$FOUND" != "$VIDEO" ]; then
      low ffmpeg -y -v error -i "$FOUND" -c copy "$VIDEO" 2>/dev/null || mv "$FOUND" "$VIDEO"
      rm -f "$FOUND"
    fi
  fi
  mark video "$S_VIDEO" --output "$VIDEO"
fi

# 2) Metadatos (barato: siempre se refresca) -------------------------------
echo "[2/7] Leyendo metadatos…"
ffprobe -v error -show_entries format=duration,size \
        -show_entries stream=codec_type,width,height -of default=noprint_wrappers=1 \
        "$VIDEO" > "$OUT/meta.txt"
# Fuente local: solo el nombre (la ruta completa del host no tiene que llegar al manual).
if [ "$IS_LOCAL" = "1" ]; then SOURCE_LABEL="$(basename "$SRC")"; else SOURCE_LABEL="$SRC"; fi
{
  echo "source=$SOURCE_LABEL"; echo "fetched_utc=$(date -u +%FT%TZ)"
  echo "frames_every=$FRAMES_EVERY"
} >> "$OUT/meta.txt"

DURATION="$(awk -F= '/^duration=/{print int($2); exit}' "$OUT/meta.txt")"
if [ "$ALLOW_LONG" != "1" ] && [ -n "${DURATION:-}" ] && [ "$DURATION" -gt $(( MAX_MINUTES * 60 )) ]; then
  echo "ERROR: el video dura $(( DURATION / 60 )) min (> --max-minutes $MAX_MINUTES)." >&2
  echo "       Whisper sin GPU tarda ~1,8× eso. --allow-long si igual lo querés." >&2
  exit 2
fi

# Upscale para el OCR: a 360p tesseract pega las palabras entre sí ("CLAUDE.md" →
# "CLAWE.ed"), y ese ruido después envenena el vocabulario de Whisper.
if [ "$DO_OCR" = "1" ] && [ "$OCR_SCALE" = "auto" ]; then
  WIDTH="$(awk -F= '/^width=/{print $2; exit}' "$OUT/meta.txt")"
  if [ -n "${WIDTH:-}" ] && [ "$WIDTH" -gt 0 ] && [ "$WIDTH" -lt 1600 ]; then
    OCR_SCALE=$(( (1600 + WIDTH - 1) / WIDTH ))
    [ "$OCR_SCALE" -gt 3 ] && OCR_SCALE=3
  else
    OCR_SCALE=1
  fi
  echo "      fuente ${WIDTH:-?}px → OCR a x${OCR_SCALE}"
fi

# 3) Audio -----------------------------------------------------------------
S_AUDIO="$(stage_sig --param src=audio --file "$VIDEO")"
if cached audio "$S_AUDIO" && [ -s "$OUT/audio.wav" ]; then
  echo "[3/7] Audio en caché"
else
  echo "[3/7] Extrayendo audio (mono 16 kHz)…"
  low ffmpeg -y -v error -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/audio.wav"
  mark audio "$S_AUDIO" --output "$OUT/audio.wav"
fi

# 4) Frames + OCR (antes del ASR: el OCR alimenta el vocabulario) -----------
S_FRAMES="$(stage_sig --param frames_every="$FRAMES_EVERY" --file "$VIDEO")"
if cached frames "$S_FRAMES" && [ -e "$OUT/frames/f_001.jpg" ]; then
  echo "[4/7] Frames en caché"
else
  echo "[4/7] Extrayendo un frame cada ${FRAMES_EVERY}s…"
  rm -f "$OUT"/frames/f_*.jpg
  low ffmpeg -y -v error -i "$VIDEO" -vf "fps=1/${FRAMES_EVERY}" -q:v 3 "$OUT/frames/f_%03d.jpg"
  mark frames "$S_FRAMES" --output "$OUT/frames"
fi

if [ "$DO_OCR" = "1" ]; then
  if command -v tesseract >/dev/null; then
    TESS_VER="$(tesseract --version 2>/dev/null | head -n1 || true)"
    S_OCR="$(stage_sig --param ocr="$TESS_VER" --param scale="$OCR_SCALE" --file "$OUT/frames")"
    if cached ocr "$S_OCR" && [ -s "$OUT/slides-ocr.txt" ]; then
      echo "      OCR en caché"
    else
      echo "      OCR de frames con tesseract (x${OCR_SCALE})…"
      : > "$OUT/slides-ocr.txt"
      TMP_OCR="$OUT/.ocr-tmp.png"
      OCR_FAIL=0
      for f in "$OUT"/frames/f_*.jpg; do
        [ -e "$f" ] || continue
        printf '===== %s =====\n' "$(basename "$f")" >> "$OUT/slides-ocr.txt"
        img="$f"
        if [ "$OCR_SCALE" -gt 1 ]; then
          if low ffmpeg -y -v error -i "$f" -vf "scale=iw*${OCR_SCALE}:ih*${OCR_SCALE}:flags=lanczos" \
                 "$TMP_OCR" 2>/dev/null; then img="$TMP_OCR"; fi
        fi
        # Un frame que tesseract no puede leer no aborta el OCR entero (pipefail): se anota.
        if ! txt="$(low tesseract "$img" - --psm 3 2>/dev/null)"; then
          OCR_FAIL=$((OCR_FAIL + 1)); txt=""
        fi
        printf '%s\n' "$txt" | sed '/^[[:space:]]*$/d' >> "$OUT/slides-ocr.txt"
      done
      rm -f "$TMP_OCR"
      [ "$OCR_FAIL" -gt 0 ] && echo "      aviso: tesseract falló en $OCR_FAIL frame(s); quedaron vacíos" >&2
      mark ocr "$S_OCR" --output "$OUT/slides-ocr.txt"
    fi
  else
    echo "      aviso: tesseract no está instalado; salteo el OCR" >&2
    AUTO_VOCAB=0
  fi
fi

# 5) Vocabulario (sesga a Whisper con lo que dicen las slides) --------------
PROMPT="$VOCAB"
if [ "$AUTO_VOCAB" = "1" ] && [ -s "$OUT/slides-ocr.txt" ]; then
  S_VOCAB="$(stage_sig --param mode=auto2 --param extra="$VOCAB" --file "$OUT/slides-ocr.txt")"
  if cached vocab "$S_VOCAB" && [ -s "$OUT/vocab.txt" ]; then
    echo "[5/7] Vocabulario en caché"
    PROMPT="$(cat "$OUT/vocab.txt")"
  else
    echo "[5/7] Derivando vocabulario del OCR…"
    VB_ARGS=()
    [ -n "$VOCAB" ] && VB_ARGS+=(--extra "$VOCAB")
    if AUTO_TERMS="$(python3 "$SCRIPT_DIR/build_vocab.py" "$OUT/slides-ocr.txt" --min-count 2 \
                       ${VB_ARGS[@]+"${VB_ARGS[@]}"})"; then
      PROMPT="$AUTO_TERMS"
      printf '%s\n' "$PROMPT" > "$OUT/vocab.txt"
      echo "      ${#PROMPT} chars: …$(printf '%s' "$PROMPT" | tail -c 100)"
      mark vocab "$S_VOCAB" --output "$OUT/vocab.txt"
    else
      echo "      aviso: build_vocab.py falló; sigo con el --vocab manual" >&2
    fi
  fi
else
  echo "[5/7] Sin vocabulario automático (--no-auto-vocab, o --no-ocr)."
  S_VOCAB="$(stage_sig --param mode=manual --param extra="$VOCAB")"
  if [ -n "$PROMPT" ]; then
    if cached vocab "$S_VOCAB" && [ -s "$OUT/vocab.txt" ]; then
      PROMPT="$(cat "$OUT/vocab.txt")"
    else
      # El --vocab manual también respeta el presupuesto de tokens de Whisper.
      PROMPT="$(printf '%s' "$VOCAB" | python3 "$SCRIPT_DIR/build_vocab.py" - --no-ocr-terms --extra "$VOCAB")"
      printf '%s\n' "$PROMPT" > "$OUT/vocab.txt"
      mark vocab "$S_VOCAB" --output "$OUT/vocab.txt"
    fi
  fi
fi

# 6) Transcripción ---------------------------------------------------------
S_ASR="$(stage_sig --param model="$MODEL" --param lang="$WHISPER_LANG" \
                   --param prompt="$PROMPT" --file "$OUT/audio.wav")"
if cached asr "$S_ASR" && [ -s "$OUT/transcript.srt" ]; then
  echo "[6/7] Transcripción en caché (mismo audio, modelo y vocabulario)"
else
  MIN_EST=$(( ${DURATION:-0} * 18 / 600 ))
  echo "[6/7] Transcribiendo con whisper ($MODEL, $THREADS hilos, prioridad baja)…"
  echo "      sin GPU tarda ~1,8× el audio: ~${MIN_EST} min. Si se corta, esta etapa se rehace entera."
  if [ -r /proc/meminfo ]; then
    AVAIL_MB="$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
    if [ -n "${AVAIL_MB:-}" ] && [ "$AVAIL_MB" -lt 1500 ]; then
      echo "      aviso: solo ${AVAIL_MB} MB de RAM libres; whisper $MODEL usa ~1-2 GB" >&2
    fi
  fi
  rm -f "$OUT/transcript.srt" "$OUT/audio.srt"
  WHISPER_ARGS=(--model "$MODEL" --fp16 False --threads "$THREADS"
                --output_format srt --output_dir "$OUT")
  [ "$WHISPER_LANG" != "auto" ] && WHISPER_ARGS+=(--language "$WHISPER_LANG")
  [ -n "$PROMPT" ] && WHISPER_ARGS+=(--initial_prompt "$PROMPT")
  low whisper "$OUT/audio.wav" "${WHISPER_ARGS[@]}"
  if [ -f "$OUT/audio.srt" ]; then mv -f "$OUT/audio.srt" "$OUT/transcript.srt"; fi
  mark asr "$S_ASR" --output "$OUT/transcript.srt"
fi

# 7) Transcript aplanado (instantáneo: siempre se rehace) ------------------
echo "[7/7] Aplanando transcript…"
python3 "$SCRIPT_DIR/srt.py" kit "$OUT"

# Limpieza: ~250 MB por video (video + audio). Los textos y los frames quedan.
if [ "$KEEP_MEDIA" != "1" ]; then
  rm -f "$VIDEO" "$OUT/audio.wav"
  echo "      borrados video.mp4 y audio.wav (--keep-media para conservarlos)"
fi

echo
echo "Listo. Kit en: $OUT"
ls -1 "$OUT"
