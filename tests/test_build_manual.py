"""Tests del borrador-índice (scripts/build_manual.py)."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_manual  # noqa: E402

TIMELINE_MD = """# Línea de tiempo (slides + relato)

> Generado por `align_slides.py` desde slides-ocr.txt (slides agrupadas por imagen). 2 slides, 2 tramos.

## 1. [00:00–00:40] · slide `f_001.jpg`

> Claude Managed Agents
> Production infrastructure

- **[00:00]** Welcome to the talk.
- **[00:20]** Today we ship agents.

## 2. [00:40–01:20] · slide `f_003.jpg`

> Messages API

- **[00:40]** First, the Messages API.
"""


def _kit(tmp_path, clean=True, timeline=True, long=False):
    kit = tmp_path / 'kit'
    kit.mkdir()
    (kit / 'meta.txt').write_text('duration=80.0\nwidth=1920\nsource=/opt/secreto/src.mp4\n'
                                  'codec_type=video\nframes_every=20\n')
    lines = [f"[00:{i:02d}] cloud code line {i}" for i in range(0, 60, 2)]
    (kit / 'transcript.txt').write_text('\n'.join(lines))
    if clean:
        (kit / 'transcript.clean.txt').write_text('[00:00] editado a mano\n')
    if timeline:
        md = TIMELINE_MD
        if long:
            md += ''.join(f"\n## {i}. [00:{i:02d}–00:{i:02d}] · slide `f_{i:03d}.jpg`\n\n> "
                          + 'x' * 300 + "\n\n- **[00:00]** " + 'relato ' * 60 + "\n"
                          for i in range(3, 400))
        (kit / 'timeline.md').write_text(md)
        (kit / 'timeline.json').write_text(json.dumps({'group_by': 'imagen'}))
    return kit


def test_usa_el_clean_sin_renormalizar(tmp_path):
    kit = _kit(tmp_path)
    doc = build_manual.build(kit, 'T', fixes=['anthropic-agents'])
    assert 'transcript.clean.txt' in doc


def test_indice_desde_el_timeline(tmp_path):
    kit = _kit(tmp_path)
    doc = build_manual.build(kit, 'Mi charla')
    assert '### 1. [00:00–00:40] · slide `f_001.jpg`' in doc
    assert 'en pantalla: Claude Managed Agents / Production infrastructure' in doc
    assert 'relato: Welcome to the talk. Today we ship agents.' in doc
    assert 'línea de tiempo: **imagen**' in doc


def test_no_filtra_rutas_ni_campos_irrelevantes(tmp_path):
    doc = build_manual.build(_kit(tmp_path), 'T')
    assert 'codec_type' not in doc


def test_sin_timeline_indice_por_tiempo_y_todo(tmp_path):
    kit = _kit(tmp_path, clean=False, timeline=False)
    doc = build_manual.build(kit, 'T', fixes=['anthropic-agents'])
    assert 'TODO' in doc and 'align_slides.py' in doc
    assert 'Claude Code' in doc                 # aplicó el diccionario por nombre


def test_salida_por_defecto_dentro_del_kit_y_tamaño(tmp_path, monkeypatch):
    kit = _kit(tmp_path, long=True)
    monkeypatch.chdir(tmp_path)
    assert build_manual.main([str(kit), '--title', 'T']) == 0
    out = kit / 'manual-draft.md'
    assert out.exists() and not (tmp_path / 'manual-draft.md').exists()
    # 400 tramos con 300 chars de OCR y 420 de relato cada uno: el índice los recorta.
    assert out.stat().st_size < 400 * 400
