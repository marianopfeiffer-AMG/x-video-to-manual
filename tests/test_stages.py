"""Tests de la caché de etapas (scripts/stages.py).

Lo que importa de verdad: que un cambio de parámetro o de entrada **invalide** la etapa,
y que una salida borrada no se tome por buena. Si eso funciona, reanudar es seguro.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import stages  # noqa: E402


@pytest.fixture
def archivo(tmp_path):
    p = tmp_path / 'audio.wav'
    p.write_bytes(b'x' * 100)
    return p


def test_firma_estable(archivo):
    a = stages.signature({'model': 'small'}, [archivo])
    b = stages.signature({'model': 'small'}, [archivo])
    assert a == b


def test_firma_cambia_con_el_parametro(archivo):
    assert stages.signature({'model': 'small'}, [archivo]) != \
           stages.signature({'model': 'base'}, [archivo])


def test_firma_cambia_si_cambia_el_archivo(archivo):
    antes = stages.signature({'model': 'small'}, [archivo])
    archivo.write_bytes(b'y' * 100)          # mismo tamaño, distinto contenido
    assert stages.signature({'model': 'small'}, [archivo]) != antes


def test_firma_distinta_si_cambia_el_tamano(archivo):
    antes = stages.signature({}, [archivo])
    archivo.write_bytes(b'z' * 101)
    assert stages.signature({}, [archivo]) != antes


def test_archivo_inexistente_no_explota(tmp_path):
    assert stages.file_sig(tmp_path / 'no-existe.wav') is None
    assert stages.signature({'a': '1'}, [tmp_path / 'no-existe.wav'])


def test_firma_de_directorio_cambia_al_agregar_un_archivo(tmp_path):
    d = tmp_path / 'frames'
    d.mkdir()
    (d / 'f_001.jpg').write_bytes(b'aaa')
    antes = stages.file_sig(d)
    (d / 'f_002.jpg').write_bytes(b'bbb')
    assert stages.file_sig(d) != antes


def test_directorio_vacio_tiene_firma(tmp_path):
    d = tmp_path / 'frames'
    d.mkdir()
    assert stages.file_sig(d)


def test_ok_tras_marcar(tmp_path, archivo):
    state = tmp_path / '.stages.json'
    salida = tmp_path / 'transcript.srt'
    salida.write_text('1\n')
    sig = stages.signature({'model': 'small'}, [archivo])

    assert stages.is_ok(state, 'asr', sig) is False       # todavía no está marcada
    stages.mark(state, 'asr', sig, [salida])
    assert stages.is_ok(state, 'asr', sig) is True


def test_ok_falla_si_la_firma_cambio(tmp_path, archivo):
    state = tmp_path / '.stages.json'
    salida = tmp_path / 'transcript.srt'
    salida.write_text('1\n')
    stages.mark(state, 'asr', stages.signature({'model': 'small'}, [archivo]), [salida])
    assert stages.is_ok(state, 'asr', stages.signature({'model': 'base'}, [archivo])) is False


def test_ok_falla_si_borraron_la_salida(tmp_path, archivo):
    """Auto-sanación: si alguien borra transcript.srt, la etapa se rehace."""
    state = tmp_path / '.stages.json'
    salida = tmp_path / 'transcript.srt'
    salida.write_text('1\n')
    sig = stages.signature({'model': 'small'}, [archivo])
    stages.mark(state, 'asr', sig, [salida])
    assert stages.is_ok(state, 'asr', sig) is True

    salida.unlink()
    assert stages.is_ok(state, 'asr', sig) is False


def test_estado_corrupto_es_estado_vacio(tmp_path):
    state = tmp_path / '.stages.json'
    state.write_text('{ esto no es json')
    assert stages.load(state) == {}
    assert stages.is_ok(state, 'asr', 'deadbeef') is False


def test_mark_no_pisa_otras_etapas(tmp_path):
    state = tmp_path / '.stages.json'
    stages.mark(state, 'audio', 'aaaa', [])
    stages.mark(state, 'asr', 'bbbb', [])
    data = stages.load(state)
    assert set(data) == {'audio', 'asr'}
    assert data['audio']['sig'] == 'aaaa'


def test_guardar_y_leer_preserva_las_salidas(tmp_path):
    state = tmp_path / '.stages.json'
    stages.mark(state, 'ocr', 'cccc', ['slides-ocr.txt'])
    assert json.loads(state.read_text())['ocr']['outputs'] == ['slides-ocr.txt']


def test_cli_sig_ok_mark(tmp_path, archivo, capsys):
    state = tmp_path / '.stages.json'
    salida = tmp_path / 'audio.wav'

    assert stages.main(['sig', '--param', 'k=v', '--file', str(archivo)]) == 0
    sig = capsys.readouterr().out.strip()
    assert len(sig) == stages.SIG_LEN

    assert stages.main(['ok', '--state', str(state), '--stage', 'x', '--sig', sig]) == 1
    assert stages.main(['mark', '--state', str(state), '--stage', 'x',
                        '--sig', sig, '--output', str(salida)]) == 0
    assert stages.main(['ok', '--state', str(state), '--stage', 'x', '--sig', sig]) == 0


def test_cli_clear(tmp_path):
    state = tmp_path / '.stages.json'
    stages.mark(state, 'audio', 'aaaa', [])
    assert stages.main(['clear', '--state', str(state)]) == 0
    assert not state.exists()
