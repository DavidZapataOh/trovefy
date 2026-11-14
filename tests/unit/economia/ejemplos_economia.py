"""Reglas de la plantilla y mercados ficticios para los tests de economía."""

from decimal import Decimal

from trovefy.config.mercados import Mercado
from trovefy.economia.config import PLANTILLA, ConfigEconomia, cargar_texto
from trovefy.economia.modelo import Cifra
from trovefy.fx import Cambio


def config_plantilla() -> ConfigEconomia:
    return cargar_texto(PLANTILLA.read_text(encoding="utf-8"))


def reglas_plantilla():
    return config_plantilla().reglas


def reglas_escalera():
    return config_plantilla().escalera


def usd(importe: str) -> Cifra:
    return Cifra(Decimal(importe))


CAMBIO = Cambio({"EUR": 1.0, "USD": 1.08, "RON": 4.977}, "2026-11-12")
XE = Mercado("XE", "xx", "EUR", "Zona demo", (11.90, 15.90), None, "activo")
XR = Mercado("XR", "xr", "RON", "Zona demo", (11.90, 15.90), None, "activo")
XM = Mercado("XM", "xm", "MDL", "Zona demo", (11.90, 15.90), None, "activo")
XU = Mercado("XU", "xu", "USD", "Zona demo", (11.90, 15.90), None, "activo")
