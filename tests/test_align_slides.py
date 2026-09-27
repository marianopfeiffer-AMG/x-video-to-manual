"""Tests de la línea de tiempo (relato ↔ slides)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from align_slides import (attach, avg_abs_diff, frame_index, group_by_visual,  # noqa: E402
                          group_slides, hhmmss, parse_ocr, parse_transcript, to_sec,
                          visual_signatures)

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


# --- agrupado por imagen ---------------------------------------------------

def test_frame_index():
    assert frame_index('f_012.jpg') == 12
    assert frame_index('sin-numero') is None


def test_avg_abs_diff():
    negro, blanco = bytes([0] * 256), bytes([255] * 256)
    assert avg_abs_diff(negro, negro) == 0.0
    assert avg_abs_diff(negro, blanco) == 1.0
    assert avg_abs_diff(negro, b'') == 1.0        # firmas incomparables: se tratan como distintas


def test_agrupa_por_imagen():
    frames = [(f'f_{i:03d}.jpg', f'texto {i}') for i in (1, 2, 3, 4, 5)]
    a, b, c = bytes([10] * 256), bytes([200] * 256), bytes([60] * 256)
    slides = group_by_visual(frames, {1: a, 2: a, 3: b, 4: b, 5: c}, every=20)
    assert len(slides) == 3
    assert slides[0]['frames'] == ['f_001.jpg', 'f_002.jpg']
    assert slides[1]['frames'] == ['f_003.jpg', 'f_004.jpg']
    assert slides[2]['frames'] == ['f_005.jpg']
    assert slides[0]['end'] == 40


def test_agrupado_visual_tolera_movimiento():
    """Una variación chica (el orador moviéndose) no puede partir la slide en dos."""
    frames = [(f'f_{i:03d}.jpg', 'x') for i in (1, 2, 3)]
    slides = group_by_visual(frames, {1: bytes([100] * 256), 2: bytes([101] * 256),
                                      3: bytes([100] * 256)}, every=10)
    assert len(slides) == 1


def test_group_by_visual_sin_firma_abre_grupo():
    slides = group_by_visual([('f_001.jpg', 'a'), ('f_002.jpg', 'b')],
                             {1: bytes([1] * 256)}, every=10)
    assert len(slides) == 2


def test_visual_signatures_sin_frames(tmp_path):
    assert visual_signatures(tmp_path / 'frames') == (None, None)


def test_visual_signatures_con_huecos_en_la_numeracion(tmp_path):
    d = tmp_path / 'frames'
    d.mkdir()
    for i in (1, 3):                              # falta el 2: desalinearía todo
        (d / f'f_{i:03d}.jpg').write_bytes(b'x')
    assert visual_signatures(d) == (None, None)


def test_visual_signatures_con_ffmpeg(tmp_path):
    import shutil
    import subprocess as sp
    if not shutil.which('ffmpeg'):
        import pytest
        pytest.skip('ffmpeg no está disponible')
    d = tmp_path / 'frames'
    d.mkdir()
    for i in (1, 2, 3):
        sp.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=160x90',
                '-frames:v', '1', str(d / f'f_{i:03d}.jpg')], check=True)
    sigs, nums = visual_signatures(d)
    assert nums == [1, 2, 3]
    assert len(sigs) == 3 and len(sigs[1]) == 256
    assert avg_abs_diff(sigs[1], sigs[2]) < 0.05    # mismo gris => misma firma


def test_end_to_end_visual(tmp_path):
    """Con frames presentes debe agrupar por imagen y decirlo en el markdown."""
    import shutil
    import subprocess as sp
    if not shutil.which('ffmpeg'):
        import pytest
        pytest.skip('ffmpeg no está disponible')
    d = tmp_path / 'frames'
    d.mkdir()
    colores = ['black', 'black', 'white', 'white']
    for i, c in enumerate(colores, 1):
        sp.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={c}:s=160x90',
                '-frames:v', '1', str(d / f'f_{i:03d}.jpg')], check=True)
    (tmp_path / 'slides-ocr.txt').write_text(
        "===== f_001.jpg =====\nSlide uno\n\n===== f_002.jpg =====\nSlide uno\n\n"
        "===== f_003.jpg =====\nSlide dos\n\n===== f_004.jpg =====\nSlide dos\n",
        encoding='utf-8')
    (tmp_path / 'meta.txt').write_text('frames_every=20\n', encoding='utf-8')
    (tmp_path / 'transcript.srt').write_text(
        "1\n00:10:00,000 --> 00:10:04,000\nprimero\n\n"
        "2\n00:10:50,000 --> 00:11:00,000\nsegundo\n", encoding='utf-8')
    from align_slides import main
    assert main([str(tmp_path)]) == 0
    md = (tmp_path / 'timeline.md').read_text(encoding='utf-8')
    assert 'por imagen' in md
    import json
    assert json.loads((tmp_path / 'timeline.json').read_text())['group_by'] == 'imagen'
