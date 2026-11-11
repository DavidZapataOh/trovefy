"""Precio soportable por país: qué tan dentro de la banda en EUR del mercado cae el precio."""

from __future__ import annotations

from trovify.caza.senales import Medida
from trovify.config.mercados import Mercado


def precio_soportable(precio_eur: Medida, banda: tuple[float, float]) -> Medida:
    if precio_eur.valor is None:
        return precio_eur
    bajo, alto = banda
    p = precio_eur.valor
    if bajo <= p <= alto:
        return Medida(1.0)
    distancia = bajo - p if p < bajo else p - alto
    ancho = alto - bajo
    if ancho <= 0:
        return Medida(0.0)
    return Medida(round(max(0.0, 1 - distancia / ancho), 9))


def precio_local(precio_eur: float, mercado: Mercado, tasas: dict[str, float] | None) -> Medida:
    """El precio en EUR llevado a la moneda del país (para mostrarlo en el informe)."""
    if mercado.moneda == "EUR":
        return Medida(precio_eur)
    if tasas is None or mercado.moneda not in tasas:
        return Medida(None, f"no medido: sin cambio de referencia para {mercado.moneda}")
    return Medida(precio_eur * tasas[mercado.moneda])
