"""Voz de ElevenLabs (plan 21, Tarea 6; S1 8:30). Sin red ni claves reales."""

import os
import urllib.error

import pytest
from trovefy.voz import elevenlabs


class _R:
    def __init__(self, cuerpo, codigo=200):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def test_credenciales_del_almacen(tmp_path):
    ruta = tmp_path / "elevenlabs.env"
    with pytest.raises(elevenlabs.SinClaveElevenLabs):
        elevenlabs.leer_credenciales(ruta)
    ruta.write_text("ELEVENLABS_API_KEY=" + "k" * 32 + "\n", encoding="utf-8")
    os.chmod(ruta, 0o600)
    cred = elevenlabs.leer_credenciales(ruta)
    assert "k" * 32 not in repr(cred)


def test_genera_mp3_con_su_cabecera():
    vistos = []

    def abrir(req, timeout=None):
        vistos.append(req)
        return _R(b"ID3" + b"\x00" * 16)

    cred = elevenlabs.CredElevenLabs("k" * 32)
    audio = elevenlabs.generar(cred, "abcdefgh12345678", elevenlabs.cuerpo("Здравей", "eleven_multilingual_v2"), abrir)
    assert audio.startswith(b"ID3")
    req = vistos[0]
    assert "/v1/text-to-speech/abcdefgh12345678" in req.full_url and req.headers["Xi-api-key"] == "k" * 32


def test_error_sin_clave_en_el_mensaje():
    def abrir(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "x", {}, None)

    cred = elevenlabs.CredElevenLabs("k" * 32)
    with pytest.raises(elevenlabs.ErrorElevenLabs) as e:
        elevenlabs.generar(cred, "abcdefgh12345678", elevenlabs.cuerpo("a", "m"), abrir)
    assert "k" * 32 not in str(e.value)
