#!/usr/bin/env python3
"""build_vocab.py — arma un vocabulario para sesgar Whisper a partir del OCR de las slides.

Whisper alucina homófonos en jerga técnica (`agentic` → "Asian", `Claude` → "Cloud",
`MCP` → "MCT"). Corregirlo después es parchear. La mejor jugada es darle a Whisper el
vocabulario correcto ANTES, con `--initial_prompt`.

Las slides son una fuente perfecta: ya tienen escrito —bien escrito— el nombre de los
productos, las siglas y la jerga del dominio.

Uso:
    build_vocab.py slides-ocr.txt                       # imprime la lista de términos
    build_vocab.py slides-ocr.txt --extra "Claude, MCP" # agrega términos tuyos (van primero)
    build_vocab.py slides-ocr.txt --json                # {terms, prompt, counts}
"""
import argparse
import json
import pathlib
import re
import sys

# Ruido típico del OCR de frames (headers del kit, extensiones de archivo).
NOISE = {
    'jpg', 'jpeg', 'png', 'gif', 'mp4', 'webp', 'pdf', 'txt',
    'slide', 'slides', 'frame', 'frames', 'image', 'img',
}

STOP = set("""
a an the and or but if then than that this these those of to in on at by for with from
as is are was were be been being it its he she they them him his her their our your my
we you i not no yes do does did done have has had will would can could should may might
must about into over under again more most other some such only own same so too very
just also there here when where why how what which who whom whose all any both each few
nor don now s t ll ve re
""".split())

WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[+#._-][A-Za-z0-9]+)*")
EXTRA_SEP = re.compile(r"[,\n;]+")


def iter_tokens(text: str):
    """Devuelve (token, es_inicio_de_oración) para cada palabra del texto."""
    for m in WORD.finditer(text):
        tok = m.group(0)
        prev = text[:m.start()].rstrip()
        sent_init = (not prev) or prev[-1] in '.!?:;'
        yield tok, sent_init


def build(text: str, extra=(), min_count: int = 1, max_chars: int = 900):
    """Extrae el vocabulario y devuelve (terminos, conteos)."""
    # Los headers "===== f_001.jpg =====" del kit no aportan vocabulario.
    text = '\n'.join(l for l in text.splitlines() if not l.startswith('====='))

    counts = {}
    for tok, sent_init in iter_tokens(text):
        low = tok.lower()
        if len(tok) < 2 or len(tok) > 24:
            continue
        if low in STOP or low in NOISE or tok.isdigit():
            continue
        n, mid = counts.get(tok, (0, 0))
        # mid = apariciones capitalizadas en MEDIO de una oración (nombre propio).
        mid += 1 if (not sent_init and tok[0].isupper()) else 0
        counts[tok] = (n + 1, mid)

    def interesting(tok, n, mid):
        # Siglas cortas, CamelCase, tokens con dígitos, o cualquier cosa capitalizada
        # en medio de una oración (señal fuerte de nombre propio / jerga).
        if tok.isalpha() and tok.isupper():
            return 2 <= len(tok) <= 6        # MCP, SDK, API… pero no texto en mayúsculas
        if any(c.isupper() for c in tok[1:]):
            return True                       # BigQuery, NanoBanana
        if any(c.isdigit() for c in tok):
            return True
        if mid > 0:
            return any(c in 'aeiouAEIOU' for c in tok)
        return False

    cands = [(tok, n, mid) for tok, (n, mid) in counts.items()
             if n >= min_count and interesting(tok, n, mid)]
    # Prioridad: capitalizado en medio de oración > repetido > más largo.
    cands.sort(key=lambda t: (t[2] > 0, t[1] >= 2, len(t[0])), reverse=True)

    extra_list = [e.strip() for e in extra if e.strip()]
    extra_low = {e.lower() for e in extra_list}
    terms = list(extra_list) + [t for t, _, _ in cands if t.lower() not in extra_low]

    out, total, seen = [], 0, set()
    for t in terms:
        if t in seen:
            continue
        if total + len(t) + 2 > max_chars:
            break
        seen.add(t)
        out.append(t)
        total += len(t) + 2
    return out, counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('ocr', help='slides-ocr.txt (o "-" para stdin)')
    ap.add_argument('--extra', action='append', default=[],
                    help='términos propios, separados por coma (repetible; van primero)')
    ap.add_argument('--min-count', type=int, default=1)
    ap.add_argument('--max-chars', type=int, default=900,
                    help='tope del prompt (Whisper lo trunca cerca de los 224 tokens)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args(argv)

    raw = sys.stdin.read() if a.ocr == '-' else pathlib.Path(a.ocr).read_text(
        encoding='utf-8', errors='ignore')

    extra = []
    for chunk in a.extra:
        extra.extend(EXTRA_SEP.split(chunk))

    terms, counts = build(raw, extra, a.min_count, a.max_chars)
    prompt = ', '.join(terms)

    if a.json:
        payload = {'terms': terms, 'prompt': prompt, 'char_count': len(prompt),
                   'counts': {k: {'n': v[0], 'mid_sentence': v[1]} for k, v in counts.items()}}
        salida = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        salida = prompt

    if a.out:
        pathlib.Path(a.out).write_text(salida + '\n', encoding='utf-8')
        print(f"escrito {a.out} ({len(terms)} términos)", file=sys.stderr)
    else:
        print(salida)


if __name__ == '__main__':
    main()
