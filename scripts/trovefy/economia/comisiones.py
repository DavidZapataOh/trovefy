"""Comisiones de la ruta de cobro activa, para el ROAS neto de `/leer` y el neto de `/cierre` (resolución 15).

**Qué hacen los vídeos:** «ROAS neto = lo que entra a tu cuenta después de comisiones ÷ lo que gastaste» (T3 10:05);
el bot da el «Neto Whop» (T3 13:42). Una sola función de comisiones en el código: esta. No inventa nada: lo que esté en
``null`` en ``config/economia.yaml`` sale en la lista de lo que falta por fijar (lo fija el usuario, paso 0 de la fase).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trovefy.economia.config import ConfigEconomia

_CAMPOS = ("comision_pct", "comision_fija_usd", "impuestos_pct")


@dataclass(frozen=True)
class Comisiones:
    ruta: str
    pct: Decimal
    fija_usd: Decimal
    impuestos_pct: Decimal
    fuentes: tuple[str, ...]  # las plataformas de la ruta (claves de config/economia.yaml)


def comisiones(config: ConfigEconomia) -> Comisiones | list[str]:
    """Suma de las plataformas de la ruta activa; si falta algo, la lista de lo que falta («falta ruta_activa»…).
    Un 0 fijado es un valor, no un faltante."""
    if config.ruta_activa is None:
        return ["falta ruta_activa"]
    faltan: list[str] = []
    total = dict.fromkeys(_CAMPOS, Decimal(0))
    plataformas = config.rutas.get(config.ruta_activa, ())
    for nombre in plataformas:
        p = config.plataformas.get(nombre)
        for campo in _CAMPOS:
            v = getattr(p, campo) if p is not None else None
            if v is None:
                faltan.append(f"falta plataformas.{nombre}.{campo}")
            else:
                total[campo] += v
    if faltan:
        return faltan
    return Comisiones(config.ruta_activa, total["comision_pct"], total["comision_fija_usd"], total["impuestos_pct"],
                      tuple(f"plataformas.{n}" for n in plataformas))
