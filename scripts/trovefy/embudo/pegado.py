"""Evidencias que aporta el usuario (plan 19, Tarea 6): capturas, textos (un email) y sus palabras literales.

trovefy no entra en ningún panel: lo que pasa ahí lo prueba el usuario pegando una captura, un texto o
diciéndolo. Todo va a ``productos/<p>/checkout/<PAIS>/evidencia/`` (0600, sin pisar nada) y a ``indice.yaml``,
que solo crece. Fuerza de la evidencia: ``captura`` > ``dicho``.

Regla de la skill (Tarea 16): antes de registrar una captura, Claude la mira con Read; si ve un token, una
contraseña o datos de tarjeta, no la registra y pide otra. Aquí se comprueba lo que se puede comprobar sin ojos:
que la imagen es una imagen, el tamaño, y que los textos y valores no llevan nada con forma de secreto.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml

from trovefy.embudo.contexto import ruta_pais
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import anadir_log, escribir_atomico

CLAVES: tuple[str, ...] = (
    "tracking-pixel", "plan-tienda", "market", "ver-como", "producto", "checkout", "upsell-u1", "upsell-u2",
    "upsell-u3", "downsell", "emails", "bump", "pedido", "email-entrega", "pdf-descargado", "reembolso",
    "test-events",
)
MAX_BYTES = 10 * 1024 * 1024
INDICE = "indice.yaml"
_IMAGENES = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}
_TEXTOS = (".txt", ".eml")
_UNIDAD = re.compile(r"([A-Za-z]):[\\/](.*)", re.DOTALL)
_WSL = re.compile(r"\\\\(?:wsl\.localhost|wsl\$)\\[^\\]+(\\.*)?", re.IGNORECASE | re.DOTALL)
_CLAVE_VALOR = re.compile(r"[a-z][a-z0-9_-]{0,39}")


@dataclass(frozen=True)
class Pegado:
    clave: str
    ruta: str
    tipo: Literal["captura", "texto", "dicho"]
    sha256: str
    fecha: str
    valores: dict[str, str] = field(default_factory=dict)
    nota: str = ""


def ruta_local(origen: str | Path) -> Path:
    """La ruta en WSL de lo que pega el usuario desde Windows: ``C:\\…`` → ``/mnt/c/…``,
    ``\\\\wsl.localhost\\<distro>\\…`` (o ``\\\\wsl$\\…``) → la ruta local. Lo demás, tal cual."""
    texto = str(origen).strip().strip('"')
    m = _WSL.fullmatch(texto)
    if m:
        return Path("/" + (m.group(1) or "").replace("\\", "/").lstrip("/"))
    m = _UNIDAD.fullmatch(texto)
    if m:
        return Path(f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/"))
    return Path(texto)


def _exigir_clave(clave: str) -> None:
    if clave not in CLAVES:
        raise ValueError(f"clave desconocida «{clave}»: usa una de {', '.join(CLAVES)}")


def _leer_origen(ruta: Path) -> bytes:
    try:
        fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise ValueError(f"no existe {ruta}") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"{ruta} es un enlace simbólico: pega el archivo de verdad") from None
        raise ValueError(f"no puedo abrir {ruta} ({exc.strerror})") from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError(f"{ruta} no es un archivo normal")
    with os.fdopen(fd, "rb") as f:
        datos = f.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise ValueError(f"{ruta.name} pasa de 10 MB: recórtala o comprímela")
    if not datos:
        raise ValueError(f"{ruta.name} está vacío")
    return datos


def _es_imagen(datos: bytes, tipo: str) -> bool:
    if tipo == "png":
        return datos.startswith(b"\x89PNG\r\n\x1a\n")
    if tipo == "jpg":
        return datos.startswith(b"\xff\xd8\xff")
    return datos[:4] == b"RIFF" and datos[8:12] == b"WEBP"


def _secreto(*textos: str) -> None:
    for texto in textos:
        patron = buscar_secreto(texto)
        if patron:
            raise ValueError(f"parece llevar un secreto ({patron}): no lo guardo; borra esa parte y vuelve a pegarlo")


def _valores(valores: dict | None) -> dict[str, str]:
    salida: dict[str, str] = {}
    for k, v in (valores or {}).items():
        if not isinstance(k, str) or not _CLAVE_VALOR.fullmatch(k) or not isinstance(v, str) or not v.strip():
            raise ValueError(f"valor mal escrito «{k}={v}»: usa nombre=valor (nombre en minúsculas)")
        salida[k] = v.strip()
    _secreto(*salida.values())
    return salida


def _carpeta(ctx) -> Path:
    return ruta_pais(ctx) / "evidencia"


def _escribir_nuevo(destino: Path, datos: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise ValueError(f"ya existe {destino.name}: no lo piso (espera un segundo y vuelve a pegarlo)") from None
    with os.fdopen(fd, "wb") as f:
        f.write(datos)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(destino, 0o600)


def _registrar(vault: Path, ctx, p: Pegado, destino: Path, ahora: datetime) -> Pegado:
    ruta_indice = _carpeta(ctx) / INDICE
    lista = _leer_indice(ruta_indice)
    lista.append(asdict(p))
    escribir_atomico(ruta_indice, yaml.safe_dump(lista, allow_unicode=True, sort_keys=False))
    anadir_log(Path(vault), "checkout", f"{ctx.producto} {ctx.pais}: evidencia {p.clave} ({p.tipo})",
               [destino.relative_to(Path(vault)).as_posix()], ahora=ahora)
    return p


def _nombre(clave: str, ahora: datetime, ext: str) -> str:
    return f"{clave}-{ahora:%Y-%m-%dT%H%M%S}.{ext}"


def _rel(ctx, destino: Path) -> str:
    return destino.relative_to(ruta_pais(ctx).parent.parent).as_posix()


def guardar_pegado(vault: Path, ctx, clave: str, origen: str | Path, valores: dict | None,
                   ahora: datetime, nota: str = "") -> Pegado:
    """Copia `origen` (una captura PNG/JPEG/WebP o un texto .txt/.eml) a
    ``checkout/<PAIS>/evidencia/<clave>-<AAAA-MM-DDTHHMMSS>.<ext>`` (0600, sin pisar) y lo añade al índice.

    `valores` = lo que Claude leyó en la captura y el usuario confirmó (``{"precio": "13,90 €"}``).
    ``ValueError`` (sin escribir nada) si la clave no existe, el origen no es un archivo normal, la imagen no lo
    es por sus primeros bytes, pasa de 10 MB, o un texto o un valor lleva algo con forma de secreto."""
    _exigir_clave(clave)
    ruta = ruta_local(origen)
    ext = ruta.suffix.lower()
    if ext not in _IMAGENES and ext not in _TEXTOS:
        raise ValueError(f"extensión {ext or '(ninguna)'} no admitida: una captura .png/.jpg/.webp o un texto "
                         ".txt/.eml")
    datos = _leer_origen(ruta)
    vals = _valores(valores)
    _secreto(nota)
    if ext in _IMAGENES:
        tipo, ext_final = "captura", _IMAGENES[ext]
        if not _es_imagen(datos, ext_final):
            raise ValueError(f"{ruta.name} no es una imagen {ext_final.upper()} de verdad: vuelve a hacer la captura")
    else:
        tipo, ext_final = "texto", ext[1:]
        try:
            texto = datos.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"{ruta.name} no es texto UTF-8: cópialo en un .txt") from None
        _secreto(texto)
    destino = _carpeta(ctx) / _nombre(clave, ahora, ext_final)
    _escribir_nuevo(destino, datos)
    p = Pegado(clave=clave, ruta=_rel(ctx, destino), tipo=tipo, sha256=hashlib.sha256(datos).hexdigest(),
               fecha=ahora.isoformat(timespec="seconds"), valores=vals, nota=nota)
    return _registrar(vault, ctx, p, destino, ahora)


def dicho(vault: Path, ctx, clave: str, cita: str, ahora: datetime) -> Pegado:
    """Las palabras literales del usuario, fechadas, en ``evidencia/<clave>-<fecha>.md`` (la evidencia más débil)."""
    _exigir_clave(clave)
    if not isinstance(cita, str) or not cita.strip():
        raise ValueError("la cita está vacía: copia las palabras del usuario tal cual")
    _secreto(cita)
    texto = frontmatter.renderizar({"tipo": "evidencia", "clave": clave, "fuente": "dicho",
                                    "fecha": ahora.isoformat(timespec="seconds")},
                                   f"Palabras literales del usuario:\n\n{cita}\n")
    destino = _carpeta(ctx) / _nombre(clave, ahora, "md")
    _escribir_nuevo(destino, texto.encode("utf-8"))
    p = Pegado(clave=clave, ruta=_rel(ctx, destino), tipo="dicho",
               sha256=hashlib.sha256(cita.encode("utf-8")).hexdigest(), fecha=ahora.isoformat(timespec="seconds"))
    return _registrar(vault, ctx, p, destino, ahora)


def _leer_indice(ruta: Path) -> list[dict]:
    if not ruta.is_file():
        return []
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    if datos is None:
        return []
    if not isinstance(datos, list) or not all(isinstance(x, dict) for x in datos):
        raise ValueError(f"{ruta.name} está roto: no es una lista de evidencias")
    return datos


def indice(vault: Path, ctx) -> dict[str, list[Pegado]]:
    """Las evidencias registradas, por clave y en orden de llegada."""
    salida: dict[str, list[Pegado]] = {}
    for d in _leer_indice(_carpeta(ctx) / INDICE):
        campos = {k: d.get(k) for k in Pegado.__dataclass_fields__}
        campos["valores"] = dict(campos["valores"] or {})
        campos["nota"] = campos["nota"] or ""
        p = Pegado(**campos)
        salida.setdefault(p.clave, []).append(p)
    return salida
