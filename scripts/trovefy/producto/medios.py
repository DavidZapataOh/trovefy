"""Medios en modo 0640 (contrato 10) y su manifiesto ``<raíz>/medios/medios.json`` (resolución 15).

Los medios (imágenes, PDF, hojas de contactos) se escriben con :func:`escribir_medio`: temporal en el
mismo directorio, ``fchmod 0o640`` y ``os.replace``. El manifiesto es texto y va con
``escribir_atomico``; es la prueba de «imágenes propias» (contrato 4): cada entrada lleva su origen
y el sha256 del archivo, comprobado al registrarla. No toma cerrojo: quien escribe en paralelo
(el lote de APIMart) lo cubre con su ``flock``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from trovefy.vault.escritura import escribir_atomico
from trovefy.vault.producto import secreto_en

MODO_MEDIO = 0o640
ORIGENES = ("apimart", "propio")
CARPETA = "medios"
MANIFIESTO = "medios.json"
_ID = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
_ARCHIVO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


def escribir_medio(ruta: Path, datos: bytes) -> str:
    """Escribe ``datos`` en ``ruta`` con modo 0640 de forma atómica y devuelve su sha256 en hex."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fchmod(f.fileno(), MODO_MEDIO)
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return hashlib.sha256(datos).hexdigest()


def ruta_manifiesto(raiz: Path) -> Path:
    return Path(raiz) / CARPETA / MANIFIESTO


def leer_manifiesto(raiz: Path) -> dict[str, dict]:
    """Entradas del manifiesto por id; ``{}`` si aún no existe. ``ValueError`` si está roto."""
    ruta = ruta_manifiesto(raiz)
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CARPETA}/{MANIFIESTO} no se puede leer: {exc}") from None
    if not isinstance(datos, dict) or not all(isinstance(v, dict) for v in datos.values()):
        raise ValueError(f"{CARPETA}/{MANIFIESTO} no es un mapa id → entrada")
    return datos


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    raise TypeError(f"no se puede guardar en {MANIFIESTO}: {type(valor).__name__}")


def registrar_medio(raiz: Path, id_: str, archivo: str, sha256: str, origen: Literal["apimart", "propio"],
                    **datos: Any) -> None:
    """Añade o reemplaza la entrada ``id_`` del manifiesto de ``raiz``.

    ``archivo`` es un nombre suelto dentro de ``<raíz>/medios/`` que ya existe y cuyo sha256 coincide.
    Los ``datos`` extra (``task_id``, ``modelo``, ``prompt_sha256``, ``coste_usd``…) no pueden pisar
    ``archivo``, ``sha256`` ni ``origen`` (Python lo impide: ``TypeError``); los ``Decimal`` se guardan
    como texto. ``ValueError`` si algo
    no cuadra o si el texto trae algo con forma de secreto; entonces no se escribe nada.
    """
    if not isinstance(id_, str) or not _ID.fullmatch(id_):
        raise ValueError(f"id de medio mal escrito: «{id_}» (usa minúsculas, cifras y guiones)")
    if not isinstance(archivo, str) or not _ARCHIVO.fullmatch(archivo) or ".." in archivo:
        raise ValueError(f"archivo de medio mal escrito: «{archivo}» (solo el nombre, dentro de {CARPETA}/)")
    if origen not in ORIGENES:
        raise ValueError(f"origen de medio no admitido: «{origen}» (solo {', '.join(ORIGENES)})")
    if not isinstance(sha256, str) or not _SHA.fullmatch(sha256):
        raise ValueError(f"sha256 mal escrito para «{id_}»")
    ruta = Path(raiz) / CARPETA / archivo
    if not ruta.is_file():
        raise ValueError(f"el medio {CARPETA}/{archivo} no existe")
    if hashlib.sha256(ruta.read_bytes()).hexdigest() != sha256:
        raise ValueError(f"el sha256 de {CARPETA}/{archivo} no coincide con el archivo")
    entrada = {"archivo": archivo, "sha256": sha256, "origen": origen, **datos}
    entrada = json.loads(json.dumps(entrada, default=_json))
    if secreto_en(entrada):
        raise ValueError("el medio trae algo con forma de secreto; no se guarda")
    manifiesto = leer_manifiesto(raiz)
    manifiesto[id_] = entrada
    texto = json.dumps(manifiesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    escribir_atomico(ruta_manifiesto(raiz), texto)
