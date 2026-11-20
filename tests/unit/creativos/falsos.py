"""APIMart y ElevenLabs falsos para los tests de /creativos: nunca tocan la red ni gastan nada."""

from __future__ import annotations

import io
import json
import struct
import wave

from trovefy.apimart.http import Credenciales

from .ejemplos import png

CLAVE = "sk-prueba-" + "x" * 24
CRED = Credenciales("https://api.apimart.ai", CLAVE)
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def wav(segundos: float = 1.0, hz: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(hz)
        w.writeframes(struct.pack("<h", 0) * int(segundos * hz))
    return buf.getvalue()


class _Resp:
    def __init__(self, cuerpo: bytes, codigo: int = 200):
        self.status, self._c = codigo, cuerpo

    def read(self, *_a):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


class APIMartFalso:
    def __init__(self, coste: float = 0.01, post_lanza: Exception | None = None, video_ok: bool = True):
        self.coste, self.post_lanza, self.video_ok = coste, post_lanza, video_ok
        self.rutas: list[str] = []
        self.cuerpos: list[dict] = []
        self.n = 0

    def __call__(self, req, timeout=None):
        ruta = req.full_url.removeprefix("https://api.apimart.ai")
        self.rutas.append(f"{req.get_method()} {ruta}")
        if ruta.startswith("/v1/uploads/"):
            return _Resp(json.dumps({"url": f"https://upload.apimart.ai/f/{self.n}.bin"}).encode())
        if req.get_method() == "POST" and ruta in ("/v1/images/generations", "/v1/videos/generations",
                                                   "/v1/music/generations", "/v1/audio/speech"):
            self.cuerpos.append(json.loads(req.data))
            if self.post_lanza:
                raise self.post_lanza
            if ruta == "/v1/audio/speech":
                return _Resp(wav())
            self.n += 1
            return _Resp(json.dumps({"code": 200, "data": [{"status": "submitted", "task_id": f"task_{self.n}"}]})
                         .encode())
        if ruta.startswith("/v1/music/tasks/"):
            tid = ruta.rsplit("/", 1)[1]
            return _Resp(json.dumps({"code": 200, "data": {"id": tid, "status": "completed", "cost": self.coste,
                                                           "result": {"music": [{"audio_url":
                                                                                 f"https://cdn.apimart.ai/{tid}.mp3"}]}}
                                     }).encode())
        if ruta.startswith("/v1/tasks/"):
            tid = ruta.rsplit("/", 1)[1]
            datos = {"id": tid, "status": "completed", "cost": self.coste}
            if self.video_ok:
                datos["result"] = {"videos": [{"url": [f"https://upload.apimart.ai/f/video/{tid}.mp4"]}],
                                   "images": [{"url": [f"https://upload.apimart.ai/f/image/{tid}.png"]}]}
            return _Resp(json.dumps({"code": 200, "data": datos}).encode())
        raise AssertionError(f"ruta inesperada {ruta}")


MP3 = b"ID3" + b"\x00" * 64


def publico(req, timeout=None):
    assert "Authorization" not in req.headers
    url = req.full_url
    if url.endswith(".mp4"):
        return _Resp(MP4)
    if url.endswith(".mp3"):
        return _Resp(MP3)
    return _Resp(png(64, 80))


def explota(*_a, **_k):
    raise AssertionError("no debía llamar a la red")
