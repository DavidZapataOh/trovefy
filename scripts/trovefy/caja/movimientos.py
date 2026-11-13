"""``ledger/caja/movimientos.csv``: libro solo de añadir. Nunca se reescribe una fila."""

from __future__ import annotations

import csv
import fcntl
import io
import os
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

CABECERA = [
    "fecha", "tipo", "origen", "destino", "usd_centavos", "importe_original",
    "moneda_original", "trm", "trm_fecha", "nota", "decision",
]  # fmt: skip
TIPOS = ("mover", "herramienta")


class MovimientosCorruptos(ValueError):
    """Fila con columnas de más o de menos, o con importe ilegible. Nunca se «arregla»."""


@dataclass(frozen=True)
class Movimiento:
    fecha: datetime
    tipo: str
    origen: str
    destino: str
    usd_centavos: int
    importe_original: str
    moneda_original: str
    trm: str
    trm_fecha: str
    nota: str
    decision: str


def _ruta(vault: Path) -> Path:
    return Path(vault) / "ledger" / "caja" / "movimientos.csv"


def _fila(m: Movimiento) -> list[str]:
    if m.tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {m.tipo!r}")
    if isinstance(m.usd_centavos, bool) or not isinstance(m.usd_centavos, int):
        raise TypeError("usd_centavos debe ser int")
    return [m.fecha.isoformat(), *[str(getattr(m, f.name)) for f in fields(m)[1:]]]


def _linea(valores: list[str]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(valores)
    return buf.getvalue()


def anotar_movimiento(vault: Path, m: Movimiento) -> None:
    """Añade una fila (``flock``); la cabecera solo si el archivo es nuevo. Rechaza enlaces simbólicos."""
    texto = _linea(_fila(m))
    ruta = _ruta(vault)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            nuevo = os.fstat(fd).st_size == 0
            datos = (_linea(CABECERA) if nuevo else "") + texto
            os.write(fd, datos.encode("utf-8"))
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def leer_movimientos(vault: Path) -> list[Movimiento]:
    ruta = _ruta(vault)
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = list(csv.reader(f))
    if not filas:
        return []
    if filas[0] != CABECERA:
        raise MovimientosCorruptos("movimientos.csv: cabecera inesperada")
    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        if len(fila) != len(CABECERA):
            raise MovimientosCorruptos(
                f"movimientos.csv línea {n}: {len(fila)} columnas"
            )
        try:
            fecha = datetime.fromisoformat(fila[0])
            centavos = int(fila[4])
        except ValueError:
            raise MovimientosCorruptos(
                f"movimientos.csv línea {n}: fecha o importe ilegible"
            ) from None
        if fila[1] not in TIPOS:
            raise MovimientosCorruptos(f"movimientos.csv línea {n}: tipo {fila[1]!r}")
        salida.append(Movimiento(fecha, fila[1], fila[2], fila[3], centavos, *fila[5:]))
    return salida
