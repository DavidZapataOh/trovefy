"""Caché de medios ajenos fuera del vault y del repo, con caducidad (retención)."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

_RE_PID = re.compile(r"^p-\d{4}-[a-z0-9-]+$")
_RE_LIB = re.compile(r"^\d{1,25}$")


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
    marca: Path, ahora: datetime, retencion_dias: int, extra: dict
) -> None:
    """Escribe caduca.json una sola vez (nunca se alarga) y de forma atómica."""
    if marca.exists() or marca.is_symlink():
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
    _escribe_marca(carpeta / "caduca.json", ahora, retencion_dias, {"producto": p_id})
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


def _recorrer(ahora: datetime):
    """Devuelve (vencidas, avisos): solo base/*/*, sin seguir enlaces simbólicos."""
    ahora = _utc(ahora)
    base = base_cache()
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


def vencidos(ahora: datetime) -> list[Path]:
    return _recorrer(ahora)[0]


def avisos_limpieza(ahora: datetime) -> list[str]:
    return _recorrer(ahora)[1]


def limpiar(ahora: datetime) -> list[Path]:
    borradas: list[Path] = []
    for carpeta in vencidos(ahora):
        if carpeta.is_symlink():
            continue
        shutil.rmtree(carpeta)
        borradas.append(carpeta)
    for textos in _textos_vencidos(ahora):
        textos.unlink(missing_ok=True)
        (textos.parent / "caduca.json").unlink(missing_ok=True)
        borradas.append(textos)
    return borradas
