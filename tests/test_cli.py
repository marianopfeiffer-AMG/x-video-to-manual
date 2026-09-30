"""Tests del orquestador sin red ni Whisper: las protecciones que corren ANTES de trabajar.

Se usan stubs de yt-dlp/ffmpeg/ffprobe/whisper en el PATH: el script tiene que rechazar la
entrada o esperar el lock sin llegar a descargar ni transcribir nada.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'x-video-to-manual.sh'


@pytest.fixture
def env(tmp_path):
    stubs = tmp_path / 'bin'
    stubs.mkdir()
    for tool in ('yt-dlp', 'ffmpeg', 'ffprobe', 'whisper'):
        p = stubs / tool
        # ffprobe no reporta ningún stream: ningún archivo pasa por video.
        p.write_text('#!/bin/sh\necho "stub $0 $*" >> "$XVM_STUB_LOG"\nexit 0\n')
        p.chmod(0o755)
    e = dict(os.environ)
    e['PATH'] = f"{stubs}:{e['PATH']}"
    e['XVM_STUB_LOG'] = str(tmp_path / 'stub.log')
    e['XVM_LOCK'] = str(tmp_path / 'xvm.lock')
    return e


def run(env, *args, cwd=None):
    return subprocess.run(['bash', str(SCRIPT), *args], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def called(env):
    p = pathlib.Path(env['XVM_STUB_LOG'])
    return p.read_text() if p.exists() else ''


def test_help():
    r = subprocess.run(['bash', str(SCRIPT), '--help'], capture_output=True, text=True)
    assert r.returncode == 0 and '--max-minutes' in r.stdout


def test_rechaza_dominios_fuera_de_la_lista(env, tmp_path):
    r = run(env, 'https://evil.example.com/video.mp4', '--out', str(tmp_path / 'k'))
    assert r.returncode == 2 and 'dominio no permitido' in r.stderr
    assert 'yt-dlp' not in called(env)


def test_rechaza_modelos_pesados(env, tmp_path):
    r = run(env, 'https://x.com/a/status/1', '--model', 'large', '--out', str(tmp_path / 'k'))
    assert r.returncode == 2 and 'RAM' in r.stderr
    r = run(env, 'https://x.com/a/status/1', '--model', 'gigante', '--out', str(tmp_path / 'k'))
    assert r.returncode == 2


def test_rechaza_archivos_locales_que_no_son_video(env, tmp_path):
    secreto = tmp_path / 'hostname'
    secreto.write_text('mi-servidor\n')
    r = run(env, str(secreto), '--out', str(tmp_path / 'k'))
    assert r.returncode == 2 and 'no es un archivo de video' in r.stderr
    assert not (tmp_path / 'k' / 'video.mp4').exists()


def test_rechaza_rutas_fuera_de_las_raices_permitidas(env, tmp_path):
    video = tmp_path / 'fuera' / 'v.mp4'
    video.parent.mkdir()
    video.write_bytes(b'\x00' * 10)
    (tmp_path / 'permitido').mkdir()
    env['XVM_INPUT_ROOTS'] = str(tmp_path / 'permitido')
    r = run(env, str(video), '--out', str(tmp_path / 'k'))
    assert r.returncode == 2 and 'XVM_INPUT_ROOTS' in r.stderr


def test_valida_enteros(env, tmp_path):
    r = run(env, 'https://x.com/a/status/1', '--max-minutes', 'mucho')
    assert r.returncode == 2


def test_espera_el_lock_y_no_arranca_si_hay_otra_corrida(env, tmp_path):
    lock = pathlib.Path(env['XVM_LOCK'])
    if shutil.which('flock'):
        import fcntl
        fh = open(lock, 'w')
        fcntl.flock(fh, fcntl.LOCK_EX)
    else:
        d = pathlib.Path(str(lock) + '.d')
        d.mkdir()
        (d / 'pid').write_text(str(os.getpid()))     # este proceso está vivo: el lock es válido
    r = run(env, 'https://x.com/a/status/1', '--lock-wait', '0', '--out', str(tmp_path / 'k'))
    assert r.returncode == 75 and 'otra corrida' in r.stderr
    assert 'yt-dlp' not in called(env)


def test_lock_huerfano_se_limpia(env, tmp_path):
    if shutil.which('flock'):
        pytest.skip('con flock el kernel libera el lock solo')
    d = pathlib.Path(env['XVM_LOCK'] + '.d')
    d.mkdir()
    (d / 'pid').write_text('999999')                 # PID que no existe
    r = run(env, 'https://x.com/a/status/1', '--lock-wait', '0', '--out', str(tmp_path / 'k'))
    assert r.returncode != 75                        # siguió de largo (falla después, sin video)
