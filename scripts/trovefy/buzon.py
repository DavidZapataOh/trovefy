"""Buzón de propuestas (lado de Claude): deposita en el spool del ejecutor y lee su estado.

Falla cerrado: ante STOP, id fuera de 001-799, esquema inválido o cualquier duda no se escribe nada.
Solo importa ``trovefy_ejecutor.esquema`` (resolución de aislamiento entre paquetes).
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta

COT = timezone(timedelta(hours=-5))
SPOOL_POR_DEFECTO = "/var/spool/trovefy"
MAX_ID = 799
# El ejecutor late cada 30 s antes del long-poll, pero con 429 de Telegram un ciclo puede tardar ≈ 200 s.
LATIDO_MAX_S = 300
INTENTOS_ID = 5
_ID = re.compile(r"^P-([0-9]{8})-([0-9]{3})$")
_NUM = re.compile(r"^P-([0-9]{8})-([0-9]{3})(?:[.-]|$)")


class CupoAgotado(Exception):
    """Ya hay 799 propuestas de Claude hoy."""


class IdDuplicado(Exception):
    """El id que trae la propuesta ya existe en el buzón."""


class StopActivo(Exception):
    """Existe ``<vault>/.trovefy/STOP``: no se deposita nada."""


def raiz_spool() -> Path:
    return Path(os.environ.get("TROVEFY_SPOOL") or SPOOL_POR_DEFECTO)


def _maximo(carpeta: Path, prefijo: str) -> int:
    mayor = 0
    for nombre in os.listdir(carpeta):
        m = _NUM.match(nombre)
        if m and m.group(1) == prefijo and 1 <= int(m.group(2)) <= MAX_ID:
            mayor = max(mayor, int(m.group(2)))
    return mayor


def nuevo_id(spool: Path, dia: date) -> str:
    prefijo = dia.strftime("%Y%m%d")
    mayor = _maximo(Path(spool) / "entrada", prefijo)
    try:
        mayor = max(mayor, _maximo(Path(spool) / "procesadas", prefijo))
    except OSError:
        pass  # sin acceso a procesadas/: se cuenta solo entrada/
    if mayor >= MAX_ID:
        raise CupoAgotado("799 propuestas hoy: no se deposita más")
    return f"P-{prefijo}-{mayor + 1:03d}"


def _comprobar_unidades(datos: dict) -> None:
    ops = datos.get("operaciones")
    if not isinstance(ops, list):
        return
    for op in ops:
        # La unidad solo viaja en operaciones de importe (el esquema exige que falte en las demás).
        if isinstance(op, dict) and "unidad" in op and op["unidad"] != "minima":
            raise PropuestaInvalida('unidad: debe ser "minima"')


def _escribir(spool: Path, id_: str, datos: dict) -> Path:
    entrada = Path(spool) / "entrada"
    tmp = entrada / f".{id_}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    destino = entrada / f"{id_}.json"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    except FileExistsError:
        raise OSError(f"temporal ya existente en el buzón: {tmp.name}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o640)
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, destino, follow_symlinks=False)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return destino


def depositar(datos: dict, *, spool: Path, vault: Path, ahora: datetime) -> Path:
    if (Path(vault) / ".trovefy" / "STOP").exists():
        raise StopActivo("STOP activo: no se deposita nada")
    if not isinstance(datos, dict):
        raise PropuestaInvalida("la propuesta debe ser un objeto")
    datos = dict(datos)
    _comprobar_unidades(datos)
    ahora_cot = ahora.astimezone(COT)
    generado = "id" not in datos
    if not generado:
        m = _ID.match(datos["id"]) if isinstance(datos["id"], str) else None
        if not m or not 1 <= int(m.group(2)) <= MAX_ID:
            raise PropuestaInvalida(f"id: debe ser P-AAAAMMDD-NNN con NNN 001-{MAX_ID}")
    datos.setdefault("creada", ahora_cot.isoformat(timespec="seconds"))
    datos["version"] = 1
    for _ in range(INTENTOS_ID):
        if generado:
            datos["id"] = nuevo_id(spool, ahora_cot.date())
        cargar_propuesta(datos)
        try:
            return _escribir(spool, datos["id"], datos)
        except FileExistsError:
            if not generado:
                raise IdDuplicado(f"ya existe {datos['id']} en el buzón") from None
    raise IdDuplicado("no se pudo reservar un id libre tras varios intentos")


def _leer_json(ruta: Path) -> dict | None:
    try:
        fd = os.open(ruta, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            with os.fdopen(fd, "rb", closefd=False) as f:
                datos = json.loads(f.read(1 << 20).decode("utf-8"))
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def estado(spool: Path, ahora: datetime) -> dict:
    """Estado del ejecutor; lo ilegible queda en None («no medido»)."""
    carpeta = Path(spool) / "estado"
    sal: dict = {n: _leer_json(carpeta / f"{n}.json")
                 for n in ("latido", "stop", "emparejamiento", "meta", "limites")}
    try:
        sal["pendientes"] = sum(1 for n in os.listdir(Path(spool) / "entrada")
                                if n.endswith(".json") and not n.startswith("."))
    except OSError:
        sal["pendientes"] = None
    viejo = True
    latido = sal["latido"]
    if latido is not None and isinstance(latido.get("fecha"), str):
        try:
            f = datetime.fromisoformat(latido["fecha"])
            if f.tzinfo is not None:
                viejo = (ahora - f).total_seconds() > LATIDO_MAX_S
        except ValueError:
            pass
    sal["latido_viejo"] = viejo
    return sal
