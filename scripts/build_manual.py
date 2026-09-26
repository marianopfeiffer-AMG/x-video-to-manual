#!/usr/bin/env python3
"""build_manual.py — arma un borrador de manual a partir de un kit x-video-to-manual.

Lee (en este orden de prioridad): `transcript.clean.txt` > `transcript.txt` > `transcript.srt`.
Si existe el `.clean.txt` NO se vuelve a normalizar: se respeta lo que editó el humano.

Uso:
    build_manual.py /ruta/al/kit [--title "..."] [--out manual-draft.md] [--fixes fixes/x.tsv]
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import srt  # noqa: E402

try:
    from normalize_transcript import load_fixes, apply_fixes
    _NORM_OK = True
except Exception as e:  # pragma: no cover
    _NORM_OK = False
    _NORM_ERR = e

OCR_MAX_LINES = 400


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''


def _transcript_lines(kit: pathlib.Path, fixes):
    """Devuelve (lineas, origen). Prioriza el archivo editado a mano."""
    clean = kit / 'transcript.clean.txt'
    if clean.exists():
        print(f"      usando {clean.name} (sin renormalizar)", file=sys.stderr)
        return clean.read_text(encoding='utf-8', errors='ignore').splitlines(), clean.name

    plain = kit / 'transcript.txt'
    raw = _read(plain)
    if not raw:
        for name in ('transcript.srt', 'audio.srt'):
            if (kit / name).exists():
                raw = srt.flatten(srt.parse(_read(kit / name)))
                break

    lines = raw.splitlines()
    if fixes:
        if not _NORM_OK:
            sys.stderr.write(f"ERROR: no pude importar el normalizador: {_NORM_ERR}\n")
            return lines, 'sin normalizar'
        rules = []
        for f in fixes:
            rules.extend(load_fixes(pathlib.Path(f)))
        log = []
        lines = apply_fixes('\n'.join(lines), rules, log=log).splitlines()
        print(f"      {len(log)} correcciones aplicadas", file=sys.stderr)
        return lines, 'normalizado'

    sys.stderr.write("aviso: sin --fixes y sin transcript.clean.txt → "
                     "la transcripción va sin corregir\n")
    return lines, 'sin normalizar'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('kit')
    ap.add_argument('--title', default='(título pendiente)')
    ap.add_argument('--out', default='manual-draft.md')
    ap.add_argument('--fixes', action='append', default=[],
                    help='TSV de correcciones (repetible)')
    a = ap.parse_args(argv)

    kit = pathlib.Path(a.kit)
    meta = _read(kit / 'meta.txt')
    ocr = _read(kit / 'slides-ocr.txt')
    timeline = _read(kit / 'timeline.md')
    lines, origin = _transcript_lines(kit, a.fixes)
    transcript = '\n'.join(lines)

    if timeline:
        timeline_block = timeline.strip()
    else:
        timeline_block = ('TODO — correr `scripts/align_slides.py <kit>` para pegar cada '
                          'tramo del relato a la slide que estaba en pantalla.')

    slides = [l for l in ocr.splitlines() if not l.startswith('=====') and len(l) > 3]
    if len(slides) > OCR_MAX_LINES:
        print(f"aviso: el OCR tiene {len(slides)} líneas; recorto a {OCR_MAX_LINES} "
              f"(el resto queda en slides-ocr.txt)", file=sys.stderr)
        slides = slides[:OCR_MAX_LINES]

    doc = f"""# {a.title}

> Borrador generado automáticamente por `build_manual.py`. **Completar** las secciones
> marcadas con TODO cruzando la transcripción y el OCR de slides.
> Transcripción: **{origin}**.

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

## Línea de tiempo (slides + relato)
{timeline_block}

## Apéndice A — Texto detectado en las slides (OCR)
```
{chr(10).join(slides)}
```

## Apéndice B — Transcripción
```
{transcript}
```
"""
    pathlib.Path(a.out).write_text(doc, encoding='utf-8')
    print(f"escrito {a.out} ({len(doc)} bytes)")


if __name__ == '__main__':
    main()
