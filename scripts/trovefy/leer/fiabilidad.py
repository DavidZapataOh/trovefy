"""Fiabilidad del dato (alta / media / baja) y si cuentan los pagos iniciados del píxel (plan 23, Tarea 5).

**Qué hacen los vídeos:** se decide con ventas reales, no con el píxel (E2, «Turbo»); «cuatro días sin ventas porque no
tenía el pixel conectado» (L2 19:45). Añadido (no cambia el método): la fiabilidad **no bloquea** los cortes por gasto
(el gasto de Meta es fiable); va en el parte y en el motivo de cada propuesta, para que el usuario decida con ella.

Desvío D1: mientras el dataset no haya confirmado InitiateCheckout (excepción del 18-nov), los pagos iniciados por
anuncio del píxel no apagan solos. En cuanto Meta registre un IC real, la rama vuelve sola.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trovefy.leer import Umbrales, umbral
from trovefy.leer.modelo import LecturaOferta

IC_NO_FIABLE = ("el píxel no ha confirmado InitiateCheckout (excepción del 18-nov): los pagos iniciados por anuncio "
                "no cuentan para apagar (desvío D1)")


@dataclass(frozen=True)
class Fiabilidad:
    nivel: Literal["alta", "media", "baja"]
    pi_fiable: bool
    motivos: tuple[str, ...]


def ic_verificado(tracking: dict | None) -> bool:
    """``TRACKING.md`` con InitiateCheckout contado (> 0) en ``eventos``."""
    eventos = (tracking or {}).get("eventos")
    n = eventos.get("InitiateCheckout") if isinstance(eventos, dict) else None
    return type(n) is int and n > 0


def evaluar(o: LecturaOferta, tracking: dict | None, ledger_dia: dict | None, u: Umbrales,
            zona_cuenta: str = "America/Bogota") -> Fiabilidad:
    motivos: list[str] = []
    baja = False
    media = False
    if o.ventas_tienda is None:
        baja = True
        motivos.append("ventas de la tienda no medidas: solo píxel")
    if o.gasto_usd_c is None:
        baja = True
        motivos.append("gasto en USD no medido (sin TRM o sin Meta)")
    if o.ventas_tienda is not None and o.ventas_pixel is not None:
        dif = abs(o.ventas_tienda - o.ventas_pixel)
        if dif > 1:
            baja = True
            motivos.append(f"píxel {o.ventas_pixel} y tienda {o.ventas_tienda}: difieren en más de 1")
        elif dif == 1:
            media = True
            motivos.append(f"píxel {o.ventas_pixel} y tienda {o.ventas_tienda}: difieren en 1")
    if o.intradia:
        media = True
        motivos.append("día en curso (intradía)")
    if o.zona_tienda and o.zona_tienda != zona_cuenta:
        media = True
        motivos.append(f"la tienda cuenta el día en {o.zona_tienda} y la cuenta en {zona_cuenta}")
    clics = o.clics
    minimo = int(umbral(u, "diagnostico.clics_min"))
    if clics is None or clics < minimo:
        media = True
        motivos.append(f"{clics if clics is not None else '—'} clics acumulados (< {minimo})")
    if ledger_dia and type(ledger_dia.get("ventas")) is int and o.ventas_dia is not None \
            and ledger_dia["ventas"] != o.ventas_dia:
        media = True
        motivos.append(f"el cierre registró {ledger_dia['ventas']} ventas ese día y la tienda dice {o.ventas_dia}")
    pi_fiable = ic_verificado(tracking) or bool(o.pi_pixel)
    if not pi_fiable:
        motivos.append(IC_NO_FIABLE)
    nivel = "baja" if baja else ("media" if media else "alta")
    return Fiabilidad(nivel, pi_fiable, tuple(motivos))
