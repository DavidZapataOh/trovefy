import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.referencia import watch
from trovefy.referencia.watch import (
    Entorno,
    comando_watch,
    comprobar_entorno,
    ejecutar_watch,
    entorno_hijo,
    leer_informe,
    pasos_instalacion,
)

FIX = Path(__file__).resolve().parents[2] / "fixtures/referencia"


def _fix(nombre, trabajo=None):
    t = (FIX / nombre).read_text()
    return t.replace("{trabajo}", str(trabajo)) if trabajo else t


def _ent(whisperx=True, ffmpeg="/usr/bin/ffmpeg", vendor_ok=True):
    return Entorno(ffmpeg, "/usr/bin/ffprobe", vendor_ok, whisperx, "")


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def test_watch_siempre_local_sin_claves(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    cmd = comando_watch(tmp_path / "v.mp4", tmp_path, True)
    i = cmd.index("--engine")
    assert cmd[i + 1] == "local"
    assert not any(x in " ".join(cmd) for x in ("gemini", "groq", "openai"))
    env = entorno_hijo("es", True)
    assert not any(k.endswith("_API_KEY") for k in env)
    assert env["WATCH_ENGINE"] == "local" and env["WATCH_WHISPERX_LANGUAGE"] == "es"
    assert env["WATCH_WHISPER_BACKEND"] == "whisperx" and env["LANG"] == "C.UTF-8"
    assert entorno_hijo(None, False)["WATCH_WHISPER_BACKEND"] == "none"


def test_watch_sin_whisperx_no_medido(tmp_path):
    llamadas = []

    def falso(cmd, **kw):
        llamadas.append(cmd)
        return _proc(0, _fix("watch_sin_transcripcion.md", tmp_path))

    r = ejecutar_watch(tmp_path / "v.mp4", tmp_path, None, _ent(whisperx=False), falso)
    assert "--no-whisper" in llamadas[0]
    assert r.transcripcion is None
    assert r.motivo.startswith("no medido: whisper local no instalado")
    assert (tmp_path / "watch.md").exists()


def test_leer_informe(tmp_path):
    r = leer_informe(_fix("watch_salida.md", tmp_path), tmp_path)
    assert r.duracion_s == Decimal("32.4")
    assert len(r.fotogramas) == 3
    assert "anuncio inventado" in r.transcripcion
    assert r.fuente_transcripcion == "whisperx" and r.motivo is None


def test_watch_rechaza_fotograma_fuera(tmp_path):
    txt = _fix("watch_salida.md", tmp_path).replace(
        f"{tmp_path}/frames/f_0002.jpg", "/etc/passwd"
    )
    with pytest.raises(ValueError):
        leer_informe(txt, tmp_path)


def test_watch_codigo_1_no_medido(tmp_path):
    r = ejecutar_watch(
        tmp_path / "v.mp4", tmp_path, None, _ent(), lambda c, **k: _proc(1, "", "x")
    )
    assert r.motivo == "no medido: /watch no dio evidencia" and not r.fotogramas


def test_comprobar_entorno_sin_whisperx():
    salida = (FIX / "setup_json_sin_whisperx.json").read_text()
    e = comprobar_entorno(
        which=lambda n: f"/usr/bin/{n}", ejecutar=lambda c, **k: _proc(0, salida)
    )
    assert e.whisperx is False and e.ffmpeg and e.vendor_ok
    pasos = pasos_instalacion(e)
    assert any("--install-whisperx" in p for p in pasos)
    assert not any(p.lstrip("` ").startswith("sudo") for p in pasos)


def test_comprobar_entorno_listo():
    salida = (FIX / "setup_json_listo.json").read_text()
    e = comprobar_entorno(
        which=lambda n: f"/usr/bin/{n}", ejecutar=lambda c, **k: _proc(0, salida)
    )
    assert e.whisperx is True and pasos_instalacion(e) == []


def test_entorno_json_ilegible_y_sin_ffmpeg():
    e = comprobar_entorno(
        which=lambda n: None, ejecutar=lambda c, **k: _proc(0, "no json")
    )
    assert e.whisperx is False and e.ffmpeg is None and e.whisperx_detalle
    assert any("sudo apt install ffmpeg" in p for p in pasos_instalacion(e))
    assert watch.RAIZ_VENDOR.name == "scripts"


def test_sin_ffmpeg_no_ejecuta(tmp_path):
    def falso(*a, **k):
        raise AssertionError("no debe ejecutarse")

    r = ejecutar_watch(tmp_path / "v.mp4", tmp_path, None, _ent(ffmpeg=None), falso)
    assert r.motivo.startswith("no medido:") and not r.fotogramas
    r = ejecutar_watch(tmp_path / "v.mp4", tmp_path, None, _ent(vendor_ok=False), falso)
    assert r.motivo.startswith("no medido:")
