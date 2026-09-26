#!/usr/bin/env python3
"""normalize_transcript.py — limpia artefactos sistemáticos de Whisper.

Whisper (esp. modelos chicos) confunde palabras del dominio "agentes" con
homófonos. Este script aplica un diccionario de correcciones y deja marcadas
las ocurrencias dudosas para revisión humana.

Uso:
    normalize_transcript.py transcript.txt             # imprime a stdout
    normalize_transcript.py transcript.txt -o clean.txt
    normalize_transcript.py transcript.txt --report    # lista qué cambió
"""
import argparse
import re
import sys

FIXES = [
    (r'\bManaged Asians\b',        'Managed Agents',   'producto Anthropic'),
    (r'\bCloud Managed Asians\b',  'Claude Managed Agents', 'producto Anthropic'),
    (r'\bCloud Asian SDK\b',       'Claude Agent SDK', 'producto Anthropic'),
    (r'\bAsian SDK\b',             'Agent SDK',        'producto Anthropic'),
    (r'\bCloud Code\b',            'Claude Code',      'producto Anthropic'),
    (r'\bCloud\b',                 'Claude',           'modelo'),
    (r'\bagentic furnace\b',       'agentic harness',  'jerga'),
    (r'\bfurnace\b',               'harness',          'jerga'),
    (r'\bMCT servers\b',           'MCP servers',      'protocolo'),
    (r'\bMCT\b',                   'MCP',              'protocolo'),
    (r'\bcheckwining\b',           'checkpointing',    'jerga'),
    (r'\bWaltz\b',                 'Vault',            'feature'),
    (r'\bentropic console\b',      'Anthropic console', 'empresa'),
    (r'\bentropic\b',              'Anthropic',        'empresa'),
    (r'\bAnthropik\b',             'Anthropic',        'empresa'),
    (r'\bCWC workshops\b',         'Code with Claude workshops', 'evento'),
    (r'\bgrab, glob\b',            'grep, glob',       'tools'),
    (r'\bRalph looking move\b',    '"Ralph" loop',     'patrón de iteración'),
]

CONTEXTUAL = [
    (r'\bAsian harness(es)?\b', lambda m: 'agentic harness' + (m.group(1) or '')),
    (r'\bAsian use cases\b',    lambda m: 'agent use cases'),
    (r'\bAsian building\b',     lambda m: 'agentic building'),
    (r'\bAsian ID\b',           lambda m: 'agent ID'),
    (r'\bManaged Asians\b',     lambda m: 'Managed Agents'),
    (r'\bAsian\b',              lambda m: 'agent'),
]


def normalize(text: str, report: bool = False) -> str:
    log = []
    for pat, rep, note in FIXES:
        for m in re.finditer(pat, text):
            if report:
                log.append(f"  {m.group(0)!r} -> {rep!r}  ({note})")
        text = re.sub(pat, rep, text)
    for pat, fn in CONTEXTUAL:
        def _sub(m, fn=fn, report=report, log=log):
            new = fn(m)
            if report:
                log.append(f"  {m.group(0)!r} -> {new!r}  (contextual)")
            return new
        text = re.sub(pat, _sub, text)
    if report:
        sys.stderr.write("Correcciones aplicadas (revisar las 'contextual'):\n")
        sys.stderr.write("\n".join(log) + "\n")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('-o', '--out')
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()
    raw = open(a.path, encoding='utf-8', errors='ignore').read()
    clean = normalize(raw, report=a.report)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(clean)
        print(f"escrito {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)


if __name__ == '__main__':
    main()
