#!/usr/bin/env python3
"""stages.py — caché de etapas para el pipeline x-video-to-manual.

El pipeline es caro: Whisper sin GPU corre a ~0.5x realtime, así que un video de 20
minutos tarda ~40. La versión anterior, si se cortaba en el minuto 30, arrancaba de cero.

Cada etapa se identifica por una **firma** derivada de sus parámetros y de los archivos
de entrada. Si la firma coincide con la guardada y las salidas siguen existiendo, la
etapa se saltea. Si cambia un parámetro (p. ej. `--model`), la firma cambia y la etapa
se rehace sola: no hay forma de quedarse con una salida vieja por accidente.

Los archivos grandes no se hashean enteros — se muestrean los primeros y los últimos
64 KB más el tamaño. Alcanza para detectar un cambio real y es mucho más rápido que leer
2 GB de video. Para los archivos chicos (transcripción, OCR) se lee todo.

Uso:
    stages.py sig --param model=small --file audio.wav
    stages.py ok --state .stages.json --stage asr --sig 1a2b3c
    stages.py mark --state .stages.json --stage asr --sig 1a2b3c --output transcript.srt
    stages.py show --state .stages.json
    stages.py clear --state .stages.json
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

SAMPLE = 65536
SIG_LEN = 16


def file_sig(path, sample: int = SAMPLE):
    """Firma de un archivo o directorio. `None` si no existe.

    Archivo: tamaño + sha256 de (primeros `sample` bytes + últimos `sample` bytes).
    Directorio: cantidad, nombres y tamaños de los archivos que contiene.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    if p.is_dir():
        files = sorted(x for x in p.rglob('*') if x.is_file())
        for x in files:
            h.update(x.relative_to(p).as_posix().encode('utf-8'))
            h.update(str(x.stat().st_size).encode('ascii'))
        return f"d{len(files)}:{h.hexdigest()[:SIG_LEN]}"
    size = p.stat().st_size
    with p.open('rb') as f:
        h.update(f.read(sample))
        if size > 2 * sample:
            f.seek(-sample, 2)
            h.update(f.read(sample))
    h.update(str(size).encode('ascii'))
    return f"{size}:{h.hexdigest()[:SIG_LEN]}"


def signature(params=(), files=()):
    """Firma de una etapa: parámetros + firmas de los archivos de entrada."""
    payload = {
        'params': {str(k): str(v) for k, v in sorted(dict(params).items())},
        'files': {str(f): file_sig(f) for f in files},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:SIG_LEN]


def load(state):
    """Lee el estado. Un archivo corrupto o ausente es un estado vacío, no un error."""
    p = pathlib.Path(state)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(state, data):
    pathlib.Path(state).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding='utf-8')


def is_ok(state, stage, sig, _data=None):
    """¿La etapa está al día? Firma igual **y** todas sus salidas presentes."""
    data = load(state) if _data is None else _data
    entry = data.get(stage)
    if not entry or entry.get('sig') != sig:
        return False
    for out in entry.get('outputs', []):
        if not pathlib.Path(out).exists():
            return False
    return True


def mark(state, stage, sig, outputs=()):
    data = load(state)
    data[stage] = {
        'sig': sig,
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'outputs': [str(o) for o in outputs],
    }
    save(state, data)
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('sig', help='imprime la firma de una etapa')
    p.add_argument('--param', action='append', default=[],
                   help='par clave=valor (repetible)')
    p.add_argument('--file', action='append', default=[],
                   help='archivo o directorio de entrada (repetible)')

    p = sub.add_parser('ok', help='exit 0 si la etapa está en caché')
    p.add_argument('--state', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--sig', required=True)

    p = sub.add_parser('mark', help='guarda la firma de una etapa ya ejecutada')
    p.add_argument('--state', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--sig', required=True)
    p.add_argument('--output', action='append', default=[])

    p = sub.add_parser('show', help='muestra el estado')
    p.add_argument('--state', required=True)

    p = sub.add_parser('clear', help='borra el estado')
    p.add_argument('--state', required=True)

    a = ap.parse_args(argv)

    if a.cmd == 'sig':
        params = {}
        for item in a.param:
            k, _, v = item.partition('=')
            params[k] = v
        print(signature(params, a.file))
        return 0

    if a.cmd == 'ok':
        data = load(a.state)
        entry = data.get(a.stage)
        if is_ok(a.state, a.stage, a.sig, _data=data):
            return 0
        if not entry:
            sys.stderr.write(f"etapa {a.stage}: sin registro previo\n")
        elif entry.get('sig') != a.sig:
            sys.stderr.write(f"etapa {a.stage}: entradas cambiaron "
                             f"({entry.get('sig')} ≠ {a.sig})\n")
        else:
            faltan = [o for o in entry.get('outputs', []) if not pathlib.Path(o).exists()]
            sys.stderr.write(f"etapa {a.stage}: falta la salida {faltan}\n")
        return 1

    if a.cmd == 'mark':
        mark(a.state, a.stage, a.sig, a.output)
        return 0

    if a.cmd == 'show':
        data = load(a.state)
        if not data:
            print(f"{a.state}: vacío")
            return 0
        for stage in sorted(data):
            e = data[stage]
            outs = ', '.join(pathlib.Path(o).name for o in e.get('outputs', [])) or '—'
            print(f"{stage:8} {e.get('sig', '?'):16} {e.get('ts', '?')}  {outs}")
        return 0

    if a.cmd == 'clear':
        p = pathlib.Path(a.state)
        if p.exists():
            p.unlink()
            print(f"borrado {p}")
        return 0

    return 2


if __name__ == '__main__':
    sys.exit(main())
