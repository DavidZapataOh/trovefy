"""Surf intradía y vuelta a la base como funciones puras (plan 23, Tarea 3b; R-010), en la fase 3.

**Qué hacen los vídeos:** «si tiene más de ROAS de dos, lo vas a duplicar… cada 2 horas» (S1 10:27); «solo con ventas
nuevas: si mantiene el ROAS pero no vendió desde la última revisión, no se toca · Nunca queda pausada» (T3 12:35);
«1.75 −50 %… 11 p.m. poner todo [a la base]» (S2 14:10, S2 14:40); en ABO, por conjunto (T3 11:22); «el ABO G1R va a
3,04 y no se toca» (L2 21:25). Sin desvío. Cada cambio es una propuesta que el usuario acepta por Telegram.

Importes en unidades mínimas de la moneda de la cuenta (la base sale de lo que montó el 22, ya a la baja con la TRM).
Un ×2 que choca con un límite del ejecutor o con el techo de la campaña no se recorta en silencio: no se propone y la
nota lo dice (se sube el límite con una propuesta ``limite_ejecutor``, plan 22, R2).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from trovefy.leer import Umbrales, num, umbral
from trovefy.leer.economia import EconomiaLeer, neto_de, roas_neto
from trovefy.leer.modelo import LecturaConjunto


@dataclass(frozen=True)
class Surf:
    conjunto_id: str
    nombre: str
    de_minima: int
    a_minima: int
    motivo: str
    regla: str
    ventas_hoy: int | None = None


@dataclass(frozen=True)
class Limites:
    """Lo que el ejecutor deja cambiar (``estado/limites.json``); ``None`` = sin límite conocido."""

    max_presupuesto_conjunto: int | None = None
    paso_max_pct: int | None = None


def roas_hoy(c: LecturaConjunto, e: EconomiaLeer) -> Decimal | None:
    if c.hoy is None:
        return None
    return roas_neto(neto_de(c.hoy.bruto_usd, c.hoy.ventas, e), c.hoy.gasto_usd_c)


def veredicto_surf(c: LecturaConjunto, ventas_previas: int, e: EconomiaLeer, u: Umbrales, base: int | None,
                   *, limites: Limites | None = None, spend_cap: int | None = None) -> tuple[Surf | None, str | None]:
    """(propuesta o ``None``, nota para el parte). ``ventas_previas`` = ventas de hoy vistas en la ronda anterior."""
    limites = limites or Limites()
    if (c.estado_meta or "").upper() != "ACTIVE":
        return None, None
    if c.presupuesto is None:
        return None, f"{c.nombre}: surf no medido: sin presupuesto vivo de Meta"
    if c.hoy is None or c.hoy.ventas is None or c.hoy.gasto_usd_c is None:
        return None, f"{c.nombre}: surf no medido: sin la lectura de hoy (gasto o ventas)"
    if not e.medida:
        return None, f"{c.nombre}: surf no medido: {e.motivo}"
    roas = roas_hoy(c, e)
    if roas is None:
        return None, None if not c.hoy.gasto_usd_c else f"{c.nombre}: surf no medido: sin ROAS neto de hoy"
    subir, bajar = umbral(u, "surf.roas_subir"), umbral(u, "surf.roas_bajar")
    if roas >= subir:
        if c.hoy.ventas <= ventas_previas:
            return None, (f"{c.nombre}: ROAS {num(roas)} hoy pero sin ventas nuevas desde la ronda anterior: no se "
                          "toca (T3 12:35)")
        factor = umbral(u, "surf.factor_subir")
        a = int((Decimal(c.presupuesto) * factor).to_integral_value(rounding=ROUND_FLOOR))
        if limites.max_presupuesto_conjunto is not None and a > limites.max_presupuesto_conjunto:
            return None, (f"{c.nombre}: tocaría ×{num(factor, 0)} ({c.presupuesto} → {a}), pero supera "
                          f"max_presupuesto_conjunto del ejecutor ({limites.max_presupuesto_conjunto}): propón subirlo "
                          "con limite_ejecutor (no se recorta en silencio)")
        if limites.paso_max_pct is not None and a * 100 > c.presupuesto * (100 + limites.paso_max_pct):
            return None, (f"{c.nombre}: tocaría ×{num(factor, 0)}, pero el ejecutor solo deja subir un "
                          f"{limites.paso_max_pct} % por paso (paso_max_pct): propón subirlo a 100 con limite_ejecutor")
        if spend_cap is not None and a > spend_cap:
            return None, f"{c.nombre}: ×{num(factor, 0)} pasaría el techo de la campaña: no se sube (C1 0:18:10)"
        nuevas = c.hoy.ventas - ventas_previas
        return Surf(c.adset_id, c.nombre, c.presupuesto, a,
                    f"ROAS {num(roas)} hoy y {nuevas} venta{'s' if nuevas != 1 else ''} nueva{'s' if nuevas != 1 else ''}"
                    f": ×{num(factor, 0)}", "S1 10:27, T3 12:35", c.hoy.ventas), None
    if roas <= bajar and c.hoy.gasto_usd_c > 0 and base is not None and c.presupuesto > base:
        factor = umbral(u, "surf.factor_bajar")
        a = max(base, int((Decimal(c.presupuesto) * factor).to_integral_value(rounding=ROUND_FLOOR)))
        return Surf(c.adset_id, c.nombre, c.presupuesto, a, f"ROAS {num(roas)} hoy ≤ {num(bajar)}: −50 %",
                    "S2 14:10", c.hoy.ventas), None
    return None, None


def vuelta_a_la_base(conjuntos: tuple[LecturaConjunto, ...] | list[LecturaConjunto], base: int | None) -> list[Surf]:
    """A las 23:00 del país, cada conjunto activo con presupuesto distinto de la base vuelve a ella (S2 14:40)."""
    if base is None:
        return []
    return [Surf(c.adset_id, c.nombre, c.presupuesto, base, "vuelta a la base de las 23:00", "S2 14:40, S1 10:00")
            for c in conjuntos
            if (c.estado_meta or "").upper() == "ACTIVE" and c.presupuesto is not None and c.presupuesto != base]


def es_hora_de_base(hora_local: int, u: Umbrales) -> bool:
    return hora_local == int(umbral(u, "surf.base_hora"))
