#!/usr/bin/env bash
# x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.
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

Salida (en DIR):
  video.mp4            video bajado/original
  audio.wav            audio mono 16 kHz para ASR
  transcript.srt       transcripción con timestamps
  transcript.txt       transcripción aplanada [hh:mm:ss] texto
  frames/              frames cada N segundos (jpg)
  slides-ocr.txt       texto extraído de las slides con tesseract
  vocab.txt            vocabulario usado para sesgar Whisper
  meta.txt             metadatos (duración, resolución, fuente, fecha)

Siguiente paso:
  scripts/normalize_transcript.py <DIR>/transcript.txt --fixes fixes/anthropic-agents.tsv -o <DIR>/transcript.clean.txt
  scripts/build_manual.py <DIR> --title "..." --fixes fixes/anthropic-agents.tsv
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC=""; OUT="./xvm-out"; MODEL="small"; WHISPER_LANG="auto"; VOCAB=""
FRAMES_EVERY=20; DO_OCR=1; AUTO_VOCAB=1

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --lang) WHISPER_LANG="$2"; shift 2;;
    --vocab) VOCAB="$2"; shift 2;;
    --no-auto-vocab) AUTO_VOCAB=0; shift;;
    --frames-every) FRAMES_EVERY="$2"; shift 2;;
    --no-ocr) DO_OCR=0; AUTO_VOCAB=0; shift;;
    -h|--help) usage; exit 0;;
    -*) echo "opción desconocida: $1 (ver --help)" >&2; exit 2;;
    *) SRC="$1"; shift;;
  esac
done

[ -n "$SRC" ] || { echo "ERROR: falta <url | archivo> (ver --help)" >&2; exit 1; }
case "$FRAMES_EVERY" in ''|*[!0-9]*) echo "ERROR: --frames-every debe ser un entero" >&2; exit 2;; esac

for tool in yt-dlp ffmpeg ffprobe whisper python3; do
  command -v "$tool" >/dev/null || { echo "ERROR: falta '$tool'" >&2; exit 1; }
done

NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"

mkdir -p "$OUT" "$OUT/frames"
OUT="$(cd "$OUT" && pwd)"
VIDEO="$OUT/video.mp4"

# 1) Obtener el video ------------------------------------------------------
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

# 2) Metadatos -------------------------------------------------------------
echo "[2/7] Leyendo metadatos…"
ffprobe -v error -show_entries format=duration,size \
        -show_entries stream=codec_type,width,height -of default=noprint_wrappers=1 \
        "$VIDEO" > "$OUT/meta.txt"
{
  echo "source=$SRC"; echo "fetched_utc=$(date -u +%FT%TZ)"
} >> "$OUT/meta.txt"

# 3) Audio -----------------------------------------------------------------
echo "[3/7] Extrayendo audio (mono 16 kHz)…"
ffmpeg -y -v error -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/audio.wav"

# 4) Frames + OCR (antes del ASR: el OCR alimenta el vocabulario) -----------
echo "[4/7] Extrayendo un frame cada ${FRAMES_EVERY}s…"
ffmpeg -y -v error -i "$VIDEO" -vf "fps=1/${FRAMES_EVERY}" -q:v 3 "$OUT/frames/f_%03d.jpg"
if [ "$DO_OCR" = "1" ]; then
  if command -v tesseract >/dev/null; then
    echo "      OCR de frames con tesseract…"
    : > "$OUT/slides-ocr.txt"
    for f in "$OUT"/frames/f_*.jpg; do
      [ -e "$f" ] || continue
      printf '===== %s =====\n' "$(basename "$f")" >> "$OUT/slides-ocr.txt"
      tesseract "$f" - --psm 3 2>/dev/null | sed '/^[[:space:]]*$/d' >> "$OUT/slides-ocr.txt"
    done
  else
    echo "      aviso: tesseract no está instalado; salteo el OCR" >&2
    AUTO_VOCAB=0
  fi
fi

# 5) Vocabulario (sesga a Whisper con lo que dicen las slides) --------------
PROMPT="$VOCAB"
VB_ARGS=()
[ -n "$VOCAB" ] && VB_ARGS+=(--extra "$VOCAB")
if [ "$AUTO_VOCAB" = "1" ] && [ -s "$OUT/slides-ocr.txt" ]; then
  echo "[5/7] Derivando vocabulario del OCR…"
  if AUTO_TERMS="$(python3 "$SCRIPT_DIR/build_vocab.py" "$OUT/slides-ocr.txt" --min-count 2 \
                     ${VB_ARGS[@]+"${VB_ARGS[@]}"} 2>/dev/null)"; then
    PROMPT="$AUTO_TERMS"
    printf '%s\n' "$PROMPT" > "$OUT/vocab.txt"
    echo "      ${#PROMPT} chars: $(printf '%.100s' "$PROMPT")…"
  else
    echo "      aviso: build_vocab.py falló; sigo con el --vocab manual" >&2
  fi
else
  echo "[5/7] Sin vocabulario automático (--no-auto-vocab sin OCR, o --no-ocr)."
  [ -n "$PROMPT" ] && printf '%s\n' "$PROMPT" > "$OUT/vocab.txt"
fi

# 6) Transcripción ---------------------------------------------------------
echo "[6/7] Transcribiendo con whisper ($MODEL)… (puede tardar: ~0.5x realtime sin GPU)"
WHISPER_ARGS=(--model "$MODEL" --fp16 False --threads "$NPROC"
              --output_format srt --output_dir "$OUT")
[ "$WHISPER_LANG" != "auto" ] && WHISPER_ARGS+=(--language "$WHISPER_LANG")
[ -n "$PROMPT" ] && WHISPER_ARGS+=(--initial_prompt "$PROMPT")
whisper "$OUT/audio.wav" "${WHISPER_ARGS[@]}"
if [ -f "$OUT/audio.srt" ]; then mv -f "$OUT/audio.srt" "$OUT/transcript.srt"; fi

# 7) Transcript aplanado ---------------------------------------------------
echo "[7/7] Aplanando transcript…"
python3 "$SCRIPT_DIR/srt.py" kit "$OUT"

echo
echo "Listo. Kit en: $OUT"
ls -1 "$OUT"
