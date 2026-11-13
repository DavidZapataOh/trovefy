"""Fuentes del ejecutor (``estado/*.json`` del spool) y adaptador único de depósito.

Solo lectura del spool: sin seguir symlinks, sin imprimir contenido de más. Dato ausente = «no medido: <motivo>».
``depositar`` es el ÚNICO punto del plan 13 que deposita propuestas.
"""
from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ZONA_COT = timezone(timedelta(hours=-5))
SPOOL_POR_DEFECTO = "/var/spool/trovefy"
ESTADOS = ("latido", "stop", "limites", "meta", "emparejamiento")
_MAX_BYTES = 1 << 20
_ACT = re.compile(r"\bact_(\d+)")


def enmascarar_cuentas(texto: str) -> str:
    """``act_1234567890123456`` → ``act_…3456``: el número real de la cuenta nunca sale por pantalla ni por Telegram."""
    return _ACT.sub(lambda m: f"act_…{m.group(1)[-4:]}", texto)


class BuzonNoDisponible(Exception):
    """No se puede depositar: el mensaje dice por qué."""


@dataclass(frozen=True)
class Lectura:
    datos: dict | None
    motivo: str | None


def ruta_spool() -> Path:
    return Path(os.environ.get("TROVEFY_SPOOL") or SPOOL_POR_DEFECTO)


def _no_medido(motivo: str) -> Lectura:
    return Lectura(None, f"no medido: {motivo}")


def leer_estado(nombre: str, spool: Path | None = None, cuenta: str | None = None) -> Lectura:
    """Lee ``estado/<nombre>.json``. ``meta.json`` exige ``cuenta``; sin ella o de otra cuenta cuenta como ausente."""
    if nombre not in ESTADOS:
        raise ValueError(f"estado desconocido: {nombre}")
    carpeta = (Path(spool) if spool is not None else ruta_spool()) / "estado"
    ruta = carpeta / f"{nombre}.json"
    try:
        hay_carpeta = carpeta.is_dir()
    except PermissionError:  # la carpeta padre no es atravesable: el usuario aún no está en el grupo
        return _no_medido(f"sin permiso para leer {carpeta} (¿estás en el grupo trovefy?)")
    if not hay_carpeta:
        return _no_medido(f"el ejecutor aún no está instalado (no existe {carpeta})")
    try:
        fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return _no_medido(f"el ejecutor no ha escrito {nombre}.json")
    except PermissionError:
        return _no_medido(f"sin permiso para leer {ruta} (¿estás en el grupo trovefy?)")
    except OSError:
        return _no_medido(f"{nombre}.json ilegible")
    try:
        with os.fdopen(fd, "rb", closefd=False) as f:
            datos = json.loads(f.read(_MAX_BYTES).decode("utf-8"))
    except PermissionError:
        return _no_medido(f"sin permiso para leer {ruta} (¿estás en el grupo trovefy?)")
    except (OSError, ValueError):
        return _no_medido(f"{nombre}.json ilegible")
    finally:
        os.close(fd)
    if not isinstance(datos, dict):
        return _no_medido(f"{nombre}.json ilegible")
    if nombre == "meta":
        if cuenta is None:
            return _no_medido("falta la cuenta de config/caja.yaml para comprobar meta.json")
        if datos.get("cuenta") != cuenta:
            return _no_medido("meta.json es de otra cuenta")
    return Lectura(datos, None)


def depositar(vault: Path, datos: dict, ahora: Callable[[], datetime] | None = None) -> str:
    """Deposita una propuesta en el buzón y devuelve su id. Único punto de depósito del plan 13."""
    if (Path(vault) / ".trovefy" / "STOP").exists():
        raise BuzonNoDisponible("STOP del cerebro activo: no se deposita nada")
    try:
        buzon = importlib.import_module("trovefy.buzon")
    except ImportError:
        raise BuzonNoDisponible("el buzón aún no está instalado (plan 12)") from None
    errores = tuple(getattr(buzon, n) for n in ("StopActivo", "PropuestaInvalida", "IdDuplicado", "CupoAgotado"))
    reloj = ahora or (lambda: datetime.now(ZONA_COT))
    try:
        ruta = buzon.depositar(datos, spool=ruta_spool(), vault=Path(vault), ahora=reloj())
    except errores as e:
        raise BuzonNoDisponible(str(e)) from None
    except PermissionError:
        raise BuzonNoDisponible(
            "sin permiso para depositar (¿estás en el grupo trovefy? cierra y abre la terminal tras instalar)"
        ) from None
    except OSError as e:
        raise BuzonNoDisponible(f"no se pudo depositar: {e.strerror or e}") from None
    return Path(ruta).stem
