"""Tests de la línea de tiempo (relato ↔ slides)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from align_slides import (attach, group_slides, hhmmss, parse_ocr,  # noqa: E402
                          parse_transcript, to_sec)

OCR = """===== f_001.jpg =====
Claude Managed Agents
Observability in Production

===== f_002.jpg =====
Claude Managed Agents
Observability in Production

===== f_003.jpg =====
Sandbox and Tools
Session and Credentials

===== f_004.jpg =====
"""


def test_parse_ocr():
    frames = parse_ocr(OCR)
    assert [f[0] for f in frames] == ['f_001.jpg', 'f_002.jpg', 'f_003.jpg', 'f_004.jpg']
    assert 'Observability' in frames[0][1]
    assert frames[3][1] == ''


def test_agrupa_misma_slide():
    slides = group_slides(parse_ocr(OCR), every=20)
    assert len(slides) == 2
    assert slides[0]['frames'] == ['f_001.jpg', 'f_002.jpg']
    assert slides[0]['start'] == 0 and slides[0]['end'] == 40


def test_frame_sin_texto_extiende_la_anterior():
    slides = group_slides(parse_ocr(OCR), every=20)
    assert slides[-1]['frames'] == ['f_003.jpg', 'f_004.jpg']
    assert slides[-1]['end'] == 80


def test_placa_de_titulo_con_poco_texto_no_se_pierde():
    slides = group_slides(parse_ocr("===== f_001.jpg =====\nGagan Bhat\n\n"
                                    "===== f_002.jpg =====\nClaude Managed Agents\n"),
                          every=20)
    assert slides[0]['frames'] == ['f_001.jpg']
    assert len(slides) == 2


def test_attach_y_agrupado():
    slides = group_slides(parse_ocr(OCR), every=20)
    segs = [{'start': 5, 'end': 8, 'text': 'uno'},
            {'start': 12, 'end': 15, 'text': 'dos'},
            {'start': 45, 'end': 50, 'text': 'tres'}]
    secs = attach(segs, slides)
    assert len(secs) == 2
    assert secs[0]['slide'] is slides[0] and len(secs[0]['segs']) == 2
    assert secs[1]['slide'] is slides[1]
    assert secs[0]['end'] == 15


def test_parse_transcript_desde_srt(tmp_path):
    (tmp_path / 'transcript.srt').write_text(
        "1\n00:00:05,000 --> 00:00:08,000\nhola\n", encoding='utf-8')
    segs = parse_transcript(tmp_path)
    assert segs[0]['start'] == 5 and segs[0]['text'] == 'hola'


def test_parse_transcript_desde_txt(tmp_path):
    (tmp_path / 'transcript.txt').write_text('[01:02:03] texto\n', encoding='utf-8')
    segs = parse_transcript(tmp_path)
    assert segs[0]['start'] == 3723 and segs[0]['text'] == 'texto'


def test_hhmmss_y_to_sec():
    assert hhmmss(75) == '01:15'
    assert hhmmss(3675) == '01:01:15'
    assert to_sec('01:01:15') == 3675
    assert to_sec('00:05') == 5


def test_end_to_end(tmp_path):
    (tmp_path / 'slides-ocr.txt').write_text(OCR, encoding='utf-8')
    (tmp_path / 'meta.txt').write_text('duration=100\nframes_every=20\n', encoding='utf-8')
    (tmp_path / 'transcript.srt').write_text(
        "1\n00:00:05,000 --> 00:00:09,000\nsobre observabilidad\n\n"
        "2\n00:00:45,000 --> 00:00:49,000\ny el sandbox\n", encoding='utf-8')
    from align_slides import main
    assert main([str(tmp_path)]) == 0
    md = (tmp_path / 'timeline.md').read_text(encoding='utf-8')
    assert 'Observability' in md and '00:45' in md
    assert (tmp_path / 'timeline.json').exists()
