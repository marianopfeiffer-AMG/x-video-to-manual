#!/usr/bin/env bash
# x-video-to-manual.sh — de un video de X (o archivo local) a un kit de manual.
#
# Uso:
#   x-video-to-manual.sh <url-x | archivo-de-video> [--out DIR] [--model small]
#                         [--lang auto] [--frames-every 20] [--no-ocr]
#
# Salida (en DIR, por defecto ./xvm-out):
#   video.mp4            video bajado/original
#   audio.wav            audio mono 16 kHz para ASR
#   transcript.srt       transcripción con timestamps
#   transcript.txt       transcripción aplanada [hh:mm:ss] texto
#   frames/              frames cada N segundos (jpg)
#   slides-ocr.txt       texto extraído de las slides con tesseract
#   meta.txt             metadatos (duración, resolución, fuente, fecha)
#
# Requiere: yt-dlp, ffmpeg/ffprobe, whisper (openai-whisper), tesseract (opcional)
set -euo pipefail

SRC=""; OUT="./xvm-out"; MODEL="small"; LANG="auto"; FRAMES_EVERY=20; DO_OCR=1

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --lang) LANG="$2"; shift 2;;
    --frames-every) FRAMES_EVERY="$2"; shift 2;;
    --no-ocr) DO_OCR=0; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) SRC="$1"; shift;;
  esac
done

[ -n "$SRC" ] || { echo "ERROR: falta <url | archivo>" >&2; exit 1; }
command -v yt-dlp  >/dev/null || { echo "ERROR: falta yt-dlp"  >&2; exit 1; }
command -v ffmpeg  >/dev/null || { echo "ERROR: falta ffmpeg"  >&2; exit 1; }
command -v whisper >/dev/null || { echo "ERROR: falta whisper" >&2; exit 1; }

mkdir -p "$OUT" "$OUT/frames"
OUT="$(cd "$OUT" && pwd)"
VIDEO="$OUT/video.mp4"

# 1) Obtener el video ------------------------------------------------------
if [ -f "$SRC" ]; then
  echo "[1/6] Copiando video local…"
  cp "$SRC" "$VIDEO"
else
  echo "[1/6] Descargando de X con yt-dlp…"
  yt-dlp -q --no-warnings -f "bv*+ba/b" --merge-output-format mp4 -o "$OUT/dl.%(ext)s" "$SRC"
  FOUND="$(ls "$OUT"/dl.* 2>/dev/null | head -1)"
  [ -n "$FOUND" ] || { echo "ERROR: yt-dlp no generó archivo" >&2; exit 1; }
  if [ "$FOUND" != "$VIDEO" ]; then
    ffmpeg -y -v error -i "$FOUND" -c copy "$VIDEO" 2>/dev/null || mv "$FOUND" "$VIDEO"
    rm -f "$FOUND"
  fi
fi

# 2) Metadatos -------------------------------------------------------------
echo "[2/6] Leyendo metadatos…"
ffprobe -v error -show_entries format=duration,size \
        -show_entries stream=codec_type,width,height -of default=noprint_wrappers=1 \
        "$VIDEO" > "$OUT/meta.txt"
{
  echo "source=$SRC"; echo "fetched_utc=$(date -u +%FT%TZ)"
} >> "$OUT/meta.txt"

# 3) Audio -----------------------------------------------------------------
echo "[3/6] Extrayendo audio (mono 16 kHz)…"
ffmpeg -y -v error -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$OUT/audio.wav"

# 4) Transcripción ---------------------------------------------------------
echo "[4/6] Transcribiendo con whisper ($MODEL)… (puede tardar: ~0.5x realtime sin GPU)"
WLANG=()
[ "$LANG" != "auto" ] && WLANG=(--language "$LANG")
whisper "$OUT/audio.wav" --model "$MODEL" --fp16 False --threads "$(nproc)" \
        --output_format srt --output_dir "$OUT" "${WLANG[@]}"
[ -f "$OUT/audio.srt" ] && mv -f "$OUT/audio.srt" "$OUT/transcript.srt"

# 5) Frames + OCR de slides ------------------------------------------------
echo "[5/6] Extrayendo un frame cada ${FRAMES_EVERY}s…"
ffmpeg -y -v error -i "$VIDEO" -vf "fps=1/${FRAMES_EVERY}" -q:v 3 "$OUT/frames/f_%03d.jpg"
if [ "$DO_OCR" = "1" ] && command -v tesseract >/dev/null; then
  echo "      OCR de frames con tesseract…"
  : > "$OUT/slides-ocr.txt"
  for f in "$OUT"/frames/f_*.jpg; do
    printf '===== %s =====\n' "$(basename "$f")" >> "$OUT/slides-ocr.txt"
    tesseract "$f" - --psm 3 2>/dev/null | sed '/^\s*$/d' >> "$OUT/slides-ocr.txt"
  done
fi

# 6) Transcript aplanado ---------------------------------------------------
echo "[6/6] Aplanando transcript…"
python3 - "$OUT" <<'PY'
import re, sys, pathlib
out = pathlib.Path(sys.argv[1])
srt = out/'transcript.srt'
if srt.exists():
    raw = srt.read_text(encoding='utf-8', errors='ignore').strip()
    lines=[]
    for b in re.split(r'\n\n+', raw):
        parts=b.split('\n')
        if len(parts)>=3:
            ts=parts[1].split(' --> ')[0].split(',')[0]
            lines.append(f"[{ts}] {' '.join(parts[2:]).strip()}")
    (out/'transcript.txt').write_text('\n'.join(lines), encoding='utf-8')
    print(f"      {len(lines)} segmentos -> transcript.txt")
PY

echo
echo "Listo. Kit en: $OUT"
ls -1 "$OUT"
