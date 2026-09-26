#!/usr/bin/env python3
"""srt.py — parser único de subtítulos (SRT) para todo el pipeline.

Existe para no duplicar la lógica en el shell y en `build_manual.py`, y para
manejar los casos que rompían la versión anterior: CRLF, BOM, timestamps con
coma o punto, y bloques sin índice.

Uso:
    srt.py parse  <archivo.srt>            # imprime JSON [{start, end, text}]
    srt.py flat   <archivo.srt>            # imprime "[hh:mm:ss] texto" por línea
    srt.py kit    <dir> [--out transcript.txt]   # kit -> transcript.txt
"""
import json
import pathlib
import re
import sys

TS = re.compile(r'(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.]?(?P<ms>\d{3})?')
ARROW = re.compile(r'^\s*(?P<a>.+?)\s*-->\s*(?P<b>.+?)\s*$')


def _norm_timestamp(raw: str):
    """'00:01:02,500' -> '00:01:02'  (segundos enteros, formato hh:mm:ss)."""
    m = TS.search(raw)
    if not m:
        return None
    return f"{int(m.group('h')):02d}:{int(m.group('m')):02d}:{int(m.group('s')):02d}"


def parse(text: str):
    """Devuelve [{'start','end','text'}] tolerante a CRLF/BOM/índice opcional."""
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    segments = []
    for block in re.split(r'\n[ \t]*\n', text.strip()):
        lines = block.split('\n')
        idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if idx is None:
            continue
        m = ARROW.match(lines[idx].strip())
        if not m:
            continue
        start, end = _norm_timestamp(m.group('a')), _norm_timestamp(m.group('b'))
        if start is None:
            continue
        body = ' '.join(x.strip() for x in lines[idx + 1:] if x.strip())
        segments.append({'start': start, 'end': end, 'text': body})
    return segments


def flatten(segments):
    return '\n'.join(f"[{s['start']}] {s['text']}".rstrip() for s in segments)


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''


def _cmd_kit(args):
    kit = pathlib.Path(args[0])
    out = kit / 'transcript.txt'
    if '--out' in args:
        out = pathlib.Path(args[args.index('--out') + 1])
    srt = kit / 'transcript.srt'
    if not srt.exists():
        srt = kit / 'audio.srt'
    if not srt.exists():
        print(f"aviso: no encuentro transcript.srt en {kit}", file=sys.stderr)
        return 1
    segs = parse(_read(srt))
    out.write_text(flatten(segs), encoding='utf-8')
    print(f"      {len(segs)} segmentos -> {out.name}", file=sys.stderr)
    return 0


def main(argv):
    if len(argv) < 2 or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ('parse', 'flat'):
        raw = _read(pathlib.Path(rest[0]))
        segs = parse(raw)
        if cmd == 'parse':
            print(json.dumps(segs, ensure_ascii=False, indent=2))
        else:
            print(flatten(segs))
        return 0
    if cmd == 'kit':
        return _cmd_kit(rest)
    print(f"comando desconocido: {cmd}", file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
