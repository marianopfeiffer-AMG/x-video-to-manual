"""Tests del parser de SRT."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import srt  # noqa: E402


def test_srt_basico():
    raw = ("1\n00:00:00,000 --> 00:00:02,500\nhola mundo\n\n"
           "2\n00:00:02,500 --> 00:00:05,000\nsegunda línea\n")
    segs = srt.parse(raw)
    assert len(segs) == 2
    assert segs[0]['start'] == '00:00:00' and segs[0]['text'] == 'hola mundo'
    assert segs[1]['text'] == 'segunda línea'


def test_crlf_y_bom():
    raw = "\ufeff1\r\n00:00:00,000 --> 00:00:02,000\r\ncon CRLF\r\n\r\n"
    segs = srt.parse(raw)
    assert len(segs) == 1 and segs[0]['text'] == 'con CRLF'


def test_sin_indice():
    raw = "00:00:01,000 --> 00:00:03,000\nsin número de bloque\n"
    segs = srt.parse(raw)
    assert segs[0]['start'] == '00:00:01'


def test_multilinea_se_une():
    raw = "1\n00:00:00,000 --> 00:00:02,000\nlinea uno\nlinea dos\n"
    assert srt.parse(raw)[0]['text'] == 'linea uno linea dos'


def test_flatten():
    raw = "1\n00:00:05,000 --> 00:00:07,000\ntexto\n"
    assert srt.flatten(srt.parse(raw)) == '[00:00:05] texto'
