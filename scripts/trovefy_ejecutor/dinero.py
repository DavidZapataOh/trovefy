"""Dinero por cuenta (D-37): importes enteros en unidades mínimas de la moneda."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_OFFSETS = {1, 10, 100, 1000}

# Offset oficial de Meta por moneda (resolución 1). Fuente:
# https://developers.facebook.com/documentation/ads-commerce/marketing-api/currencies (leído 2026-11-12)
OFFSETS_OFICIALES: Mapping[str, int] = {"COP": 1, "USD": 100}


class MonedaNoConfigurada(Exception):
    def __init__(self, codigo: str):
        self.codigo = codigo
        super().__init__(f"moneda {codigo} sin offset confirmado (P-21): no se escriben importes")


@dataclass(frozen=True)
class Moneda:
    codigo: str
    offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.codigo, str) or not re.fullmatch(r"[A-Z]{3}", self.codigo):
            raise ValueError(f"codigo_moneda: {self.codigo!r} no es un código de 3 letras mayúsculas")
        if type(self.offset) is not int or self.offset not in _OFFSETS:
            raise ValueError(f"offset_moneda: {self.offset!r} no está en {sorted(_OFFSETS)}")


def moneda_configurada(codigo: str, offset: int | None) -> Moneda:
    if offset is None:
        raise MonedaNoConfigurada(codigo)
    return Moneda(codigo, offset)


def formatear(unidades: int, moneda: Moneda) -> str:
    decimales = len(str(moneda.offset)) - 1
    entero, resto = divmod(abs(unidades), moneda.offset)
    texto = f"{entero:,}".replace(",", ".")
    if decimales:
        texto += "," + str(resto).zfill(decimales)
    signo = "-" if unidades < 0 else ""
    return f"{signo}{texto} {moneda.codigo}"


def es_importe(valor: object) -> bool:
    return type(valor) is int and valor > 0
