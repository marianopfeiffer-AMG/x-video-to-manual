#!/usr/bin/env python3
"""build_manual.py — arma un borrador de manual a partir de un kit x-video-to-manual.

Consume la salida de x-video-to-manual.sh (meta.txt, transcript.srt,
slides-ocr.txt) y produce manual-draft.md: un esqueleto con la transcripción
corregida, el OCR de las slides y placeholders que el agente/redactor completa.

Uso:
    build_manual.py /ruta/al/kit [--title "..."] [--out manual-draft.md]
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from normalize_transcript import normalize
except Exception:
    def normalize(t, report=False):
        return t


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''


def srt_to_lines(raw: str):
    out = []
    for b in re.split(r'\n\n+', raw.strip()):
        parts = b.split('\n')
        if len(parts) >= 3:
            ts = parts[1].split(' --> ')[0].split(',')[0]
            out.append(f"[{ts}] {' '.join(parts[2:]).strip()}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('kit')
    ap.add_argument('--title', default='(título pendiente)')
    ap.add_argument('--out', default='manual-draft.md')
    a = ap.parse_args()

    kit = pathlib.Path(a.kit)
    meta = read(kit / 'meta.txt')
    srt = read(kit / 'transcript.srt') or read(kit / 'audio.srt')
    ocr = read(kit / 'slides-ocr.txt')
    tx = read(kit / 'transcript.txt')
    lines = srt_to_lines(srt) if srt else (tx.splitlines() if tx else [])
    transcript = normalize('\n'.join(lines))

    slides = [l for l in ocr.splitlines() if not l.startswith('=====') and len(l) > 3]

    doc = f"""# {a.title}

> Borrador generado automáticamente por `build_manual.py`. **Completar** las secciones
> marcadas con TODO cruzando la transcripción y el OCR de slides.

## Metadatos
```
{meta.strip()}
```

## TODO — Resumen ejecutivo
(3-6 bullets con la tesis central.)

## TODO — Secciones temáticas
(Agrupar por bloques de tiempo usando los timestamps del apéndice.)

## TODO — Diagramas
(Reconstruir los diagramas de las slides a partir del OCR y del relato.)

## Apéndice A — Texto detectado en las slides (OCR)
```
{chr(10).join(slides[:400])}
```

## Apéndice B — Transcripción corregida
```
{transcript}
```
"""
    pathlib.Path(a.out).write_text(doc, encoding='utf-8')
    print(f"escrito {a.out} ({len(doc)} bytes)")


if __name__ == '__main__':
    main()
