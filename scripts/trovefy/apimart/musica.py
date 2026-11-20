"""Música de APIMart (Suno) para la tanda (plan 21, Tarea 7; L2 15:25).

Forma leída en ``docs.apimart.ai/en/api-reference/audios/suno/generation`` (2026-11-20):
``POST /v1/music/generations`` (``model: suno``, ``version``, ``custom: false``, ``instrumental``, ``prompt`` ≤ 3000)
→ ``data[0].task_id``; se sondea ``GET /v1/music/tasks/{id}`` y el audio está en
``data.result.music[0].audio_url``. La documentación no da precio ni dice nada del uso comercial: sin precio en
``config/creativos.yaml`` no se envía nada y sin licencia comercial comprobada tampoco (la música la aporta el
usuario con su licencia).
"""

from __future__ import annotations

from urllib.parse import urlparse

from trovefy.apimart.cliente import (
    _ESTADOS_FIN_MAL,
    EstadoTarea,
    _coste,
    _limpio,
    host_publico,
)
from trovefy.apimart.http import Credenciales, abrir_sin_redireccion, pedir_json
from trovefy.apimart.video import task_id_de

RUTA = "/v1/music/generations"
RUTA_TAREA = "/v1/music/tasks/{}"


def cuerpo_musica(modelo: str, version: str | None, prompt: str) -> dict:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 3000:
        raise ValueError("la descripción de la música debe tener de 1 a 3000 caracteres")
    cuerpo = {"model": modelo, "custom": False, "instrumental": True, "prompt": prompt, "audio_format": "mp3"}
    if version:
        cuerpo["version"] = version
    return cuerpo


def enviar_musica(cred: Credenciales, cuerpo: dict, abrir=abrir_sin_redireccion) -> str:
    return task_id_de(pedir_json(cred, "POST", RUTA, cuerpo, abrir=abrir))


def leer_tarea_musica(task_id: str, datos: dict) -> EstadoTarea:
    d = datos.get("data")
    if not isinstance(d, dict):
        return EstadoTarea(task_id, "pendiente", None, None, "respuesta sin datos de la tarea")
    estado, coste = d.get("status"), _coste(d)
    if estado == "completed":
        try:
            url = d["result"]["music"][0]["audio_url"]
        except (KeyError, IndexError, TypeError):
            url = None
        ok = isinstance(url, str) and url.startswith("https://") and host_publico(urlparse(url).hostname)
        if not ok:
            return EstadoTarea(task_id, "fallida", None, coste, "APIMart terminó sin audio_url")
        return EstadoTarea(task_id, "completada", url, coste, None)
    if estado in (*_ESTADOS_FIN_MAL, "unknown"):
        err = d.get("error") if isinstance(d.get("error"), dict) else {}
        return EstadoTarea(task_id, "fallida", None, coste, _limpio(err.get("message") or f"tarea {estado}"))
    return EstadoTarea(task_id, "pendiente", None, None, None)
