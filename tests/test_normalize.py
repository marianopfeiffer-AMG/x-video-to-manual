"""Tests del normalizador y del diccionario TSV."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from normalize_transcript import apply_fixes, load_fixes  # noqa: E402

FIXES = ROOT / 'references' / 'fixes' / 'anthropic-agents.tsv'


def test_sin_diccionario_no_toca_nada():
    texto = 'We deploy on Google Cloud. The Asian market grew.'
    assert apply_fixes(texto, []) == texto


def test_diccionario_corrige_jerga():
    rules = load_fixes(FIXES)
    assert 'Claude Managed Agents' in apply_fixes('Cloud Managed Asians', rules)
    assert 'Agent SDK' in apply_fixes('the Asian SDK', rules)
    assert 'checkpointing' in apply_fixes('session checkwining', rules)


def test_no_rompe_texto_legitimo():
    rules = load_fixes(FIXES)
    texto = 'We deploy on Google Cloud and use BigQuery.'
    assert apply_fixes(texto, rules) == texto
    assert apply_fixes('The Asian market grew.', rules) == 'The Asian market grew.'


def test_reglas_ordenadas_y_sin_duplicados():
    rules = load_fixes(FIXES)
    claves = [(-r[3], -len(r[0])) for r in rules]
    assert claves == sorted(claves)
    assert len(rules) == len({(r[0], r[1]) for r in rules})


def test_la_regla_especifica_gana_a_la_generica():
    """"Cloud Managed Asians" debe resolverse con su regla propia, no con "Cloud"→"Claude"."""
    rules = load_fixes(FIXES)
    log = []
    apply_fixes('Cloud Managed Asians', rules, log=log)
    assert [c['rule'] for c in log] == ['Cloud Managed Asians']


def test_reporte_registra_correcciones():
    rules = load_fixes(FIXES)
    log = []
    apply_fixes('Cloud Managed Asians', rules, log=log)
    assert log and log[0]['original'] and 'source' in log[0]
