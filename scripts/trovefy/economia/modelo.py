"""Tipos de la economía: cifras con su «no medido», costes de la ruta de cobro y tomas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Cifra:
    """Una cifra de dinero o ratio. ``valor=None`` exige ``motivo`` «no medido: …»."""

    valor: Decimal | None
    motivo: str | None = None

    def __post_init__(self) -> None:
        if self.valor is None and not (self.motivo or "").startswith("no medido: "):
            raise ValueError("una Cifra sin valor necesita un motivo «no medido: …»")
        if self.valor is not None and not isinstance(self.valor, Decimal):
            raise TypeError(f"una Cifra lleva Decimal, no {type(self.valor).__name__}")


@dataclass(frozen=True)
class Costes:
    """Lo que se lleva la ruta de cobro (suma de sus capas) y los reembolsos esperados."""

    comision_pct: Decimal
    comision_fija_usd: Decimal
    impuestos_pct: Decimal
    reembolsos_pct: Decimal


@dataclass(frozen=True)
class Tomas:
    """Proporción de compradores que toma cada paso (bump, U1 y downsell)."""

    bump: Decimal
    u1: Decimal
    downsell: Decimal
