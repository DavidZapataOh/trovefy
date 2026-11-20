"""Clips de vídeo de APIMart (plan 21, Tarea 7): tarea asíncrona + sondeo + descarga sin clave.

Forma leída en ``docs.apimart.ai`` (2026-11-20): ``POST /v1/videos/generations`` (p. ej. ``seedance-2.0``:
``model``, ``prompt``, ``duration`` 4–15, ``size`` ``9:16``, ``resolution``, ``generate_audio``, ``image_urls``,
``audio_urls`` para que una persona hable con un audio dado) → ``data[0].task_id``; se sondea
``GET /v1/tasks/{id}`` (``status``: pending, processing, completed, failed, cancelled; ``cost``). La documentación no
enseña el resultado de un vídeo terminado (solo «``result.videos``: array of generated video objects»): se acepta
``result.videos[0].url`` como texto o como lista (igual que las imágenes) y nada más; otra forma → fallida, sin
reenviar. El precio no está publicado: sale de ``config/creativos.yaml`` (``None`` = no medido).
"""

from __future__ import annotations

import http.client
import re
import urllib.error
import urllib.request
from decimal import Decimal
from urllib.parse import urlparse

from trovefy.apimart.cliente import (
    _ESTADOS_FIN_MAL,
    _TASK_ID,
    EstadoTarea,
    _coste,
    _limpio,
    host_publico,
)
from trovefy.apimart.http import (
    Credenciales,
    RespuestaInesperada,
    SinRed,
    abrir_sin_redireccion,
    pedir_json,
)

RUTA = "/v1/videos/generations"
MAX_VIDEO = 200 * 2**20
SEGUNDOS = (4, 15)
_RESOLUCIONES = ("480p", "720p", "1080p")


def cuerpo_video(modelo: str, prompt: str, segundos: int, *, resolucion: str = "720p",
                 imagenes: list[str] | None = None, audios: list[str] | None = None) -> dict:
    """Cuerpo de ``POST /v1/videos/generations`` en 9:16 y sin audio propio (la voz y la música van aparte)."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError("el prompt del clip debe tener de 1 a 4000 caracteres")
    if isinstance(segundos, bool) or not isinstance(segundos, int) or not SEGUNDOS[0] <= segundos <= SEGUNDOS[1]:
        raise ValueError(f"un clip dura de {SEGUNDOS[0]} a {SEGUNDOS[1]} s")
    if resolucion not in _RESOLUCIONES:
        raise ValueError(f"resolución de vídeo «{resolucion}» no es {', '.join(_RESOLUCIONES)}")
    cuerpo = {"model": modelo, "prompt": prompt, "duration": segundos, "size": "9:16", "resolution": resolucion,
              "generate_audio": False}
    if imagenes:
        cuerpo["image_urls"] = list(imagenes)
    if audios:
        if not imagenes:
            raise ValueError("un audio de referencia va siempre con una imagen (la persona que habla)")
        cuerpo["audio_urls"] = list(audios)
    return cuerpo


def task_id_de(datos: dict) -> str:
    d = datos.get("data")
    primero = d[0] if isinstance(d, list) and d else d
    task_id = primero.get("task_id") if isinstance(primero, dict) else None
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise RespuestaInesperada("APIMart no devolvió un task_id")
    return task_id


def enviar_video(cred: Credenciales, cuerpo: dict, abrir=abrir_sin_redireccion) -> str:
    return task_id_de(pedir_json(cred, "POST", RUTA, cuerpo, abrir=abrir))


def _url_publica(url: object) -> str | None:
    if isinstance(url, list):
        url = url[0] if url else None
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    try:
        return url if host_publico(urlparse(url).hostname) else None
    except ValueError:
        return None


def leer_tarea_video(task_id: str, datos: dict) -> EstadoTarea:
    d = datos.get("data")
    if not isinstance(d, dict):
        return EstadoTarea(task_id, "pendiente", None, None, "respuesta sin datos de la tarea")
    estado, coste = d.get("status"), _coste(d)
    if estado == "completed":
        try:
            url = _url_publica(d["result"]["videos"][0]["url"])
        except (KeyError, IndexError, TypeError):
            url = None
        if url is None:
            return EstadoTarea(task_id, "fallida", None, coste, "APIMart terminó sin una URL de vídeo reconocible")
        return EstadoTarea(task_id, "completada", url, coste, None)
    if estado in _ESTADOS_FIN_MAL:
        err = d.get("error") if isinstance(d.get("error"), dict) else {}
        return EstadoTarea(task_id, "fallida", None, coste, _limpio(err.get("message") or f"tarea {estado}"))
    return EstadoTarea(task_id, "pendiente", None, None, None)


_MAGIA = re.compile(rb"^....ftyp", re.DOTALL)


def descargar_binario(url: str, abrir_publico=abrir_sin_redireccion, max_bytes: int = MAX_VIDEO,
                      tipo: str = "video") -> bytes:
    """Descarga sin clave ni redirecciones; comprueba que es un MP4 (``tipo="video"``) o un audio."""
    from trovefy.apimart.voz import es_audio

    try:
        u = urlparse(url)
    except (ValueError, AttributeError):
        raise RespuestaInesperada("URL de resultado ilegible") from None
    if u.scheme != "https" or not host_publico(u.hostname):
        raise RespuestaInesperada("la URL del resultado no es https pública")
    req = urllib.request.Request(url, headers={"User-Agent": "trovefy"}, method="GET")
    try:
        with abrir_publico(req, timeout=300) as resp:
            codigo, datos = resp.status, resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise RespuestaInesperada(f"la descarga respondió HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise SinRed("sin red al descargar el resultado") from None
    if codigo != 200 or len(datos) > max_bytes:
        raise RespuestaInesperada("descarga fallida o demasiado grande")
    if tipo == "video" and not _MAGIA.match(datos[:12]):
        raise RespuestaInesperada("lo descargado no es un MP4")
    if tipo == "audio" and es_audio(datos) is None:
        raise RespuestaInesperada("lo descargado no es audio")
    return datos


def estimado_clip(segundos: int, usd_segundo: Decimal) -> Decimal:
    return (usd_segundo * segundos).quantize(Decimal("0.0001"))
