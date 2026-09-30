#!/usr/bin/env python3
"""build_vocab.py — arma un vocabulario para sesgar Whisper a partir del OCR de las slides.

Whisper alucina homófonos en jerga técnica (`agentic` → "Asian", `Claude` → "Cloud",
`MCP` → "MCT"). Corregirlo después es parchear. La mejor jugada es darle a Whisper el
vocabulario correcto ANTES, con `--initial_prompt`.

Las slides son una fuente perfecta: ya tienen escrito —bien escrito— el nombre de los
productos, las siglas y la jerga del dominio.

**Presupuesto de tokens.** openai-whisper se queda con los ÚLTIMOS `n_text_ctx // 2 - 1`
(= 223) tokens del `--initial_prompt` y descarta el principio. Por eso:
  1. el prompt se recorta por TOKENS (`--max-tokens`, default 200), no por caracteres;
  2. se imprime de menor a mayor importancia: los `--extra` del usuario y los mejores
     términos quedan AL FINAL, que es lo que Whisper conserva si igual se pasa.
Con tiktoken instalado se cuenta exacto (encoding `gpt2`, el de Whisper para inglés);
si no, se estima de forma conservadora (~2,7 caracteres por token).

**Screencasts.** En un tutorial grabado de la pantalla, el OCR se llena de la interfaz
(Chrome, Bookmarks, Window…), que se repite en todos los frames y por eso pasa el
`--min-count`. Esos términos se filtran con una lista de UI, igual que los identificadores
de código (`EMA_9_21_Cross`) y las tiras aleatorias de OCR (`GWJOttwiXHO7IWAIP`).

Uso:
    build_vocab.py slides-ocr.txt                       # imprime la lista de términos
    build_vocab.py slides-ocr.txt --extra "Claude, MCP" # agrega términos tuyos (máxima prioridad)
    build_vocab.py slides-ocr.txt --json                # {terms, prompt, tokens, counts}
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

# Interfaz de navegadores y sistemas operativos: aparece en cada frame de un screencast.
UI_STOP = set("""
chrome safari firefox edge brave arc finder desktop dock menu toolbar sidebar
bookmarks bookmark window windows file edit view history help download downloads upload
search settings preferences profile share tab tabs home new open save close reload
back forward sign login logout account accounts notifications inbox extensions tools
untitled copy paste undo redo select format insert zoom fullscreen minimize
""".split())

STOP = set("""
a an the and or but if then than that this these those of to in on at by for with from
as is are was were be been being it its he she they them him his her their our your my
we you i not no yes do does did done have has had will would can could should may might
must about into over under again more most other some such only own same so too very
just also there here when where why how what which who whom whose all any both each few
nor don now s t ll ve re
""".split())

WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[+#._-][A-Za-z0-9]+)*")
# Tiras aleatorias de OCR: mayúsculas, minúsculas y mayúsculas otra vez (GWJOttwiXHO…) o
# letras y dígitos alternados muchas veces (x9Fk2Lm7…).
JUNK = re.compile(r"[A-Z]{3,}[a-z]+[A-Z]{2,}|(?:[A-Za-z]+\d+){3,}")
CHARS_PER_TOKEN = 2.7          # estimación conservadora sin tiktoken (medido: ~3,0)
WHISPER_PROMPT_TOKENS = 223    # lo que openai-whisper conserva del initial_prompt
EXTRA_SEP = re.compile(r"[,\n;]+")


def iter_tokens(text: str):
    """Devuelve (token, es_inicio_de_oración) para cada palabra del texto."""
    for m in WORD.finditer(text):
        tok = m.group(0)
        prev = text[:m.start()].rstrip()
        sent_init = (not prev) or prev[-1] in '.!?:;'
        yield tok, sent_init


MAX_PLAIN_LEN = 18
_INTERNAL_SIGNAL = re.compile(r'[A-Z0-9]')


def interesting(tok, n, mid):
    """¿Este token merece entrar al vocabulario de Whisper?

    Señales buenas: sigla corta (MCP), CamelCase (BigQuery), algo con dígitos, o una
    palabra capitalizada en medio de una oración (nombre propio).

    Señal mala: una tirada larga sin mayúscula interna ni dígitos. Casi siempre es OCR
    que pegó dos palabras ("Intelligencealonedoesn", "Jong-runningagentsin") porque la
    slide tenía el texto apretado o la resolución era baja. Meter eso en el prompt de
    Whisper es peor que no sesgarlo: le sugiere exactamente el ruido que queríamos evitar.
    """
    if '_' in tok or JUNK.search(tok):
        return False                      # identificador de código o basura de OCR: no se dice
    if tok.lower() in UI_STOP:
        return False                      # interfaz del navegador/SO (screencasts)
    if '-' in tok and (any(len(p) > 12 for p in tok.split('-'))
                       or (tok.replace('-', '').isupper() and len(tok) > 8)):
        return False                      # "PRODUCTION-SCRI": texto cortado por el OCR
    if tok.isalpha() and tok.isupper():
        return 2 <= len(tok) <= 6        # MCP, SDK, API… pero no texto en mayúsculas
    if any(c.isupper() for c in tok[1:]):
        return True                       # BigQuery, NanoBanana
    if any(c.isdigit() for c in tok):
        return True
    if len(tok) > MAX_PLAIN_LEN and not _INTERNAL_SIGNAL.search(tok[1:]):
        return False
    if mid > 0:
        return any(c in 'aeiouAEIOU' for c in tok)
    return False


_ENCODER = None


def count_tokens(text: str) -> int:
    """Tokens que ocupa `text` en el prompt de Whisper (exacto con tiktoken, si no estimado)."""
    global _ENCODER
    if _ENCODER is None:
        try:
            import tiktoken  # type: ignore
            _ENCODER = tiktoken.get_encoding('gpt2')
        except Exception:
            _ENCODER = False
    if _ENCODER:
        return len(_ENCODER.encode(' ' + text))
    return int(len(text) / CHARS_PER_TOKEN) + 1


def build(text: str, extra=(), min_count: int = 1, max_chars: int = 900, max_tokens: int = 200,
          ocr_terms: bool = True):
    """Extrae el vocabulario y devuelve (terminos, conteos).

    `terminos` está ordenado de MAYOR a menor importancia; `prompt_of()` lo invierte para
    Whisper. El recorte respeta los dos topes: caracteres y tokens.
    """
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

    cands = [(tok, n, mid) for tok, (n, mid) in counts.items()
             if ocr_terms and n >= min_count and interesting(tok, n, mid)]
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
        if count_tokens(prompt_of(out + [t])) > max_tokens:
            break
        seen.add(t)
        out.append(t)
        total += len(t) + 2
    return out, counts


def prompt_of(terms) -> str:
    """Prompt para Whisper: lo más importante AL FINAL (Whisper conserva la cola)."""
    return ', '.join(reversed(list(terms)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('ocr', help='slides-ocr.txt (o "-" para stdin)')
    ap.add_argument('--extra', action='append', default=[],
                    help='términos propios, separados por coma (repetible; máxima prioridad)')
    ap.add_argument('--min-count', type=int, default=1)
    ap.add_argument('--max-chars', type=int, default=900)
    ap.add_argument('--max-tokens', type=int, default=200,
                    help=f'tope en tokens (Whisper conserva los últimos {WHISPER_PROMPT_TOKENS})')
    ap.add_argument('--no-ocr-terms', action='store_true',
                    help='solo los --extra (para recortar un vocabulario manual al presupuesto)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args(argv)

    raw = sys.stdin.read() if a.ocr == '-' else pathlib.Path(a.ocr).read_text(
        encoding='utf-8', errors='ignore')

    extra = []
    for chunk in a.extra:
        extra.extend(EXTRA_SEP.split(chunk))

    terms, counts = build(raw, extra, a.min_count, a.max_chars, a.max_tokens,
                          ocr_terms=not a.no_ocr_terms)
    prompt = prompt_of(terms)

    if a.json:
        payload = {'terms': terms, 'prompt': prompt, 'char_count': len(prompt),
                   'tokens': count_tokens(prompt),
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
