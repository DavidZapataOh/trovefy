"""Gasto de los tests leído del ledger (``ledger/gasto/*.csv``), en centavos de USD.

Formato provisional que adoptará ``/cierre`` (Fase 3): ``fecha,cuenta,campana,gasto,moneda``.
El importe usa punto como separador decimal y NUNCA agrupa miles. Un importe COP con exactamente
tres dígitos tras el punto («83.700») es ambiguo y queda «no medido», jamás se lee como 83,7.
Cada día se convierte con la TRM **vigente ese día**; sin ella, ese gasto es «no medido». Todo
redondeo es al alza: el gasto nunca baja de lo que dice el ledger."""

from __future__ import annotations

import csv
import functools
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

from trovefy.caja.config import ConfigCaja
from trovefy.trm import Trm, cop_a_usd_centavos

CABECERA = ["fecha", "cuenta", "campana", "gasto", "moneda"]
SIN_ASIGNAR = "sin-asignar"


class GastoCorrupto(ValueError):
    """Cabecera o columnas del ledger de gasto que no cuadran."""


@dataclass(frozen=True)
class GastoTest:
    producto: str
    pais: str
    usd_centavos: int | None
    motivo: str | None


def _fila_a_centavos(
    fila: list[str], trm_de: Callable[[date], Trm | None]
) -> tuple[int | None, str | None]:
    try:
        dia = date.fromisoformat(fila[0][:10])
        importe = Decimal(fila[3].strip())
        if not importe.is_finite() or importe < 0:
            raise InvalidOperation
    except (ValueError, InvalidOperation):
        return None, f"no medido: fila de gasto ilegible ({fila[0]!r}, {fila[3]!r})"
    moneda = fila[4].strip().upper()
    if moneda == "COP" and re.fullmatch(r"\d+\.\d{3}", fila[3].strip()):
        return None, "no medido: importe COP ambiguo (¿separador de miles?)"
    if moneda == "USD":
        return int((importe * 100).to_integral_value(rounding=ROUND_CEILING)), None
    if moneda != "COP":
        return None, f"no medido: moneda {moneda or '—'} sin conversión a USD"
    trm = trm_de(dia)
    if trm is None or not trm.vigente(dia):
        return None, f"no medido: sin TRM del {dia.isoformat()}"
    return cop_a_usd_centavos(importe, trm), None


def _sumar(
    partes: list[tuple[int | None, str | None]],
) -> tuple[int | None, str | None]:
    for c, m in partes:
        if c is None:
            return None, m
    return sum(c for c, _ in partes if c is not None), None


def gastos_de_tests(
    vault: Path, config: ConfigCaja, trm_de: Callable[[date], Trm | None]
) -> list[GastoTest]:
    por_campana: dict[str, list[tuple[int | None, str | None]]] = {}
    trm_de = functools.cache(trm_de)  # una consulta de TRM por día, no por fila
    carpeta = Path(vault) / "ledger" / "gasto"
    for ruta in sorted(carpeta.glob("*.csv")) if carpeta.is_dir() else []:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            filas = [r for r in csv.reader(f) if any(c.strip() for c in r)]
        if not filas:
            continue
        if filas[0] != CABECERA:
            raise GastoCorrupto(f"{ruta.name}: cabecera inesperada")
        for n, fila in enumerate(filas[1:], start=2):
            if len(fila) != len(CABECERA):
                raise GastoCorrupto(f"{ruta.name} línea {n}: {len(fila)} columnas")
            por_campana.setdefault(fila[2], []).append(_fila_a_centavos(fila, trm_de))
    salida: list[GastoTest] = []
    conocidas: set[str] = set()
    for t in config.tests:
        filas_t = por_campana.get(t.campana_id) if t.campana_id is not None else None
        if t.campana_id is not None:
            conocidas.add(t.campana_id)
        if not filas_t:
            motivo = (
                f"no medido: sin gasto registrado de {t.producto} {t.pais} "
                "(llega con /cierre, Fase 3)"
            )
            salida.append(GastoTest(t.producto, t.pais, None, motivo))
            continue
        c, m = _sumar(filas_t)
        salida.append(GastoTest(t.producto, t.pais, c, m))
    ajenas = [
        p for camp, ps in por_campana.items() if camp not in conocidas for p in ps
    ]
    if ajenas:
        c, m = _sumar(ajenas)
        salida.append(GastoTest(SIN_ASIGNAR, "—", c, m))
    return salida
