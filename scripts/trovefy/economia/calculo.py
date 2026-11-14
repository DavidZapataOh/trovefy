"""Economía de la oferta en funciones puras (§4.6, §7): AOV, cobros, BE, CPA y ROAS de equilibrio.

Todo en ``Decimal`` y en USD. Se calcula a precisión completa y solo se cuantiza al construir cada
``Cifra``: AOV, BE y CPA a la baja al céntimo (conservador); ROAS de equilibrio al alza a 2 decimales.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_UP, Decimal

from trovefy.economia.config import ReglasEconomia
from trovefy.economia.modelo import Cifra, Costes, Tomas

AVISO_BE_BAJO = "precio bajo = BE chico = ningún anuncio es rentable"
_CENTIMO = Decimal("0.01")
_SIN_NETO = "no medido: el neto por pedido no es positivo: ningún CPA es rentable"
PASOS_ECONOMIA = ("front", "bump", "u1", "downsell")


def _abajo(x: Decimal) -> Decimal:
    return x.quantize(_CENTIMO, rounding=ROUND_FLOOR)


def aov(front: Decimal, bump: Decimal | None, u1: Decimal | None, downsell: Decimal | None,
        tomas: Tomas) -> Decimal:
    """Valor medio del pedido: ``front + bump·t_bump + u1·t_u1 + down·(1−t_u1)·t_down``.

    ``None`` = paso apagado (no suma). Sin U1 activo el downsell no existe y cuenta 0.
    """
    total = front
    if bump is not None:
        total += bump * tomas.bump
    if u1 is not None:
        total += u1 * tomas.u1
        if downsell is not None:
            total += downsell * (1 - tomas.u1) * tomas.downsell
    return total


def cobros_esperados(tomas: Tomas, u1_activo: bool, down_activo: bool) -> Decimal:
    """Cobros por pedido: ``1 + t_u1 + (1−t_u1)·t_down`` (el bump va en el mismo cobro que el front)."""
    cobros = Decimal(1)
    if u1_activo:
        cobros += tomas.u1
        if down_activo:
            cobros += (1 - tomas.u1) * tomas.downsell
    return cobros


def neto_por_pedido(aov: Decimal, cobros: Decimal, costes: Costes) -> Decimal:
    """El BE (CPA de equilibrio): ``aov·(1 − comisión − impuestos − reembolsos) − fija·cobros``."""
    parte = 1 - costes.comision_pct - costes.impuestos_pct - costes.reembolsos_pct
    return aov * parte - costes.comision_fija_usd * cobros


def cpa_objetivo(be: Decimal, factor: Decimal) -> Decimal:
    """``factor × BE``, a la baja al céntimo."""
    return _abajo(be * factor)


def roas_equilibrio(aov: Decimal, be: Decimal) -> Cifra:
    """``AOV ÷ neto por pedido``, al alza a 2 decimales; sin neto positivo, «no medido»."""
    if be <= 0:
        return Cifra(None, _SIN_NETO)
    return Cifra((aov / be).quantize(_CENTIMO, rounding=ROUND_UP))


@dataclass(frozen=True)
class Economia:
    aov_usd: Cifra
    be_usd: Cifra
    cpa_test_usd: Cifra
    cpa_escala_usd: Cifra
    roas_be: Cifra
    cobros: Decimal | None
    avisos: tuple[str, ...]


def _texto(x: Decimal) -> str:
    """Importe para el usuario: coma decimal; sin decimales si es entero."""
    if x == x.to_integral_value():
        return str(x.to_integral_value())
    return f"{_abajo(x):.2f}".replace(".", ",")


def _no_medida(motivo: str, aov_usd: Cifra | None = None, cobros: Decimal | None = None,
               avisos: tuple[str, ...] = ()) -> Economia:
    nm = Cifra(None, motivo)
    return Economia(aov_usd or nm, nm, nm, nm, nm, cobros, avisos)


def _aviso_aov(total: Decimal, aov_usd: Cifra, reglas: ReglasEconomia) -> list[str]:
    """El aviso de AOV bajo: depende solo del AOV, no de los costes."""
    if total < reglas.aov_objetivo_usd:
        aviso = (f"AOV estimado {_texto(aov_usd.valor)} USD: lejos del objetivo de "
                 f"{_texto(reglas.aov_objetivo_usd)} USD (aspiracional)")
        return [aviso]
    return []


def economia_de(precios_usd: dict[str, Cifra | None], costes: Costes | Cifra, tomas: Tomas,
                reglas: ReglasEconomia) -> Economia:
    """La economía de una escalera con precios en USD (claves ``front``, ``bump``, ``u1``, ``downsell``).

    ``None`` = paso apagado; una ``Cifra`` sin valor = no medido y su motivo pasa a las cinco cifras.
    Con los costes no medidos, el AOV sí sale (no depende de ellos) y BE, CPA y ROAS llevan el motivo;
    el aviso de AOV bajo sale igual (solo depende del AOV) y el de BE bajo solo con el BE medido.
    """
    front = precios_usd.get("front")
    if front is None:
        raise ValueError("la escalera necesita el precio del front")
    precios: dict[str, Decimal | None] = {}
    for paso in PASOS_ECONOMIA:
        cifra = precios_usd.get(paso)
        if cifra is not None and cifra.valor is None:
            return _no_medida(cifra.motivo)
        precios[paso] = None if cifra is None else cifra.valor

    total = aov(precios["front"], precios["bump"], precios["u1"], precios["downsell"], tomas)
    cobros = cobros_esperados(tomas, precios["u1"] is not None, precios["downsell"] is not None)
    aov_usd = Cifra(_abajo(total))
    if isinstance(costes, Cifra):
        return _no_medida(costes.motivo, aov_usd, cobros, tuple(_aviso_aov(total, aov_usd, reglas)))

    be = neto_por_pedido(total, cobros, costes)
    avisos: list[str] = []
    if be < reglas.be_minimo_usd:
        avisos.append(AVISO_BE_BAJO)
    avisos += _aviso_aov(total, aov_usd, reglas)
    if be <= 0:
        sin = Cifra(None, _SIN_NETO)
        return Economia(aov_usd, Cifra(_abajo(be)), sin, sin, sin, cobros, tuple(avisos))
    return Economia(
        aov_usd=aov_usd,
        be_usd=Cifra(_abajo(be)),
        cpa_test_usd=Cifra(cpa_objetivo(be, reglas.cpa_test_factor)),
        cpa_escala_usd=Cifra(cpa_objetivo(be, reglas.cpa_escala_factor)),
        roas_be=roas_equilibrio(total, be),
        cobros=cobros,
        avisos=tuple(avisos),
    )
