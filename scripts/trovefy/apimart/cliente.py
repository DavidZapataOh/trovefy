"""Cliente de imágenes de APIMart: envío → ``task_id`` → sondeo con *backoff* → descarga sin clave.

Patrón portado de LordVayron/video-factory ``engine/lib/apimart.mjs`` (MIT, commit 8afd1b2e):
mismo *backoff* (5 s × 1,2 hasta 15 s, límite 600 s) y misma regla de no reenviar una tarea enviada.

Formas reales en ``tests/fixtures/apimart/`` (documentación de ``gpt-image-2``, 2026-11-16): 15
proporciones, las 15 admiten 4k, como mucho 15 referencias; ``task_id`` en ``data[0].task_id``;
URL en ``data.result.images[0].url[0]``; coste en ``data.cost`` (USD) o ``data.credits_cost``.
Una tarea enviada puede estar cobrada: si el sondeo no termina queda ``pendiente``, nunca ``fallida``.
"""

from __future__ import annotations

import http.client
import io
import ipaddress
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from urllib.parse import quote, urlparse

from trovefy.apimart.http import (
    ClaveRechazada,
    Credenciales,
    ErrorApimart,
    ErrorServidor,
    Limitado,
    RespuestaInesperada,
    SinRed,
    abrir_sin_redireccion,
    pedir_json,
)
from trovefy.apimart.precios import CREDITO_USD
from trovefy.producto.rutas import PIEZA

# Fuente: https://docs.apimart.ai/en/api-reference/images/gpt-image-2/generation.md (2026-11-16).
PROPORCIONES = ("1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5", "16:9", "9:16", "2:1", "1:2", "3:1", "1:3",
                "21:9", "9:21")
PROPORCIONES_4K = PROPORCIONES  # «4K supports the 15 ratios listed above»
RESOLUCIONES = ("1k", "2k", "4k")
MAX_REFERENCIAS = 15  # «Up to 15 reference images»
MAX_PROMPT = 4000
ORIGENES_REFERENCIA = ("apimart", "propio")

# Backoff del sondeo (video-factory apimart.mjs): 5 s, ×1,2, tope 15 s, límite 600 s.
SONDEO_INICIAL_S, SONDEO_FACTOR, SONDEO_MAX_S, SONDEO_LIMITE_S = 5, Decimal("1.2"), 15, 600
FALLOS_SEGUIDOS_MAX = 3  # red o servidor caídos tres sondeos seguidos → pendiente
MOTIVO_AGOTADO = f"sin resultado en {SONDEO_LIMITE_S} s; se reanuda con --reanudar"
MAX_DESCARGA = 20 * 2**20
FORMATOS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}

_ID = re.compile(r"[a-z0-9-]{1,40}", re.ASCII)
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,128}", re.ASCII)
_ESTADOS_FIN_MAL = ("failed", "cancelled", "canceled")
_ETIQUETA = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", re.ASCII)
_SUFIJOS_PRIVADOS = (".localhost", ".local", ".localdomain", ".internal", ".lan", ".home.arpa", ".intranet")


class PeticionInvalida(ValueError):
    pass


@dataclass(frozen=True)
class PeticionImagen:
    id: str
    pieza: str
    prompt: str
    proporcion: str
    resolucion: str
    referencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class EstadoTarea:
    task_id: str
    estado: Literal["completada", "fallida", "pendiente"]
    url: str | None
    coste_real_usd: Decimal | None
    motivo: str | None


def validar(p: PeticionImagen, manifiesto: dict) -> None:
    """Proporción y resolución válidas, 4k solo en ``PROPORCIONES_4K``, prompt de 1 a 4000 caracteres,
    como mucho 15 referencias y todas en el manifiesto con origen ``apimart`` o ``propio``."""
    if not isinstance(p.id, str) or not _ID.fullmatch(p.id):
        raise PeticionInvalida(f"id de imagen mal escrito: «{p.id}» (minúsculas, cifras y guiones; hasta 40)")
    if not isinstance(p.pieza, str) or not PIEZA.fullmatch(p.pieza):
        raise PeticionInvalida(f"{p.id}: pieza «{p.pieza}» no es principal, bono-N, bump, u1, u2, u3 ni downsell")
    if p.resolucion not in RESOLUCIONES:
        raise PeticionInvalida(f"{p.id}: resolución «{p.resolucion}» no es {', '.join(RESOLUCIONES)}")
    if p.proporcion not in PROPORCIONES:
        raise PeticionInvalida(f"{p.id}: proporción «{p.proporcion}» no admitida ({' '.join(PROPORCIONES)})")
    if p.resolucion == "4k" and p.proporcion not in PROPORCIONES_4K:
        raise PeticionInvalida(f"{p.id}: 4k no se admite en {p.proporcion}")
    if not isinstance(p.prompt, str) or not p.prompt.strip() or len(p.prompt) > MAX_PROMPT:
        raise PeticionInvalida(f"{p.id}: el prompt debe tener de 1 a {MAX_PROMPT} caracteres")
    refs = p.referencias
    if not isinstance(refs, tuple) or len(refs) > MAX_REFERENCIAS:
        raise PeticionInvalida(f"{p.id}: como mucho {MAX_REFERENCIAS} referencias")
    for r in refs:
        entrada = manifiesto.get(r) if isinstance(r, str) else None
        if not isinstance(entrada, dict) or entrada.get("origen") not in ORIGENES_REFERENCIA:
            raise PeticionInvalida(f"{p.id}: la referencia «{r}» no es un medio propio del manifiesto")


def cuerpo_envio(p: PeticionImagen, modelo: str, urls_ref: list[str]) -> dict:
    cuerpo = {"model": modelo, "prompt": p.prompt, "n": 1, "size": p.proporcion, "resolution": p.resolucion}
    if urls_ref:
        cuerpo["image_urls"] = list(urls_ref)
    return cuerpo


def enviar(cred: Credenciales, cuerpo: dict, abrir=abrir_sin_redireccion) -> str:
    """``POST /v1/images/generations`` → ``task_id`` (``data[0].task_id``). Sin él: ``RespuestaInesperada``."""
    datos = pedir_json(cred, "POST", "/v1/images/generations", cuerpo, abrir=abrir)
    d = datos.get("data")
    primero = d[0] if isinstance(d, list) and d else d
    task_id = primero.get("task_id") if isinstance(primero, dict) else None
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise RespuestaInesperada("APIMart no devolvió un task_id")
    return task_id


def _num(v: object) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    d = Decimal(str(v))
    return d if d.is_finite() and d >= 0 else None


def _coste(d: dict) -> Decimal | None:
    usd = _num(d.get("cost"))
    if usd is not None:
        return usd
    creditos = _num(d.get("credits_cost"))
    return None if creditos is None else creditos * CREDITO_USD


def host_publico(host: str | None) -> bool:
    """¿``host`` es un nombre DNS público? No vale una IP (en ninguna grafía), ``localhost``, un nombre de
    una sola etiqueta ni los sufijos de red local. La documentación sirve los resultados desde
    ``upload.apimart.ai``, pero su CDN puede cambiar: se rechaza lo que nunca es público en vez de fijar
    una lista de hosts que, si cambiara, dejaría sin descargar imágenes ya pagadas."""
    if not isinstance(host, str) or not host:
        return False
    h = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(h)
        return False
    except ValueError:
        pass
    if h == "localhost" or h.endswith(_SUFIJOS_PRIVADOS):
        return False
    etiquetas = h.split(".")
    return (len(etiquetas) >= 2 and all(_ETIQUETA.fullmatch(e) for e in etiquetas)
            and bool(_TLD.fullmatch(etiquetas[-1])))


def _url_publica(url: object) -> bool:
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        return host_publico(urlparse(url).hostname)
    except ValueError:
        return False


def _url(d: dict) -> str | None:
    try:
        url = d["result"]["images"][0]["url"][0]
    except (KeyError, IndexError, TypeError):
        return None
    return url if _url_publica(url) else None


def _limpio(texto: object) -> str:
    return re.sub(r"\s+", " ", str(texto))[:200]


def leer_tarea(task_id: str, datos: dict) -> EstadoTarea:
    """Interpreta la respuesta de ``GET /v1/tasks/{id}``."""
    d = datos.get("data")
    if not isinstance(d, dict):
        return EstadoTarea(task_id, "pendiente", None, None, "respuesta sin datos de la tarea")
    estado = d.get("status")
    coste = _coste(d)
    if estado == "completed":
        url = _url(d)
        if url is None:
            return EstadoTarea(task_id, "fallida", None, coste, "APIMart terminó sin URL de imagen")
        return EstadoTarea(task_id, "completada", url, coste, None)
    if estado in _ESTADOS_FIN_MAL:
        err = d.get("error") if isinstance(d.get("error"), dict) else {}
        motivo = _limpio(err.get("message") or f"tarea {estado}")
        return EstadoTarea(task_id, "fallida", None, coste, motivo)
    return EstadoTarea(task_id, "pendiente", None, None, None)


def esperar(cred: Credenciales, task_id: str, abrir=abrir_sin_redireccion, dormir=time.sleep,
            reloj=time.monotonic) -> EstadoTarea:
    """Sondea ``GET /v1/tasks/{task_id}`` con *backoff* hasta ``completada``, ``fallida`` o el límite.

    Al pasar ``SONDEO_LIMITE_S`` devuelve ``pendiente``. La red o el servidor caídos
    ``FALLOS_SEGUIDOS_MAX`` veces seguidas, o cualquier otro error de APIMart, también dan
    ``pendiente`` (la tarea pudo cobrarse): nunca ``fallida`` y nunca se reenvía.
    """
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise ValueError(f"task_id mal escrito: {task_id!r}")
    inicio = reloj()
    espera = Decimal(SONDEO_INICIAL_S)
    fallos = 0
    while True:
        try:
            datos = pedir_json(cred, "GET", f"/v1/tasks/{quote(task_id, safe='')}", abrir=abrir)
        except (SinRed, ErrorServidor, Limitado):
            fallos += 1
            if fallos >= FALLOS_SEGUIDOS_MAX:
                return EstadoTarea(task_id, "pendiente", None, None,
                                   "sin red o APIMart caído al sondear; se reanuda con --reanudar")
        except ClaveRechazada:
            return EstadoTarea(task_id, "pendiente", None, None, "clave rechazada al sondear; se reanuda con --reanudar")
        except ErrorApimart as exc:
            return EstadoTarea(task_id, "pendiente", None, None, f"{_limpio(exc)}; se reanuda con --reanudar")
        else:
            fallos = 0
            estado = leer_tarea(task_id, datos)
            if estado.estado != "pendiente":
                return estado
        if reloj() - inicio >= SONDEO_LIMITE_S:
            return EstadoTarea(task_id, "pendiente", None, None, MOTIVO_AGOTADO)
        dormir(float(espera) if espera != espera.to_integral_value() else int(espera))
        espera = min(espera * SONDEO_FACTOR, Decimal(SONDEO_MAX_S))


def formato_imagen(datos: bytes) -> str | None:
    """``png``, ``jpg`` o ``webp`` si Pillow verifica la imagen; ``None`` si no es una imagen admitida."""
    from PIL import Image  # import tardío: Pillow solo hace falta al descargar

    try:
        with Image.open(io.BytesIO(datos)) as img:
            formato = img.format
            img.verify()
    except Exception:  # noqa: BLE001 - cualquier fallo de Pillow = no es una imagen válida
        return None
    return FORMATOS.get(formato or "")


def descargar(url: str, abrir_publico=abrir_sin_redireccion, max_bytes: int = MAX_DESCARGA) -> bytes:
    """Descarga el resultado: solo https, sin redirecciones y **sin** ``Authorization``.

    Comprueba con Pillow que es PNG, JPEG o WEBP; si no, ``RespuestaInesperada``. La URL no sale en
    los mensajes (puede llevar firma).
    """
    try:
        u = urlparse(url)
        host = u.hostname
    except (ValueError, AttributeError):
        raise RespuestaInesperada("URL de resultado ilegible") from None
    if u.scheme != "https" or not host:
        raise RespuestaInesperada("la URL del resultado no es https")
    if not host_publico(host):
        raise RespuestaInesperada("la URL del resultado no apunta a un nombre público (IP, localhost o red local)")
    req = urllib.request.Request(url, headers={"User-Agent": "trovefy", "Accept": "image/*"}, method="GET")
    try:
        with abrir_publico(req, timeout=60) as resp:
            codigo, datos = resp.status, resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise RespuestaInesperada(f"la descarga respondió HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise SinRed("sin red al descargar la imagen") from None
    if codigo != 200:
        raise RespuestaInesperada(f"la descarga respondió HTTP {codigo}")
    if len(datos) > max_bytes:
        raise RespuestaInesperada(f"la imagen pasa de {max_bytes} bytes")
    if formato_imagen(datos) is None:
        raise RespuestaInesperada("lo descargado no es una imagen PNG, JPEG ni WEBP")
    return datos
