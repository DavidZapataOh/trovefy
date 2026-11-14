"""Caché de medios ajenos fuera del vault y del repo, con caducidad (retención)."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_RE_PID = re.compile(r"^p-\d{4}-[a-z0-9-]+$")
_RE_LIB = re.compile(r"^\d{1,25}$")
_CARPETA_MCP = "mcp"
_RE_LOTE = re.compile(r"^lote-.*\.json$")
RETENCION_DIAS = 30


def base_cache() -> Path:
    env = os.environ.get("TROVEFY_CACHE_REFERENCIA")
    base = Path(env) if env else Path.home() / ".cache/trovefy/referencia"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not base.is_symlink():
        base.chmod(0o700)
    return base


def _valida_pid(p_id: str) -> None:
    if not _RE_PID.fullmatch(p_id):
        raise ValueError(f"p_id inválido: {p_id!r}")


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _escribe_atomico(destino: Path, texto: str) -> None:
    tmp = destino.with_name(destino.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(texto)
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)


def _escribe_marca(
    marca: Path, ahora: datetime, retencion_dias: int, extra: dict, renovar: bool = False
) -> None:
    """Escribe caduca.json de forma atómica; sin ``renovar``, una sola vez (nunca se alarga)."""
    if marca.is_symlink() or (marca.exists() and not renovar):
        return
    ahora = _utc(ahora)
    datos = {
        "descargado": ahora.isoformat(),
        "caduca": (ahora + timedelta(days=retencion_dias)).isoformat(),
        **extra,
    }
    _escribe_atomico(marca, json.dumps(datos, ensure_ascii=False))


def carpeta_anuncio(
    p_id: str, library_id: str, ahora: datetime, retencion_dias: int
) -> Path:
    _valida_pid(p_id)
    if not _RE_LIB.fullmatch(library_id):
        raise ValueError(f"library_id inválido: {library_id!r}")
    carpeta = base_cache() / p_id / library_id
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
    carpeta.parent.chmod(0o700)
    carpeta.chmod(0o700)
    _escribe_marca(
        carpeta / "caduca.json",
        ahora,
        retencion_dias,
        {"producto": p_id, "library_id": library_id},
    )
    return carpeta


def caduca_anuncio(p_id: str, library_id: str) -> date | None:
    """Fecha real de caducidad de los medios de un anuncio (su caduca.json), o None si no se lee."""
    _valida_pid(p_id)
    if not _RE_LIB.fullmatch(library_id):
        return None
    marca = base_cache() / p_id / library_id / "caduca.json"
    if marca.is_symlink():
        return None
    try:
        return datetime.fromisoformat(json.loads(marca.read_text())["caduca"]).date()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def textos_path(p_id: str) -> Path:
    _valida_pid(p_id)
    return base_cache() / p_id / "textos.json"


def guardar_textos(
    p_id: str, contenido: str, ahora: datetime, retencion_dias: int
) -> Path:
    destino = textos_path(p_id)
    carpeta = destino.parent
    carpeta.mkdir(parents=True, exist_ok=True, mode=0o700)
    carpeta.chmod(0o700)
    # textos.json se reescribe entero con lo leído hoy: su caducidad cuenta desde esta escritura.
    _escribe_marca(
        carpeta / "caduca.json", ahora, retencion_dias, {"producto": p_id}, renovar=True
    )
    _escribe_atomico(destino, contenido)
    return destino


def _textos_vencidos(ahora: datetime) -> list[Path]:
    ahora = _utc(ahora)
    base = base_cache()
    base_real = base.resolve()
    salida: list[Path] = []
    for nivel1 in sorted(base.iterdir()):
        if nivel1.is_symlink() or not nivel1.is_dir():
            continue
        textos = nivel1 / "textos.json"
        if textos.is_symlink() or not textos.is_file():
            continue
        if not textos.resolve().is_relative_to(base_real):
            continue
        try:
            caduca = _utc(
                datetime.fromisoformat(
                    json.loads((nivel1 / "caduca.json").read_text())["caduca"]
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if caduca <= ahora:
            salida.append(textos)
    return salida


def _lotes_vencidos(
    mcp: Path, ahora: datetime, retencion_dias: int, base_real: Path
) -> list[Path]:
    """Lotes del MCP (``<p-id>/mcp/lote-*.json``) más viejos que la retención, por su mtime."""
    if not mcp.resolve().is_relative_to(base_real):
        return []
    limite = (ahora - timedelta(days=retencion_dias)).timestamp()
    salida: list[Path] = []
    for lote in sorted(mcp.iterdir()):
        if not _RE_LOTE.fullmatch(lote.name):
            continue
        try:
            st = lote.lstat()
        except OSError:
            continue
        if lote.is_symlink() or not stat.S_ISREG(st.st_mode):
            continue
        if st.st_mtime <= limite:
            salida.append(lote)
    return salida


def _recorrer(
    ahora: datetime, base: Path | None = None, retencion_dias: int = RETENCION_DIAS
):
    """Devuelve (vencidas, avisos): solo base/*/* (y los lotes de base/*/mcp/), sin seguir enlaces."""
    ahora = _utc(ahora)
    base = base if base is not None else base_cache()
    base_real = base.resolve()
    vencidas: list[Path] = []
    avisos: list[str] = []
    for nivel1 in sorted(base.iterdir()):
        if nivel1.is_symlink() or not nivel1.is_dir():
            continue
        for carpeta in sorted(nivel1.iterdir()):
            if carpeta.is_symlink() or not carpeta.is_dir():
                continue
            if not carpeta.resolve().is_relative_to(base_real):
                continue
            if carpeta.name == _CARPETA_MCP:
                vencidas.extend(_lotes_vencidos(carpeta, ahora, retencion_dias, base_real))
                continue
            marca = carpeta / "caduca.json"
            try:
                caduca = _utc(
                    datetime.fromisoformat(json.loads(marca.read_text())["caduca"])
                )
            except (OSError, ValueError, KeyError, TypeError):
                avisos.append(
                    f"{carpeta}: sin caduca.json legible; no se borra, revísala"
                )
                continue
            if caduca <= ahora:
                vencidas.append(carpeta)
    return vencidas, avisos


def vencidos(
    ahora: datetime, base: Path | None = None, retencion_dias: int = RETENCION_DIAS
) -> list[Path]:
    return _recorrer(ahora, base, retencion_dias)[0]


def avisos_limpieza(ahora: datetime, base: Path | None = None) -> list[str]:
    return _recorrer(ahora, base)[1]


def limpiar(ahora: datetime, retencion_dias: int = RETENCION_DIAS) -> list[Path]:
    borradas: list[Path] = []
    carpetas_mcp: set[Path] = set()
    for ruta in vencidos(ahora, retencion_dias=retencion_dias):
        if ruta.is_symlink():
            continue
        if ruta.parent.name == _CARPETA_MCP and ruta.is_file():
            ruta.unlink(missing_ok=True)
            carpetas_mcp.add(ruta.parent)
        else:
            shutil.rmtree(ruta)
        borradas.append(ruta)
    for mcp in carpetas_mcp:
        try:
            mcp.rmdir()  # solo si quedó vacía
        except OSError:
            pass
    for textos in _textos_vencidos(ahora):
        textos.unlink(missing_ok=True)
        (textos.parent / "caduca.json").unlink(missing_ok=True)
        borradas.append(textos)
    return borradas
