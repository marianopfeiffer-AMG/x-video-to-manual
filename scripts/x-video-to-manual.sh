#!/usr/bin/env bash
# x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.
#
# Reanudable: cada etapa se saltea si sus entradas no cambiaron (ver scripts/stages.py).
# Con --force se ignora la caché y se rehace todo.
#
# Requiere: yt-dlp, ffmpeg/ffprobe, whisper (openai-whisper). Opcional: tesseract.
set -euo pipefail

usage() {
  cat <<'EOF'
x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.

Uso:
  x-video-to-manual.sh <url-x | archivo-de-video> [opciones]

Opciones:
  --out DIR            directorio de salida (default: ./xvm-out)
  --model NOMBRE       modelo de Whisper (default: small)
  --lang CODIGO        idioma para Whisper (default: autodetectar)
  --vocab "a, b, c"    términos extra para sesgar Whisper (se suman a los del OCR)
  --no-auto-vocab      no derivar el vocabulario del OCR de las slides
  --frames-every N     un frame cada N segundos (default: 20)
  --no-ocr             no correr tesseract sobre los frames
  --ocr-scale N|auto   upscale de los frames antes del OCR (default: auto)
  --force              rehacer todo, ignorando la caché de etapas

Salida (en DIR):
  video.mp4            video bajado/original
  audio.wav            audio mono 16 kHz para ASR
  transcript.srt       transcripción con timestamps
  transcript.txt       transcripción aplanada [hh:mm:ss] texto
  frames/              frames cada N segundos (jpg)
  slides-ocr.txt       texto extraído de las slides con tesseract
  vocab.txt            vocabulario usado para sesgar Whisper
  meta.txt             metadatos (duración, resolución, fuente, fecha)
  .stages.json         caché de etapas (permite reanudar sin reprocesar)

Siguiente paso:
  scripts/normalize_transcript.py <DIR>/transcript.txt --fixes references/fixes/anthropic-agents.tsv -o <DIR>/transcript.clean.txt
  scripts/align_slides.py <DIR>            # pega el relato a las slides → timeline.md
  scripts/build_manual.py <DIR> --title "..." --fixes references/fixes/anthropic-agents.tsv
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC=""; OUT="./xvm-out"; MODEL="small"; WHISPER_LANG="auto"; VOCAB=""
FRAMES_EVERY=20; DO_OCR=1; AUTO_VOCAB=1; FORCE=0; OCR_SCALE="auto"; WIDTH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --lang) WHISPER_LANG="$2"; shift 2;;
    --vocab) VOCAB="$2"; shift 2;;
    --no-auto-vocab) AUTO_VOCAB=0; shift;;
    --frames-every) FRAMES_EVERY="$2"; shift 2;;
    --no-ocr) DO_OCR=0; AUTO_VOCAB=0; shift;;
    --ocr-scale) OCR_SCALE="$2"; shift 2;;
    --force) FORCE=1; shift;;
    -h|--help) usage; exit 0;;
    -*) echo "opción desconocida: $1 (ver --help)" >&2; exit 2;;
    *) SRC="$1"; shift;;
  esac
done

[ -n "$SRC" ] || { echo "ERROR: falta <url | archivo> (ver --help)" >&2; exit 1; }
case "$FRAMES_EVERY" in ''|*[!0-9]*) echo "ERROR: --frames-every debe ser un entero" >&2; exit 2;; esac
case "$OCR_SCALE" in
  auto) ;;
  ''|*[!0-9]*) echo "ERROR: --ocr-scale debe ser 'auto' o un entero" >&2; exit 2;;
esac
case "$OCR_SCALE" in *[!0]*) ;; *) OCR_SCALE=1;; esac

for tool in yt-dlp ffmpeg ffprobe whisper python3; do
  command -v "$tool" >/dev/null || { echo "ERROR: falta '$tool'" >&2; exit 1; }
done

NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"

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
if [ -f "$SRC" ]; then
  S_VIDEO="$(stage_sig --param src="$SRC" --file "$SRC")"
else
  S_VIDEO="$(stage_sig --param url="$SRC")"
fi

if cached video "$S_VIDEO" && [ -s "$VIDEO" ]; then
  echo "[1/7] Video en caché (sin cambios)"
else
  if [ -f "$SRC" ]; then
    echo "[1/7] Copiando video local…"
    cp "$SRC" "$VIDEO"
  else
    echo "[1/7] Descargando de X con yt-dlp…"
    if ! yt-dlp -q --no-warnings -f "bv*+ba/b" --merge-output-format mp4 \
                -o "$OUT/dl.%(ext)s" "$SRC"; then
      cat >&2 <<'EOF'
ERROR: yt-dlp no pudo bajar el video. Caminos posibles:
  1) yt-dlp desactualizado  →  yt-dlp -U
  2) el post requiere login →  yt-dlp --cookies-from-browser firefox <url>   (opt-in, ver doc)
  3) bajalo a mano y pasá el archivo local:  x-video-to-manual.sh /ruta/video.mp4
EOF
      exit 1
    fi
    FOUND=""
    for f in "$OUT"/dl.*; do [ -e "$f" ] && FOUND="$f" && break; done
    [ -n "$FOUND" ] || { echo "ERROR: yt-dlp no generó archivo" >&2; exit 1; }
    if [ "$FOUND" != "$VIDEO" ]; then
      ffmpeg -y -v error -i "$FOUND" -c copy "$VIDEO" 2>/dev/null || mv "$FOUND" "$VIDEO"
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
{
  echo "source=$SRC"; echo "fetched_utc=$(date -u +%FT%TZ)"
  echo "frames_every=$FRAMES_EVERY"
} >> "$OUT/meta.txt"

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
  ffmpeg -y -v error -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/audio.wav"
  mark audio "$S_AUDIO" --output "$OUT/audio.wav"
fi

# 4) Frames + OCR (antes del ASR: el OCR alimenta el vocabulario) -----------
S_FRAMES="$(stage_sig --param frames_every="$FRAMES_EVERY" --file "$VIDEO")"
if cached frames "$S_FRAMES" && [ -e "$OUT/frames/f_001.jpg" ]; then
  echo "[4/7] Frames en caché"
else
  echo "[4/7] Extrayendo un frame cada ${FRAMES_EVERY}s…"
  rm -f "$OUT"/frames/f_*.jpg
  ffmpeg -y -v error -i "$VIDEO" -vf "fps=1/${FRAMES_EVERY}" -q:v 3 "$OUT/frames/f_%03d.jpg"
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
      for f in "$OUT"/frames/f_*.jpg; do
        [ -e "$f" ] || continue
        printf '===== %s =====\n' "$(basename "$f")" >> "$OUT/slides-ocr.txt"
        if [ "$OCR_SCALE" -gt 1 ]; then
          ffmpeg -y -v error -i "$f" -vf "scale=iw*${OCR_SCALE}:ih*${OCR_SCALE}:flags=lanczos" \
                 "$TMP_OCR" 2>/dev/null || cp "$f" "$TMP_OCR"
          tesseract "$TMP_OCR" - --psm 3 2>/dev/null | sed '/^[[:space:]]*$/d' >> "$OUT/slides-ocr.txt"
        else
          tesseract "$f" - --psm 3 2>/dev/null | sed '/^[[:space:]]*$/d' >> "$OUT/slides-ocr.txt"
        fi
      done
      rm -f "$TMP_OCR"
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
  S_VOCAB="$(stage_sig --param mode=auto --param extra="$VOCAB" --file "$OUT/slides-ocr.txt")"
  if cached vocab "$S_VOCAB" && [ -s "$OUT/vocab.txt" ]; then
    echo "[5/7] Vocabulario en caché"
    PROMPT="$(cat "$OUT/vocab.txt")"
  else
    echo "[5/7] Derivando vocabulario del OCR…"
    VB_ARGS=()
    [ -n "$VOCAB" ] && VB_ARGS+=(--extra "$VOCAB")
    if AUTO_TERMS="$(python3 "$SCRIPT_DIR/build_vocab.py" "$OUT/slides-ocr.txt" --min-count 2 \
                       ${VB_ARGS[@]+"${VB_ARGS[@]}"} 2>/dev/null)"; then
      PROMPT="$AUTO_TERMS"
      printf '%s\n' "$PROMPT" > "$OUT/vocab.txt"
      echo "      ${#PROMPT} chars: $(printf '%.100s' "$PROMPT")…"
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
  echo "[6/7] Transcribiendo con whisper ($MODEL)… (puede tardar: ~0.5x realtime sin GPU)"
  rm -f "$OUT/transcript.srt" "$OUT/audio.srt"
  WHISPER_ARGS=(--model "$MODEL" --fp16 False --threads "$NPROC"
                --output_format srt --output_dir "$OUT")
  [ "$WHISPER_LANG" != "auto" ] && WHISPER_ARGS+=(--language "$WHISPER_LANG")
  [ -n "$PROMPT" ] && WHISPER_ARGS+=(--initial_prompt "$PROMPT")
  whisper "$OUT/audio.wav" "${WHISPER_ARGS[@]}"
  if [ -f "$OUT/audio.srt" ]; then mv -f "$OUT/audio.srt" "$OUT/transcript.srt"; fi
  mark asr "$S_ASR" --output "$OUT/transcript.srt"
fi

# 7) Transcript aplanado (instantáneo: siempre se rehace) ------------------
echo "[7/7] Aplanando transcript…"
python3 "$SCRIPT_DIR/srt.py" kit "$OUT"

echo
echo "Listo. Kit en: $OUT"
ls -1 "$OUT"
