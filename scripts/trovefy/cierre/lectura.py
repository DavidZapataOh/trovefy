"""Lectura de los ledgers del cierre por periodo (contrato con el plan 23 y con `/caja`).

``ledger/gasto/AAAA-MM.csv`` (cabecera de `trovefy.caja.gasto.CABECERA`) y ``ledger/ventas/AAAA-MM.csv``.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from trovefy.caja.gasto import CABECERA as CABECERA_GASTO

CABECERA_VENTAS = ["fecha", "tienda", "orden", "producto", "pais", "total", "moneda", "post_compra", "metodo_pago",
                   "estado", "visto_primero", "visto_ultimo", "fuente", "detectada"]
ESTADOS = ("aprobada", "desaparecida", "prueba")


@dataclass(frozen=True)
class VentaLedger:
    fecha: date
    tienda: str
    orden: str
    producto: str
    pais: str
    total: Decimal
    moneda: str
    post_compra: bool
    metodo_pago: str | None
    estado: str
    visto_primero: str
    visto_ultimo: str
    fuente: str
    detectada: date | None  # día (zona de la cuenta) en que se vio que ya no estaba: reembolso o anulación


@dataclass(frozen=True)
class GastoLedger:
    fecha: date
    cuenta: str
    campana: str
    gasto: Decimal
    moneda: str


def carpeta(vault: Path, que: str) -> Path:
    return Path(vault) / "ledger" / que


def filas_csv(ruta: Path, cabecera: list[str]) -> list[dict[str, str]]:
    if not ruta.is_file():
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != cabecera:
            raise ValueError(f"{ruta.name}: cabecera inesperada")
        return [dict(r) for r in lector]


def venta_de_fila(r: dict[str, str]) -> VentaLedger:
    try:
        return VentaLedger(
            date.fromisoformat(r["fecha"]), r["tienda"], r["orden"], r["producto"], r["pais"], Decimal(r["total"]),
            r["moneda"], r["post_compra"] == "si", r["metodo_pago"] or None, r["estado"], r["visto_primero"],
            r["visto_ultimo"], r["fuente"], date.fromisoformat(r["detectada"]) if r.get("detectada") else None)
    except (KeyError, ValueError, InvalidOperation) as exc:
        raise ValueError(f"fila de ventas ilegible: {r.get('orden')!r}") from exc


def _meses(desde: date, hasta: date) -> list[str]:
    meses, a, m = [], desde.year, desde.month
    while (a, m) <= (hasta.year, hasta.month):
        meses.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return meses


def ventas_del_periodo(vault: Path, desde: date, hasta: date) -> list[VentaLedger]:
    """Ventas del ledger con ``desde <= fecha <= hasta`` (todos los estados; quien lee filtra)."""
    salida = []
    for mes in _meses(desde, hasta):
        for r in filas_csv(carpeta(vault, "ventas") / f"{mes}.csv", CABECERA_VENTAS):
            v = venta_de_fila(r)
            if desde <= v.fecha <= hasta:
                salida.append(v)
    return salida


def todas_las_ventas(vault: Path) -> list[VentaLedger]:
    c = carpeta(vault, "ventas")
    return [venta_de_fila(r) for ruta in sorted(c.glob("*.csv")) if c.is_dir()
            for r in filas_csv(ruta, CABECERA_VENTAS)]


def gasto_del_periodo(vault: Path, desde: date, hasta: date, campana: str | None = None) -> list[GastoLedger]:
    salida = []
    for mes in _meses(desde, hasta):
        for r in filas_csv(carpeta(vault, "gasto") / f"{mes}.csv", CABECERA_GASTO):
            try:
                g = GastoLedger(date.fromisoformat(r["fecha"][:10]), r["cuenta"], r["campana"], Decimal(r["gasto"]),
                                r["moneda"])
            except (ValueError, InvalidOperation):
                continue
            if desde <= g.fecha <= hasta and (campana is None or g.campana == campana):
                salida.append(g)
    return salida
