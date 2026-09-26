#!/usr/bin/env python3
"""align_slides.py — pega cada tramo del relato con la slide que estaba en pantalla.

El kit ya tiene las dos mitades por separado: la transcripción (con timestamps) y el OCR de
los frames (cada ~N segundos). Falta lo obvio: **qué se veía mientras se decía cada cosa**.

Esto agrupa los frames que muestran la misma slide (son muchos, la slide queda en pantalla),
arma la línea de tiempo de slides y le cuelga a cada una el relato que le corresponde.

Uso:
    align_slides.py KIT                       # escribe KIT/timeline.md y timeline.json
    align_slides.py KIT --thresh 0.5          # más agresivo juntando slides parecidas
    align_slides.py KIT --frames-every 10     # si meta.txt no lo tiene
"""
import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import srt  # noqa: E402

HEADER = re.compile(r'^=+\s*(\S+)\s*=+$')
WORD = re.compile(r'[A-Za-z0-9]{3,}')
TS_PREFIX = re.compile(r'^\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)$')


def hhmmss(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def to_sec(t: str) -> float:
    parts = [int(p) for p in t.split(':')]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_ocr(text: str):
    """[(nombre_de_frame, texto_ocr), …] a partir de slides-ocr.txt."""
    frames, name, buf = [], None, []
    for line in text.splitlines():
        m = HEADER.match(line.strip())
        if m:
            if name is not None:
                frames.append((name, '\n'.join(buf).strip()))
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        frames.append((name, '\n'.join(buf).strip()))
    return frames


def words_of(text: str):
    return {w.lower() for w in WORD.findall(text)}


def jaccard(a, b) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def frame_index(name: str):
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else None


def group_slides(frames, every: int, thresh: float = 0.6, min_words: int = 3):
    """Junta frames consecutivos que muestran la misma slide → lista de slides con rango."""
    slides = []
    for name, text in frames:
        idx = frame_index(name)
        t = (idx - 1) * every if idx else 0
        w = words_of(text)

        if len(w) < min_words:          # frame con poco texto
            if slides:                  # …extiende la slide que está en pantalla
                slides[-1]['frames'].append(name)
                slides[-1]['end'] = t + every
            elif w:                     # …o es la placa de título: no la tires
                slides.append({'start': t, 'end': t + every, 'text': text,
                               'words': w, 'frames': [name]})
            continue

        if slides:
            last = slides[-1]
            contención = len(w & last['words']) / len(w) if last['words'] else 0.0
            if jaccard(w, last['words']) >= thresh or contención >= 0.9:
                last['frames'].append(name)
                last['end'] = t + every
                if len(text) > len(last['text']):     # nos quedamos con la lectura más larga
                    last['text'], last['words'] = text, w
                continue

        slides.append({'start': t, 'end': t + every, 'text': text,
                       'words': w, 'frames': [name]})
    return slides


def parse_transcript(kit: pathlib.Path):
    """Segmentos con timestamps: del .srt si está; si no, del .txt aplanado."""
    for name in ('transcript.srt', 'audio.srt'):
        p = kit / name
        if p.exists():
            segs = srt.parse(p.read_text(encoding='utf-8', errors='ignore'))
            return [{'start': to_sec(s['start']), 'end': to_sec(s['end']), 'text': s['text']}
                    for s in segs]
    p = kit / 'transcript.txt'
    if p.exists():
        out = []
        for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            m = TS_PREFIX.match(line.strip())
            if not m:
                continue
            h, mi, s, text = m.group(1), m.group(2), m.group(3), m.group(4)
            start = int(h) * 3600 + int(mi) * 60 + int(s or 0)
            out.append({'start': start, 'end': start, 'text': text})
        return out
    return []


def attach(segs, slides):
    """Asigna a cada segmento la slide que estaba en pantalla, y agrupa consecutivos."""
    for s in segs:
        activa = None
        for cand in slides:
            if cand['start'] <= s['start']:
                activa = cand
            else:
                break
        s['slide'] = activa

    out = []
    for s in segs:
        if out and out[-1]['slide'] is s['slide']:
            out[-1]['end'] = max(out[-1]['end'], s['end'])
            out[-1]['segs'].append(s)
        else:
            out.append({'slide': s['slide'], 'start': s['start'], 'end': s['end'], 'segs': [s]})
    return out


def render_md(sections, slides, source):
    lines = ["# Línea de tiempo (slides + relato)", "",
             f"> Generado por `align_slides.py` desde {source}. "
             f"{len(slides)} slides, {len(sections)} tramos.", ""]
    for i, sec in enumerate(sections, 1):
        sl = sec['slide']
        rango = f"{hhmmss(sec['start'])}–{hhmmss(sec['end'])}"
        if sl is None:
            lines += [f"## {i}. [{rango}] · *(sin slide)*", ""]
        else:
            lines += [f"## {i}. [{rango}] · slide `{sl['frames'][0]}`", ""]
            lines += ["> " + l for l in sl['text'].splitlines() if l.strip()]
            lines += [""]
        for s in sec['segs']:
            lines.append(f"- **[{hhmmss(s['start'])}]** {s['text']}")
        lines.append("")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('kit')
    ap.add_argument('--frames-every', type=int)
    ap.add_argument('--thresh', type=float, default=0.6)
    ap.add_argument('--out')
    ap.add_argument('--json-out')
    a = ap.parse_args(argv)

    kit = pathlib.Path(a.kit)
    ocr_p = kit / 'slides-ocr.txt'
    if not ocr_p.exists():
        sys.stderr.write(f"ERROR: no hay {ocr_p} (¿corriste sin OCR?)\n")
        return 1

    every = a.frames_every
    if every is None:
        meta = kit / 'meta.txt'
        if meta.exists():
            m = re.search(r'^frames_every=(\d+)', meta.read_text(), re.M)
            every = int(m.group(1)) if m else None
    if not every:
        every = 20
        sys.stderr.write("aviso: no sé el intervalo de frames; asumo 20s "
                         "(pasá --frames-every para corregirlo)\n")

    frames = parse_ocr(ocr_p.read_text(encoding='utf-8', errors='ignore'))
    slides = group_slides(frames, every, a.thresh)
    segs = parse_transcript(kit)
    if not segs:
        sys.stderr.write("ERROR: no encontré transcripción (.srt ni .txt)\n")
        return 1
    sections = attach(segs, slides)

    md = render_md(sections, slides, ocr_p.name)
    out = pathlib.Path(a.out) if a.out else kit / 'timeline.md'
    out.write_text(md, encoding='utf-8')

    payload = {
        'frames_every': every,
        'slides': [{'start': s['start'], 'end': s['end'], 'frames': s['frames'],
                    'text': s['text']} for s in slides],
        'sections': [{'start': x['start'], 'end': x['end'],
                      'slide_start': x['slide']['start'] if x['slide'] else None,
                      'segments': len(x['segs'])} for x in sections],
    }
    jout = pathlib.Path(a.json_out) if a.json_out else kit / 'timeline.json'
    jout.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"{len(frames)} frames → {len(slides)} slides → {len(sections)} tramos")
    print(f"escrito {out} y {jout}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
