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
    marca = carpeta / "caduca.json"
    if not marca.exists():
        ahora = _utc(ahora)
        marca.write_text(
            json.dumps(
                {
                    "descargado": ahora.isoformat(),
                    "caduca": (ahora + timedelta(days=retencion_dias)).isoformat(),
                    "producto": p_id,
                    "library_id": library_id,
                },
                ensure_ascii=False,
            )
        )
    return carpeta


def textos_path(p_id: str) -> Path:
    _valida_pid(p_id)
    return base_cache() / p_id / "textos.json"


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
    return borradas
