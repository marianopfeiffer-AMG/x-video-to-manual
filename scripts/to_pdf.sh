#!/usr/bin/env bash
# to_pdf.sh — exporta un manual Markdown a PDF (y deja el HTML intermedio al lado).
#
# Camino por defecto: python-markdown → HTML con estilos → wkhtmltopdf.
# Si no hay wkhtmltopdf pero sí pandoc, usa pandoc. No hace falta nada más.
#
# Uso:
#   to_pdf.sh manual.md              # → manual.pdf (y manual.html)
#   to_pdf.sh manual.md --out x.pdf
set -euo pipefail

[ $# -ge 1 ] || { echo "uso: to_pdf.sh <manual.md> [--out archivo.pdf]" >&2; exit 2; }
case "$1" in -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac

MD="$1"; shift
OUT="${MD%.md}.pdf"
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    *) echo "opción desconocida: $1" >&2; exit 2;;
  esac
done
[ -f "$MD" ] || { echo "ERROR: no existe $MD" >&2; exit 1; }
HTML="${OUT%.pdf}.html"

if command -v wkhtmltopdf >/dev/null 2>&1 && python3 -c "import markdown" 2>/dev/null; then
  python3 - "$MD" "$HTML" <<'PY'
import pathlib, sys, markdown, html
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
body = markdown.markdown(src.read_text(encoding="utf-8"),
                         extensions=["tables", "fenced_code", "toc", "sane_lists"])
title = html.escape(src.stem)
css = """
body{font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;font-size:11pt;
     line-height:1.5;color:#1d1d1f;max-width:46em;margin:2em auto;padding:0 1em}
h1{font-size:20pt;border-bottom:2px solid #333;padding-bottom:.2em}
h2{font-size:15pt;margin-top:1.6em;border-bottom:1px solid #ccc}
h3{font-size:12.5pt}
code,pre{font-family:Menlo,Consolas,monospace;font-size:9pt;background:#f4f4f5}
pre{padding:.7em;white-space:pre-wrap;word-wrap:break-word;border-radius:4px}
table{border-collapse:collapse;margin:1em 0}td,th{border:1px solid #ccc;padding:.3em .6em}
blockquote{border-left:3px solid #999;margin:0;padding-left:1em;color:#555}
"""
dst.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
               f"<style>{css}</style></head><body>{body}</body></html>", encoding="utf-8")
PY
  nice -n 19 wkhtmltopdf --quiet --enable-local-file-access --encoding utf-8 \
       --page-size A4 --margin-top 15mm --margin-bottom 15mm "$HTML" "$OUT"
elif command -v pandoc >/dev/null 2>&1; then
  nice -n 19 pandoc "$MD" -o "$OUT"
else
  echo "ERROR: hace falta wkhtmltopdf (+ pip install markdown) o pandoc" >&2
  exit 1
fi
echo "escrito $OUT"
