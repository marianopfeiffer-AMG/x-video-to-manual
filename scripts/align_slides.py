#!/usr/bin/env python3
"""align_slides.py — pega cada tramo del relato con la slide que estaba en pantalla.

El kit ya tiene las dos mitades por separado: la transcripción (con timestamps) y el OCR de
los frames (cada ~N segundos). Falta lo obvio: **qué se veía mientras se decía cada cosa**.

Agrupa los frames que muestran la misma slide (la slide queda en pantalla muchos segundos),
arma la línea de tiempo y le cuelga a cada una el relato que le corresponde.

El agrupamiento por defecto es **visual**: compara los frames entre sí, no su texto.
Agrupar por texto (Jaccard sobre las palabras del OCR) suena bien pero se rompe con OCR
sucio: a 360p el OCR devuelve basura distinta en cada frame, no se alcanza el umbral y cada
frame termina siendo una "slide". Medido en un video real de 30 min: por texto 94 frames →
79 slides; por imagen → 25. La señal visual está separada de forma limpia (misma slide
≤ 0,05 de diferencia; distinta, ≥ 0,14).

Uso:
    align_slides.py KIT                       # escribe KIT/timeline.md y timeline.json
    align_slides.py KIT --group-by text       # agrupar por texto (si no hay ffmpeg)
    align_slides.py KIT --visual-thresh 0.05  # más exigente agrupando slides
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import srt  # noqa: E402

HEADER = re.compile(r'^=+\s*(\S+)\s*=+$')
WORD = re.compile(r'[A-Za-z0-9]{3,}')
TS_PREFIX = re.compile(r'^\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)$')
NUMBER = re.compile(r'(\d+)')

SIG_SIDE = 16                 # firma visual: 16x16 en escala de grises
SIG_BYTES = SIG_SIDE * SIG_SIDE
VISUAL_THRESH = 0.08          # diferencia media normalizada para separar dos slides


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
    m = NUMBER.search(name)
    return int(m.group(1)) if m else None


def avg_abs_diff(a, b) -> float:
    """Diferencia media normalizada (0 = idénticos, 1 = opuestos) entre dos firmas."""
    if not a or not b or len(a) != len(b):
        return 1.0
    return sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255.0)


def visual_signatures(frames_dir: pathlib.Path):
    """Firma visual de cada frame (16x16 gris), en orden numérico. `None` si no se puede.

    Una sola llamada a ffmpeg sobre la secuencia de imágenes: barato y sin dependencias
    nuevas (ffmpeg ya es requisito del pipeline).
    """
    if not frames_dir.is_dir():
        return None, None
    files = sorted((p for p in frames_dir.glob('f_*.jpg')),
                   key=lambda p: frame_index(p.name) or 0)
    if len(files) < 2:
        return None, None
    parts = [NUMBER.search(p.name) for p in files]
    nums = [int(m.group(1)) for m in parts if m]
    pads = {len(m.group(1)) for m in parts if m}
    if len(nums) != len(files) or len(pads) != 1:
        return None, None                      # numeración heterogénea: no arriesgo desalinear
    if not all(b - a == 1 for a, b in zip(nums, nums[1:])):
        return None, None                      # huecos: ffmpeg leería de menos y desalinearía
    width = pads.pop()                         # el ancho real del nombre, no el del índice
    pattern = str(frames_dir / f'f_%0{width}d.jpg')
    cmd = ['ffmpeg', '-v', 'error', '-i', pattern,
           '-vf', f'scale={SIG_SIDE}:{SIG_SIDE}:flags=area,format=gray',
           '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    try:
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        sys.stderr.write(f"aviso: no pude leer los frames con ffmpeg ({e}); "
                         f"agrupo por texto\n")
        return None, None
    n = len(raw) // SIG_BYTES
    if n != len(files):
        sys.stderr.write(f"aviso: ffmpeg devolvió {n} frames, esperaba {len(files)}; "
                         f"agrupo por texto\n")
        return None, None
    return {nums[i]: raw[i * SIG_BYTES:(i + 1) * SIG_BYTES] for i in range(n)}, nums


def group_by_visual(frames, sigs, every: int, thresh: float = VISUAL_THRESH):
    """Agrupa frames consecutivos que muestran la misma slide (según la imagen).

    Compara cada frame con el *anterior*: es lo que se midió, y tolera que la slide
tenga un elemento que se mueve (el orador, una animación) sin partir el grupo en dos.
    """
    slides = []
    prev = None
    for name, text in frames:
        idx = frame_index(name)
        t = (idx - 1) * every if idx else 0
        sig = sigs.get(idx) if idx is not None else None
        same = (slides and prev is not None and sig is not None
                and avg_abs_diff(sig, prev) <= thresh)
        if same:
            slides[-1]['frames'].append(name)
            slides[-1]['end'] = t + every
            if len(text) > len(slides[-1]['text']):     # la lectura más larga suele ser la mejor
                slides[-1]['text'], slides[-1]['words'] = text, words_of(text)
        else:
            slides.append({'start': t, 'end': t + every, 'text': text,
                           'words': words_of(text), 'frames': [name]})
        prev = sig
    return slides


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


def render_md(sections, slides, source, modo='imagen'):
    lines = ["# Línea de tiempo (slides + relato)", "",
             f"> Generado por `align_slides.py` desde {source} (slides agrupadas por {modo}). "
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
    ap.add_argument('--thresh', type=float, default=0.6,
                    help='umbral de Jaccard cuando se agrupa por texto')
    ap.add_argument('--visual-thresh', type=float, default=VISUAL_THRESH,
                    help='diferencia visual máxima dentro de una misma slide')
    ap.add_argument('--group-by', choices=('auto', 'visual', 'text'), default='auto')
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

    sigs, _nums = (None, None)
    if a.group_by in ('auto', 'visual'):
        sigs, _nums = visual_signatures(kit / 'frames')
        if sigs is None and a.group_by == 'visual':
            sys.stderr.write("ERROR: --group-by visual pero no pude leer los frames\n")
            return 1
    modo = 'imagen' if sigs else 'texto'
    if sigs:
        slides = group_by_visual(frames, sigs, every, a.visual_thresh)
    else:
        slides = group_slides(frames, every, a.thresh)

    segs = parse_transcript(kit)
    if not segs:
        sys.stderr.write("ERROR: no encontré transcripción (.srt ni .txt)\n")
        return 1
    sections = attach(segs, slides)

    md = render_md(sections, slides, ocr_p.name, modo)
    out = pathlib.Path(a.out) if a.out else kit / 'timeline.md'
    out.write_text(md, encoding='utf-8')

    payload = {
        'frames_every': every,
        'group_by': modo,
        'slides': [{'start': s['start'], 'end': s['end'], 'frames': s['frames'],
                    'text': s['text']} for s in slides],
        'sections': [{'start': x['start'], 'end': x['end'],
                      'slide_start': x['slide']['start'] if x['slide'] else None,
                      'segments': len(x['segs'])} for x in sections],
    }
    jout = pathlib.Path(a.json_out) if a.json_out else kit / 'timeline.json'
    jout.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"{len(frames)} frames → {len(slides)} slides (por {modo}) → {len(sections)} tramos")
    print(f"escrito {out} y {jout}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
