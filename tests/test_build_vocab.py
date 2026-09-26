"""Tests del vocabulario derivado del OCR."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from build_vocab import build  # noqa: E402

OCR = """===== f_001.jpg =====
Welcome to the talk about Claude Managed Agents.
We use the Agent SDK and MCP servers for tool calling.
BigQuery export runs on Google Cloud.
"""


def test_encuentra_jerga_y_nombres_propios():
    terms, _ = build(OCR)
    for esperado in ('Claude', 'Managed', 'Agents', 'Agent', 'SDK', 'MCP', 'BigQuery'):
        assert esperado in terms, f"falta {esperado} en {terms}"


def test_descarta_ruido_y_stopwords():
    terms, _ = build(OCR)
    for ruido in ('jpg', 'The', 'the', 'and', 'We', 'Welcome'):
        assert ruido not in terms, f"no debería estar {ruido}"


def test_extra_va_primero():
    terms, _ = build(OCR, extra=['NanoBanana', 'harness'])
    assert terms[0] == 'NanoBanana' and terms[1] == 'harness'
    assert 'Claude' in terms


def test_extra_no_se_duplica():
    terms, _ = build(OCR, extra=['Claude'])
    assert terms.count('Claude') == 1


def test_respeta_max_chars():
    terms, _ = build(OCR, max_chars=20)
    assert len(', '.join(terms)) <= 20


def test_prompt_es_la_lista_unida():
    terms, _ = build(OCR, extra=['X'])
    assert ', '.join(terms).startswith('X, ')
