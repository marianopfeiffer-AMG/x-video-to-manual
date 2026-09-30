#!/usr/bin/env python3
"""build_manual.py — arma el BORRADOR-ÍNDICE de un manual a partir de un kit x-video-to-manual.

El borrador es un índice para el redactor, no un volcado: por cada tramo de la línea de
tiempo, el rango, 1-2 líneas de lo que había en pantalla y el arranque del relato. El texto
completo sigue en el kit (`timeline.md`, `transcript.clean.txt`, `slides-ocr.txt`) y se lee
por tramos. Antes el borrador embebía todo (~150 KB para 17 min de video): nadie lo leía.

Lee la transcripción en este orden: `transcript.clean.txt` > `transcript.txt` > `transcript.srt`.
Si existe el `.clean.txt` NO se vuelve a normalizar: se respeta lo que editó el humano.

Uso:
    build_manual.py KIT [--title "..."] [--out KIT/manual-draft.md] [--fixes anthropic-agents]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import srt  # noqa: E402

try:
    from normalize_transcript import apply_fixes, load_fixes, resolve_fixes
    _NORM_OK = True
except Exception as e:  # pragma: no cover
    _NORM_OK = False
    _NORM_ERR = e

MAX_BYTES = 30_000        # tope del borrador: más que esto no es un índice
OCR_LINES_PER_SLIDE = 2
NARRATION_CHARS = 160


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''


def transcript_lines(kit: pathlib.Path, fixes):
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
            p = resolve_fixes(f)
            if p is None:
                sys.stderr.write(f"ERROR: no existe el diccionario {f}\n")
                return lines, 'sin normalizar'
            rules.extend(load_fixes(p))
        log = []
        lines = apply_fixes('\n'.join(lines), rules, log=log).splitlines()
        print(f"      {len(log)} correcciones aplicadas", file=sys.stderr)
        return lines, 'normalizado (sin guardar: corré normalize_transcript.py para fijarlo)'

    sys.stderr.write("aviso: sin --fixes y sin transcript.clean.txt → "
                     "la transcripción va sin corregir\n")
    return lines, 'sin normalizar'


def _clip(text: str, n: int) -> str:
    text = ' '.join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + '…'


def index_from_timeline(kit: pathlib.Path):
    """Líneas del índice a partir de timeline.json (+ el relato de timeline.md por tramo)."""
    tj = kit / 'timeline.json'
    tm = _read(kit / 'timeline.md')
    if not tj.exists() or not tm:
        return None, None
    data = json.loads(tj.read_text(encoding='utf-8'))
    # Relato por tramo: timeline.md tiene "## N. [rango] · …" y debajo "- **[ts]** texto".
    tramos, cur = [], None
    for line in tm.splitlines():
        if line.startswith('## '):
            cur = {'head': line[3:].strip(), 'ocr': [], 'rel': []}
            tramos.append(cur)
        elif cur is not None and line.startswith('> '):
            cur['ocr'].append(line[2:].strip())
        elif cur is not None and line.startswith('- **['):
            cur['rel'].append(line.split('** ', 1)[-1])
    out = []
    for t in tramos:
        out.append(f"### {t['head']}")
        ocr = [l for l in t['ocr'] if len(l) > 3][:OCR_LINES_PER_SLIDE]
        if ocr:
            out.append(f"- en pantalla: {_clip(' / '.join(ocr), 140)}")
        if t['rel']:
            out.append(f"- relato: {_clip(' '.join(t['rel']), NARRATION_CHARS)}")
        out.append('')
    return out, data.get('group_by', '?')


def index_from_transcript(lines, every_s: int = 120):
    """Sin timeline: un bloque cada `every_s` segundos con el arranque del relato."""
    out, bucket, start = [], [], None
    for line in lines:
        if not line.startswith('['):
            continue
        ts = line[1:line.find(']')]
        parts = [int(x) for x in ts.split(':') if x.isdigit()]
        sec = sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
        if start is None:
            start = sec
        if sec - start >= every_s and bucket:
            out += [f"### [{srt_hhmmss(start)}]", f"- relato: {_clip(' '.join(bucket), NARRATION_CHARS)}", '']
            bucket, start = [], sec
        bucket.append(line[line.find(']') + 1:].strip())
    if bucket:
        out += [f"### [{srt_hhmmss(start or 0)}]", f"- relato: {_clip(' '.join(bucket), NARRATION_CHARS)}", '']
    return out


def srt_hhmmss(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build(kit: pathlib.Path, title: str, fixes=()) -> str:
    meta = _read(kit / 'meta.txt')
    lines, origin = transcript_lines(kit, fixes)
    idx, modo = index_from_timeline(kit)
    if idx is None:
        idx = ['> TODO — correr `scripts/align_slides.py <kit>` para pegar el relato a lo que '
               'estaba en pantalla. Mientras tanto, índice por tiempo:', ''] + \
              index_from_transcript(lines)
        modo = 'sin timeline'
    meta_lines = [l for l in meta.splitlines()
                  if l.split('=', 1)[0] in ('duration', 'width', 'height', 'source', 'fetched_utc', 'frames_every')]
    doc = '\n'.join([
        f"# {title}",
        "",
        "> **Borrador-índice** generado por `build_manual.py`. No es el manual: es el mapa para",
        "> escribirlo. El texto completo está en el kit y se lee por tramos:",
        "> `timeline.md` (relato + pantalla), `transcript.clean.txt`, `slides-ocr.txt`.",
        f"> Transcripción: **{origin}** · línea de tiempo: **{modo}**.",
        "",
        "## Metadatos",
        "```",
        *meta_lines,
        "```",
        "",
        "## TODO — Resumen ejecutivo",
        "(3-6 bullets con la tesis central.)",
        "",
        "## TODO — Secciones temáticas",
        "(Agrupar los tramos del índice en 4-8 secciones; citar el rango de tiempo.)",
        "",
        "## Índice de tramos",
        "",
        *idx,
    ])
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('kit')
    ap.add_argument('--title', default='(título pendiente)')
    ap.add_argument('--out', help='default: KIT/manual-draft.md')
    ap.add_argument('--fixes', action='append', default=[],
                    help='TSV de correcciones o nombre de un diccionario de la skill (repetible)')
    a = ap.parse_args(argv)

    kit = pathlib.Path(a.kit)
    if not kit.is_dir():
        sys.stderr.write(f"ERROR: {kit} no es un directorio de kit\n")
        return 1
    doc = build(kit, a.title, a.fixes)
    out = pathlib.Path(a.out) if a.out else kit / 'manual-draft.md'
    size = len(doc.encode('utf-8'))
    if size > MAX_BYTES:
        sys.stderr.write(f"aviso: el borrador pesa {size // 1000} KB (> {MAX_BYTES // 1000} KB); "
                         f"probablemente es un screencast con muchos tramos: releé timeline.md por partes\n")
    out.write_text(doc, encoding='utf-8')
    print(f"escrito {out} ({size} bytes)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
