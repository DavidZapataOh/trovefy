"""Modelo de datos de las propuestas (§5.2). Sin PyYAML (resolución 15)."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

Estado = Literal[
    "recibida", "enviada", "aceptada", "ejecutando", "ejecutada",
    "fallida", "discrepancia", "rechazada", "caducada", "obsoleta",
]
Clase = Literal["gasto", "no_gasto", "limite", "notificacion"]

TIPOS: frozenset[str] = frozenset({
    "activar", "pausar", "presupuesto", "puja", "spend_cap", "limite_cuenta", "lote", "agenda", "regla_meta",
    "crear_estructura_pausada", "limite_ejecutor", "alerta", "noop",
})

CLASE_POR_TIPO: Mapping[str, Clase] = MappingProxyType({
    **{t: "gasto" for t in ("activar", "pausar", "presupuesto", "puja", "spend_cap", "limite_cuenta",
                            "lote", "agenda", "regla_meta")},
    "crear_estructura_pausada": "no_gasto",
    "limite_ejecutor": "limite",
    "alerta": "notificacion",
    "noop": "notificacion",
})


def clase_de(tipo: str) -> Clase:
    try:
        return CLASE_POR_TIPO[tipo]
    except KeyError:
        raise ValueError(f"tipo desconocido: {tipo!r}") from None


def congelar(valor: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    return None if valor is None else MappingProxyType(copy.deepcopy(dict(valor)))


@dataclass(frozen=True)
class Operacion:
    entidad: str
    id: str
    campo: str
    de_esperado: int | str | None
    a: int | str | None
    unidad: str | None = None
    moneda: str | None = None
    parametros: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parametros", congelar(self.parametros))


@dataclass(frozen=True)
class Propuesta:
    version: int
    id: str
    tipo: str
    clase: Clase
    creada: datetime
    origen: str
    cuenta: str | None
    producto: str | None
    pais: str | None
    operaciones: tuple[Operacion, ...]
    motivo: str | None
    evidencia: Mapping[str, Any] | None
    reinicia_aprendizaje: bool
    prioridad: Literal["normal", "alta"]
    expira_en_min: int | None
    estructura: Any | None = None  # Estructura: Tarea 4
    alerta: Any | None = None  # Alerta: Tarea 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidencia", congelar(self.evidencia))
