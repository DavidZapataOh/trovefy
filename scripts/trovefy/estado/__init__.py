"""Máquina de estados del producto-país en la fase 3 (§4.13: «vive en ``scripts/trovefy/estado/``»).

Una sola tabla, `TRANSICIONES` (base común 2 y resolución 9 de la fase 3), con los cuatro pares de la fase:
``listo → montado`` y ``montado → test`` (plan 22, `/montar`) y ``test → muerto`` y ``test → candidato`` (plan 23,
`/leer`). La grafía es en minúsculas, como los estados de la fase 2. ``pre_escala``, ``variaciones``, ``agresiva``,
``portfolio``, ``freno`` y ``pausado`` son de la fase 4 y no están aquí.

La tabla es estática: quien quiera un par nuevo lo añade aquí (no hay registro en tiempo de ejecución). El único
ayudante que escribe el estado sigue siendo `trovefy.vault.producto.avanzar_estado`, que acepta estos pares además de
la cadena de la fase 2.
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

ESTADOS_FASE3: tuple[str, ...] = ("montado", "test", "muerto", "candidato")

TRANSICIONES: Mapping[str, frozenset[str]] = MappingProxyType({
    "listo": frozenset({"montado"}),        # /montar: el ejecutor confirma el montaje en PAUSED
    "montado": frozenset({"test"}),         # /montar: el usuario acepta «Activar» y el ejecutor lo confirma
    "test": frozenset({"muerto", "candidato"}),  # /leer (plan 23)
})


def permitida(desde: str, hacia: str) -> bool:
    """¿``desde → hacia`` está en la tabla de la fase 3?"""
    return hacia in TRANSICIONES.get(desde, frozenset())
