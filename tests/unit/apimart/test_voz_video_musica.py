"""Clientes de APIMart para la voz, los clips y la música (plan 21, Tareas 6 y 7). Sin red."""

import io
import json
import struct
import urllib.error
import wave

import pytest
from trovefy.apimart.http import Credenciales, RespuestaInesperada, SinSaldo
from trovefy.apimart.musica import cuerpo_musica, leer_tarea_musica
from trovefy.apimart.video import cuerpo_video, leer_tarea_video
from trovefy.apimart.voz import cuerpo_tts, es_audio, pedir_audio

from .ayudas import CLAVE

CRED = Credenciales("https://api.apimart.ai", CLAVE)


def _wav():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * 800)
    return buf.getvalue()


class _R:
    def __init__(self, cuerpo, codigo=200):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def test_tts_forma_de_la_documentacion():
    c = cuerpo_tts("gpt-4o-mini-tts", "Здравей", "nova")
    assert c == {"model": "gpt-4o-mini-tts", "input": "Здравей", "voice": "nova", "response_format": "wav"}
    with pytest.raises(ValueError):
        cuerpo_tts("gpt-4o-mini-tts", "x" * 4097, "nova")
    with pytest.raises(ValueError):
        cuerpo_tts("gpt-4o-mini-tts", "x", "otra")


def test_tts_devuelve_audio_y_lleva_la_clave():
    vistos = []

    def abrir(req, timeout=None):
        vistos.append(req)
        return _R(_wav())

    datos = pedir_audio(CRED, cuerpo_tts("gpt-4o-mini-tts", "Здравей", "nova"), abrir)
    assert es_audio(datos) == "wav"
    assert vistos[0].full_url.endswith("/v1/audio/speech") and vistos[0].headers["Authorization"].startswith("Bearer")


def test_tts_sin_saldo_y_respuesta_rara():
    def sin_saldo(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 402, "x", {}, io.BytesIO(b'{"error": {"type": "x"}}'))

    with pytest.raises(SinSaldo):
        pedir_audio(CRED, cuerpo_tts("gpt-4o-mini-tts", "a", "nova"), sin_saldo)
    with pytest.raises(RespuestaInesperada):
        pedir_audio(CRED, cuerpo_tts("gpt-4o-mini-tts", "a", "nova"), lambda r, timeout=None: _R(b"<html>"))


def test_cuerpo_video_vertical_sin_audio_propio():
    c = cuerpo_video("seedance-2.0", "reloj", 4, imagenes=["https://u/a.png"], audios=["https://u/v.wav"])
    assert c["size"] == "9:16" and c["generate_audio"] is False and c["audio_urls"] == ["https://u/v.wav"]
    with pytest.raises(ValueError):
        cuerpo_video("seedance-2.0", "reloj", 20)
    with pytest.raises(ValueError):
        cuerpo_video("seedance-2.0", "reloj", 5, audios=["https://u/v.wav"])  # audio sin imagen


def test_tarea_video_url_texto_o_lista():
    for url in ("https://upload.apimart.ai/f/v.mp4", ["https://upload.apimart.ai/f/v.mp4"]):
        e = leer_tarea_video("t", {"data": {"status": "completed", "cost": 0.3, "result": {"videos": [{"url": url}]}}})
        assert e.estado == "completada" and e.url.endswith("v.mp4")
    e = leer_tarea_video("t", {"data": {"status": "completed", "result": {"videos": [{"otra": 1}]}}})
    assert e.estado == "fallida"
    assert leer_tarea_video("t", {"data": {"status": "processing"}}).estado == "pendiente"
    e = leer_tarea_video("t", {"data": {"status": "completed", "result": {"videos": [{"url": "https://127.0.0.1/x"}]}}})
    assert e.estado == "fallida"


def test_musica_instrumental_y_su_tarea():
    c = cuerpo_musica("suno", "v6", "piano suave y calmado")
    assert c["instrumental"] is True and c["custom"] is False and c["version"] == "v6"
    ok = {"data": {"status": "completed", "result": {"music": [{"audio_url": "https://cdn.apimart.ai/a.mp3"}]}}}
    assert leer_tarea_musica("t", ok).estado == "completada"
    assert leer_tarea_musica("t", {"data": {"status": "failed", "error": {"message": "x"}}}).estado == "fallida"
    assert json.dumps(c)
