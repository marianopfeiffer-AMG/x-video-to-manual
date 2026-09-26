#!/usr/bin/env python3
"""normalize_transcript.py — corrige artefactos de Whisper usando un diccionario externo.

Por defecto **no modifica nada**. Las reglas viven en un archivo TSV que se pasa con
`--fixes`; así el mismo motor sirve para dominios distintos sin tocar el código, y no
hay reglas globales que rompan texto legítimo (p. ej. "Google Cloud" → "Google Claude").

Formato del TSV (sin encabezado, `#` para comentarios):
    <patrón regex>\t<reemplazo literal>\t<nota opcional>\t<prioridad opcional>

Las reglas se ordenan solas: primero por prioridad (mayor = antes; default 100) y después
por longitud de patrón descendente, para que las específicas ganen sobre las genéricas.
La prioridad existe porque un patrón con lookaheads puede ser *largo en caracteres* pero
*genérico en alcance* (ver la regla de "Cloud"). Se deduplican.

Uso:
    normalize_transcript.py transcript.txt --fixes references/fixes/anthropic-agents.tsv -o clean.txt
    normalize_transcript.py transcript.txt --fixes a.tsv --fixes b.tsv --report
"""
import argparse
import datetime as _dt
import json
import pathlib
import re
import sys


def load_fixes(path: pathlib.Path):
    """Lee un TSV y devuelve reglas deduplicadas, ordenadas por prioridad y longitud."""
    rules, seen, skipped = [], set(), []
    for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 2 or not parts[0]:
            skipped.append(lineno)
            continue
        pat = parts[0]
        rep = parts[1]
        note = parts[2] if len(parts) > 2 else ''
        priority = 100
        if len(parts) > 3 and parts[3].strip():
            try:
                priority = int(parts[3])
            except ValueError:
                sys.stderr.write(
                    f"aviso: {path}:{lineno}: prioridad inválida {parts[3]!r}, uso 100\n")
        key = (pat, rep)
        if key in seen:
            continue
        seen.add(key)
        rules.append((pat, rep, note, priority, str(path), lineno))
    if skipped:
        sys.stderr.write(f"aviso: {path}: líneas ignoradas (faltan columnas): {skipped}\n")
    rules.sort(key=lambda r: (-r[3], -len(r[0])))
    return rules


def apply_fixes(text: str, rules, log=None):
    for pat, rep, note, priority, src, lineno in rules:
        def _sub(m, rep=rep, note=note, src=src, lineno=lineno):
            if log is not None:
                log.append({
                    'original': m.group(0),
                    'corrected': rep,
                    'rule': pat,
                    'note': note,
                    'source': f"{src}:{lineno}",
                })
            return rep
        try:
            text = re.sub(pat, _sub, text)
        except re.error as e:
            sys.stderr.write(f"aviso: regex inválida en {src}:{lineno}: {pat!r} ({e})\n")
    return text


def normalize(text: str, rules=(), report=None):
    return apply_fixes(text, rules, log=report)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Normaliza una transcripción con un diccionario TSV.")
    ap.add_argument('path')
    ap.add_argument('-o', '--out', help='archivo de salida (default: stdout)')
    ap.add_argument('--fixes', action='append', default=[],
                    help='TSV de reglas (repetible). Sin esto no se modifica nada.')
    ap.add_argument('--report', nargs='?', const='corrections.json', default=None,
                    help='escribe un JSON con cada corrección (default: corrections.json)')
    a = ap.parse_args(argv)

    raw = pathlib.Path(a.path).read_text(encoding='utf-8', errors='ignore')

    rules = []
    for f in a.fixes:
        p = pathlib.Path(f)
        if not p.exists():
            sys.stderr.write(f"ERROR: no existe el diccionario {p}\n")
            return 1
        rules.extend(load_fixes(p))

    if not rules:
        sys.stderr.write("aviso: sin --fixes → el texto sale sin cambios "
                         "(es el comportamiento por diseño)\n")

    log = []
    clean = apply_fixes(raw, rules, log=log)

    if a.out:
        pathlib.Path(a.out).write_text(clean, encoding='utf-8')
        print(f"escrito {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)

    if a.report:
        payload = {
            'generated_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
            'input': str(a.path),
            'fixes': [str(f) for f in a.fixes],
            'rule_count': len(rules),
            'corrections': log,
        }
        pathlib.Path(a.report).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{len(log)} correcciones -> {a.report}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
