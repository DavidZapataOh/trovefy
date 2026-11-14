"""Descarga segura de medios de referencia (fbcdn/fbsbx).

Adaptado de barral0/jev-ad-pattern-lab `media.py` (MIT, © 2026 Filipe Barral): validación de host, DNS público e IP fijada. Portado de httpx a http.client y ampliado a vídeo.

Las URLs de Meta llevan tokens en la query (`oh=`, `oe=`): ningún mensaje de
error ni registro las incluye. No se siguen redirecciones y no se usan
variables de entorno de proxy.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import os
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

HOSTS = ("fbcdn.net", "fbsbx.com")
TIPOS = {
    "video/mp4": 60 * 1024**2,
    "image/jpeg": 8 * 1024**2,
    "image/png": 8 * 1024**2,
    "image/webp": 8 * 1024**2,
}
TIMEOUT_S = 30
_TROZO = 64 * 1024
_EXT = {
    "video/mp4": "mp4",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class DescargaRechazada(ValueError):
    """Rechazo apto para el usuario; nunca incluye la query de la URL."""


def url_permitida(url: str) -> bool:
    try:
        p = urlsplit(url)
        puerto = p.port
    except ValueError:
        return False
    if p.scheme != "https" or puerto not in (None, 443):
        return False
    if p.username is not None or p.password is not None:
        return False
    host = (p.hostname or "").lower()
    return any(host.endswith("." + d) for d in HOSTS)


def _resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


def _es_global(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def ip_publica(host: str, resolver=_resolver) -> str:
    try:
        ips = list(resolver(host))
    except OSError:
        raise DescargaRechazada("No se pudo resolver el host del medio.") from None
    if not ips or not all(_es_global(i) for i in ips):
        raise DescargaRechazada("El host del medio no resuelve a una IP pública.")
    return ips[0]


class _ConexionFijada(http.client.HTTPSConnection):
    """Conecta a la IP ya validada, con SNI y verificación del host original."""

    def __init__(self, ip: str, host: str):
        super().__init__(host, 443, timeout=TIMEOUT_S)
        self._ip = ip
        self._host_sni = host

    def connect(self) -> None:
        s = socket.create_connection((self._ip, 443), TIMEOUT_S)
        try:
            self.sock = ssl.create_default_context().wrap_socket(
                s, server_hostname=self._host_sni
            )
        except Exception:
            s.close()
            raise


def _conectar(ip: str, host: str):
    return _ConexionFijada(ip, host)


def _firma_ok(tipo: str, cabeza: bytes) -> bool:
    if tipo == "video/mp4":
        return cabeza[4:8] == b"ftyp"
    if tipo == "image/jpeg":
        return cabeza[:3] == b"\xff\xd8\xff"
    if tipo == "image/png":
        return cabeza[:4] == b"\x89PNG"
    return cabeza[:4] == b"RIFF" and cabeza[8:12] == b"WEBP"


def descargar_medio(
    url: str, destino_sin_ext: Path, resolver=_resolver, conectar=_conectar
) -> Path:
    if not url_permitida(url):
        raise DescargaRechazada("URL de medio no permitida (host o esquema).")
    p = urlsplit(url)
    host = p.hostname
    ip = ip_publica(host, resolver)
    ruta = (p.path or "/") + (f"?{p.query}" if p.query else "")
    destino_sin_ext = Path(destino_sin_ext)
    parcial = destino_sin_ext.with_name(destino_sin_ext.name + ".part")
    con = None
    try:
        con = conectar(ip, host)
        con.request("GET", ruta, headers={"Host": host, "Accept": "*/*"})
        resp = con.getresponse()
        if resp.status != 200:
            raise DescargaRechazada(
                f"El servidor respondió {resp.status}; no se siguen redirecciones."
            )
        tipo = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if tipo not in TIPOS:
            raise DescargaRechazada("Tipo de contenido no permitido.")
        tope = TIPOS[tipo]
        total = 0
        cabeza = b""
        fd = os.open(parcial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            while True:
                trozo = resp.read(_TROZO)
                if not trozo:
                    break
                total += len(trozo)
                if total > tope:
                    raise DescargaRechazada("El medio supera el tamaño máximo.")
                if len(cabeza) < 12:
                    cabeza = (cabeza + trozo)[:12]
                f.write(trozo)
        if not _firma_ok(tipo, cabeza):
            raise DescargaRechazada("El contenido no coincide con su tipo declarado.")
        destino = destino_sin_ext.with_name(f"{destino_sin_ext.name}.{_EXT[tipo]}")
        os.chmod(parcial, 0o600)
        os.replace(parcial, destino)
        return destino
    except DescargaRechazada:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise DescargaRechazada("No se pudo descargar el medio.") from None
    finally:
        if con is not None:
            with contextlib.suppress(OSError, http.client.HTTPException):
                con.close()
        try:
            parcial.unlink()
        except FileNotFoundError:
            pass
