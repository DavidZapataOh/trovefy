"""Medios en modo 0640 (contrato 10) y su manifiesto ``<raíz>/medios/medios.json`` (resolución 15).

Los medios (imágenes, PDF, hojas de contactos) se escriben con :func:`escribir_medio`: temporal propio
en el mismo directorio (``O_EXCL | O_NOFOLLOW``), ``fchmod 0o640`` y ``os.replace``. Antes de escribir
se revisa cada carpeta desde la base hasta la del archivo: ninguna puede ser un enlace simbólico. Un
enlace en la ruta final se reemplaza, nunca se sigue. El manifiesto se escribe igual (también 0640);
es la prueba de «imágenes propias» (contrato 4): cada entrada lleva su origen y el sha256 del archivo,
calculado desde el mismo descriptor con que se comprueba que es un archivo regular 0640 y no un
enlace. No toma cerrojo: quien escribe en paralelo (el lote de APIMart) lo cubre con su ``flock``.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from trovefy.vault.producto import secreto_en

MODO_MEDIO = 0o640
ORIGENES = ("apimart", "propio")
EXTENSIONES = (".png", ".jpg", ".jpeg", ".webp", ".pdf")
CARPETA = "medios"
MANIFIESTO = "medios.json"
_CAMPOS = ("archivo", "sha256", "origen")
_ID = re.compile(r"[a-z0-9][a-z0-9-]*", re.ASCII)
_ARCHIVO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


# --- carpetas y escritura ------------------------------------------------------------------------


def carpeta_segura(base: Path, carpeta: Path, *, crear: bool) -> bool:
    """Revisa cada componente de ``carpeta`` por debajo de ``base``: ninguno puede ser un enlace.

    Con ``crear`` crea los que faltan (uno a uno, revisándolos). Sin ``crear`` devuelve ``False`` en
    cuanto falta uno. ``ValueError`` si hay un enlace, algo que no es carpeta o si queda fuera de ``base``.
    """
    base = Path(os.path.abspath(base))
    carpeta = Path(os.path.abspath(carpeta))
    try:
        partes = carpeta.relative_to(base).parts
    except ValueError:
        raise ValueError(f"{carpeta} queda fuera de {base}") from None
    actual = base
    for parte in partes:
        actual = actual / parte
        if crear:
            try:
                os.mkdir(actual)
            except FileExistsError:
                pass
        try:
            info = os.lstat(actual)
        except FileNotFoundError:
            if crear:
                raise
            return False
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{actual} es un enlace simbólico: no se escribe ni se lee a través de él")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{actual} no es una carpeta")
    return True


_carpeta_segura = carpeta_segura  # alias privado: nombre anterior (ruling de la Tarea 13)


def _escribir(ruta: Path, datos: bytes, base: Path) -> None:
    carpeta = ruta.parent
    carpeta_segura(base, carpeta, crear=True)
    tmp = carpeta / f".{ruta.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
            f.flush()
            os.fchmod(f.fileno(), MODO_MEDIO)
            os.fsync(f.fileno())
        os.replace(tmp, ruta)  # rename no sigue un enlace en el destino: lo reemplaza
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def escribir_medio(ruta: Path, datos: bytes, *, base: Path | None = None) -> str:
    """Escribe ``datos`` en ``ruta`` con modo 0640 de forma atómica y devuelve su sha256 en hex.

    ``base`` (el vault, normalmente) marca desde dónde se revisan las carpetas: ninguna entre ``base``
    y ``ruta.parent`` puede ser un enlace simbólico (``ValueError``; no se escribe nada). Sin ``base``
    se revisan la raíz de la pieza y ``medios/`` (los dos niveles por encima del archivo).
    """
    ruta = Path(os.path.abspath(ruta))
    _escribir(ruta, datos, ruta.parents[2] if base is None else Path(base))
    return hashlib.sha256(datos).hexdigest()


# --- manifiesto ----------------------------------------------------------------------------------


def ruta_manifiesto(raiz: Path) -> Path:
    return Path(raiz) / CARPETA / MANIFIESTO


def _abrir_sin_enlace(ruta: Path, que: str) -> int:
    try:
        return os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)  # NONBLOCK: una FIFO no cuelga
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"{que} es un enlace simbólico") from None
        raise


def _hash_medio(raiz: Path, archivo: str) -> str:
    """sha256 de ``<raíz>/medios/<archivo>``: sin seguir enlaces, archivo regular y modo 0640."""
    que = f"el medio {CARPETA}/{archivo}"
    try:
        fd = _abrir_sin_enlace(Path(raiz) / CARPETA / archivo, que)
    except FileNotFoundError:
        raise ValueError(f"{que} no existe") from None
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{que} no es un archivo regular")
        modo = stat.S_IMODE(info.st_mode)
        if modo != MODO_MEDIO:
            raise ValueError(f"{que} tiene modo {modo:o}; debe ser 640")
        h = hashlib.sha256()
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _sin_float(valor: Any, donde: str) -> None:
    if isinstance(valor, float):
        raise ValueError(f"{donde}: no se guardan float en {MANIFIESTO}; el dinero va en Decimal o texto")  # noqa: TRY004 (contrato: ValueError)
    if isinstance(valor, dict):
        for k, v in valor.items():
            _sin_float(v, f"{donde}.{k}")
    elif isinstance(valor, (list, tuple)):
        for i, v in enumerate(valor):
            _sin_float(v, f"{donde}[{i}]")


def _validar(id_: Any, archivo: Any, sha256: Any, origen: Any, datos: dict[str, Any]) -> None:
    if not isinstance(id_, str) or not _ID.fullmatch(id_):
        raise ValueError(f"id de medio mal escrito: «{id_}» (usa minúsculas, cifras y guiones)")
    if archivo == MANIFIESTO:
        raise ValueError(f"archivo de medio no admitido: «{MANIFIESTO}» es el manifiesto")
    if (not isinstance(archivo, str) or not _ARCHIVO.fullmatch(archivo) or ".." in archivo
            or Path(archivo).suffix.lower() not in EXTENSIONES):
        raise ValueError(f"archivo de medio mal escrito: «{archivo}» (solo el nombre, dentro de {CARPETA}/, "
                         f"con extensión {', '.join(e[1:] for e in EXTENSIONES)})")
    if origen not in ORIGENES:
        raise ValueError(f"origen de medio no admitido: «{origen}» (solo {', '.join(ORIGENES)})")
    if not isinstance(sha256, str) or not _SHA.fullmatch(sha256):
        raise ValueError(f"sha256 mal escrito para «{id_}»")
    _sin_float(datos, id_)


def leer_manifiesto(raiz: Path, *, verificar: bool = False) -> dict[str, dict]:
    """Entradas del manifiesto por id; ``{}`` si aún no existe.

    Cada id y cada entrada pasan las mismas comprobaciones que en :func:`registrar_medio`; con
    ``verificar`` además se recalcula el sha256 de cada archivo (sin seguir enlaces, regular, 0640).
    ``ValueError`` en la primera entrada mala, si el manifiesto está roto o si hay un enlace por medio.
    """
    raiz = Path(raiz)
    if not carpeta_segura(raiz.parent, raiz / CARPETA, crear=False):
        return {}
    try:
        fd = _abrir_sin_enlace(ruta_manifiesto(raiz), f"{CARPETA}/{MANIFIESTO}")
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError(f"{CARPETA}/{MANIFIESTO} no es un archivo regular")
        crudo = f.read()
    try:
        datos = json.loads(crudo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{CARPETA}/{MANIFIESTO} no se puede leer: {exc}") from None
    if not isinstance(datos, dict) or not all(isinstance(v, dict) for v in datos.values()):
        raise ValueError(f"{CARPETA}/{MANIFIESTO} no es un mapa id → entrada")
    for id_, entrada in datos.items():
        faltan = [c for c in _CAMPOS if c not in entrada]
        if faltan:
            raise ValueError(f"{CARPETA}/{MANIFIESTO}: a «{id_}» le falta {', '.join(faltan)}")
        resto = {k: v for k, v in entrada.items() if k not in _CAMPOS}
        _validar(id_, entrada["archivo"], entrada["sha256"], entrada["origen"], resto)
        if verificar and _hash_medio(raiz, entrada["archivo"]) != entrada["sha256"]:
            raise ValueError(f"el sha256 de {CARPETA}/{entrada['archivo']} no coincide con el manifiesto")
    return datos


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    raise TypeError(f"no se puede guardar en {MANIFIESTO}: {type(valor).__name__}")


def registrar_medio(raiz: Path, id_: str, archivo: str, sha256: str, origen: Literal["apimart", "propio"],
                    **datos: Any) -> None:
    """Añade o reemplaza la entrada ``id_`` del manifiesto de ``raiz``.

    ``archivo`` es un nombre suelto (png, jpg, jpeg, webp o pdf) dentro de ``<raíz>/medios/``: un
    archivo regular 0640, no un enlace, cuyo sha256 coincide. Los ``datos`` extra (``task_id``,
    ``modelo``, ``prompt_sha256``, ``coste_usd``…) no pueden pisar ``archivo``, ``sha256`` ni ``origen``
    (Python lo impide: ``TypeError``); los ``Decimal`` se guardan como texto y los ``float`` se
    rechazan. ``ValueError`` si algo no cuadra, si hay un enlace en la raíz o en ``medios/`` o si el
    texto trae algo con forma de secreto; entonces no se escribe nada.
    """
    raiz = Path(raiz)
    _validar(id_, archivo, sha256, origen, datos)
    if not carpeta_segura(raiz.parent, raiz / CARPETA, crear=False):
        raise ValueError(f"el medio {CARPETA}/{archivo} no existe")
    if _hash_medio(raiz, archivo) != sha256:
        raise ValueError(f"el sha256 de {CARPETA}/{archivo} no coincide con el archivo")
    try:
        entrada = json.loads(json.dumps({"archivo": archivo, "sha256": sha256, "origen": origen, **datos},
                                        default=_json))
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc) if "no se puede guardar" in str(exc)
                         else f"no se puede guardar en {MANIFIESTO}: {exc}") from None
    if secreto_en(entrada):
        raise ValueError("el medio trae algo con forma de secreto; no se guarda")
    manifiesto = leer_manifiesto(raiz)
    manifiesto[id_] = entrada
    texto = json.dumps(manifiesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _escribir(ruta_manifiesto(raiz), texto.encode("utf-8"), raiz.parent)
