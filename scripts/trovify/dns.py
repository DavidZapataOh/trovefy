"""Consultas DNS públicas por DNS sobre HTTPS (Cloudflare), sin dependencias nuevas."""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Literal
from urllib.parse import quote, urlsplit

URL_DOH = "https://cloudflare-dns.com/dns-query"
TIMEOUT = 10
MAX_BYTES = 65536
_ETIQUETA = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


class SinRed(Exception):
    pass


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _abrir_sin_redireccion(req, timeout=None):
    return urllib.request.build_opener(_SinRedireccion).open(req, timeout=timeout)


def normalizar(dominio: str) -> str:
    """Minúsculas, sin esquema, `www.`, punto final ni ruta. Lanza ValueError si no es un dominio plausible."""
    crudo = dominio.strip()
    if "://" not in crudo:
        crudo = "//" + crudo
    try:
        partes = urlsplit(crudo)
        host = partes.hostname
        partes.port  # noqa: B018  (valida el puerto)
    except ValueError:
        raise ValueError("el dominio no es válido") from None
    if "@" in partes.netloc or not host:
        raise ValueError("el dominio no es válido")
    host = host.lower().rstrip(".")
    host = host.removeprefix("www.")
    etiquetas = host.split(".")
    if len(etiquetas) < 2 or len(host) > 253 or not all(_ETIQUETA.fullmatch(e) for e in etiquetas):
        raise ValueError("el dominio no es válido (ejemplo: midominio.com)")
    if etiquetas[-1].isdigit():  # una IP, no un dominio
        raise ValueError("el dominio no puede ser una dirección IP")
    return host


def consultar(
    nombre: str, tipo: Literal["NS", "TXT", "A"], abrir: Callable = _abrir_sin_redireccion
) -> list[str]:
    """Registros `tipo` de `nombre`; [] si no existen. Lanza SinRed si no hay respuesta útil."""
    if tipo not in ("NS", "TXT", "A"):
        raise ValueError("tipo de registro no admitido")
    nombre = normalizar(nombre)
    req = urllib.request.Request(
        f"{URL_DOH}?name={quote(nombre)}&type={tipo}", headers={"Accept": "application/dns-json"}
    )
    try:
        with abrir(req, timeout=TIMEOUT) as resp:
            estado, cuerpo = resp.status, resp.read(MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError):  # incluye HTTPError
        raise SinRed from None
    if estado != 200:
        raise SinRed
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        raise SinRed from None
    respuestas = datos.get("Answer") if isinstance(datos, dict) else None
    if not isinstance(respuestas, list):
        return []
    return [r["data"] for r in respuestas if isinstance(r, dict) and isinstance(r.get("data"), str)]
