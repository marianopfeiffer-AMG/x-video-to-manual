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


def test_descarta_concatenaciones_largas_del_ocr():
    """El OCR a baja resolución pega palabras. Eso no puede ir al prompt de Whisper."""
    ocr = ("===== f_001.jpg =====\n"
           "Intelligencealonedoesn really work.\n"
           "Intelligencealonedoesn again.\n"
           "Jong-runningagentsin production today.\n"
           "Jong-runningagentsin again.\n")
    terms, _ = build(ocr, min_count=2)
    assert 'Intelligencealonedoesn' not in terms
    assert 'Jong-runningagentsin' not in terms


def test_conserva_marcas_largas_con_senal_interna():
    """Una marca larga con mayúscula interna o dígitos sí sirve como vocabulario."""
    ocr = ("===== f_001.jpg =====\n"
           "BigQueryAnalytics and BigQueryAnalytics again.\n"
           "GPT4Tokenizer GPT4Tokenizer GPT4Tokenizer\n")
    terms, _ = build(ocr)
    assert 'BigQueryAnalytics' in terms
    assert 'GPT4Tokenizer' in terms


def test_no_rompe_palabras_normales_largas():
    terms, _ = build("===== f_001.jpg =====\nwe value Observability and Observability matters\n")
    assert 'Observability' in terms
