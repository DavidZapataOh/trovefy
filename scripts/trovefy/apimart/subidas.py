"""Subida de imágenes de referencia a APIMart con caché de 60 h.

Patrón portado de LordVayron/video-factory ``engine/lib/apimart.mjs`` (MIT, commit 8afd1b2e).

``POST /v1/uploads/images?retention_days=3`` (multipart, campo ``file``) devuelve ``url`` en la raíz
(``tests/fixtures/apimart/subida-imagen.json``). APIMart guarda la subida 72 h; aquí se reutiliza la URL
mientras tenga menos de 60 h, con margen para que no caduque a mitad de un lote. La caché
``data/cache/apimart-subidas.json`` (sha1 → ``{url, subida}``) se lee y escribe bajo ``flock``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from trovefy.apimart.cliente import formato_imagen
from trovefy.apimart.http import (
    Credenciales,
    RespuestaInesperada,
    abrir_sin_redireccion,
    pedir,
)
from trovefy.vault.escritura import escribir_atomico

RUTA_CACHE = Path("data") / "cache" / "apimart-subidas.json"
RUTA_CERROJO = Path("data") / "cache" / ".apimart-subidas.lock"
VIGENCIA = timedelta(hours=60)  # APIMart guarda 72 h (retention_days=3)
RETENCION_DIAS = 3
MAX_SUBIDA = 20 * 2**20  # «Max 20 MB per image» en image_urls
_TIPOS = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _leer_cache(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _vigente(entrada: object, ahora: datetime) -> str | None:
    if not isinstance(entrada, dict) or not isinstance(entrada.get("url"), str):
        return None
    try:
        subida = datetime.fromisoformat(entrada["subida"])
    except (KeyError, TypeError, ValueError):
        return None
    if subida.tzinfo is None or not timedelta(0) <= ahora - subida < VIGENCIA:
        return None
    return entrada["url"]


def _multipart(nombre: str, tipo: str, datos: bytes) -> tuple[bytes, str]:
    frontera = f"trovefy-{uuid.uuid4().hex}"
    cabeza = (f'--{frontera}\r\nContent-Disposition: form-data; name="file"; filename="{nombre}"\r\n'
              f"Content-Type: {tipo}\r\n\r\n").encode()
    return cabeza + datos + f"\r\n--{frontera}--\r\n".encode(), f"multipart/form-data; boundary={frontera}"


def subir(cred: Credenciales, ruta: Path, vault: Path, abrir=abrir_sin_redireccion, ahora: datetime | None = None) -> str:
    """URL pública de ``ruta`` en APIMart: la de la caché si tiene menos de 60 h; si no, la sube."""
    if ahora is None or ahora.tzinfo is None or ahora.utcoffset() is None:
        raise ValueError("ahora debe ser un datetime con zona horaria")
    ruta = Path(ruta)
    datos = ruta.read_bytes()
    if len(datos) > MAX_SUBIDA:
        raise ValueError(f"{ruta.name} pasa de 20 MB; APIMart no lo admite como referencia")
    formato = formato_imagen(datos)
    if formato is None:
        raise ValueError(f"{ruta.name} no es una imagen PNG, JPEG ni WEBP")
    sha1 = hashlib.sha1(datos, usedforsecurity=False).hexdigest()
    cache = Path(vault) / RUTA_CACHE
    cerrojo = Path(vault) / RUTA_CERROJO
    cerrojo.parent.mkdir(parents=True, exist_ok=True)
    with open(cerrojo, "a+b") as fc:
        fcntl.flock(fc, fcntl.LOCK_EX)
        try:
            tabla = _leer_cache(cache)
            url = _vigente(tabla.get(sha1), ahora)
            if url is not None:
                return url
            cuerpo, tipo = _multipart(f"{re.sub(r'[^A-Za-z0-9_-]', '-', ruta.stem)[:60] or 'imagen'}.{formato}", _TIPOS[formato], datos)
            resp = pedir(cred, "POST", f"/v1/uploads/images?retention_days={RETENCION_DIAS}", cuerpo, tipo,
                         abrir, timeout=120)
            url = resp.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise RespuestaInesperada("APIMart no devolvió una URL https de la subida")
            tabla[sha1] = {"url": url, "subida": ahora.isoformat()}
            escribir_atomico(cache, json.dumps(tabla, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            return url
        finally:
            fcntl.flock(fc, fcntl.LOCK_UN)
