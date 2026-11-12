"""Fábricas de propuestas para las pruebas del ejecutor contra el Graph falso (plan 11).

Construyen ``Propuesta`` directamente (sin pasar por el esquema) para poder usar los ids cortos
del ``mundo_basico`` (``s1``, ``c1``...). Cuenta ficticia en COP (resolución 17).
"""
from __future__ import annotations

from datetime import UTC, datetime

from ejecutor.fabricas import presupuesto as presupuesto_dict
from trovefy_ejecutor.modelo import Operacion, Propuesta, clase_de

CUENTA = "act_0000000000000000"
# Propuesta por defecto como dict válido para ``cargar_propuesta`` (ids numéricos).
PROPUESTA_BASE: dict = presupuesto_dict()
_IMPORTES = ("daily_budget", "lifetime_budget", "bid_amount", "spend_cap")


def operacion(**cambios) -> Operacion:
    base = {"entidad": "adset", "id": "s1", "campo": "daily_budget", "de_esperado": 20000, "a": 26000,
            "unidad": "minima", "moneda": "COP"}
    base.update(cambios)
    if base["campo"] not in _IMPORTES:  # estados: sin unidad ni moneda
        base["unidad"] = base["moneda"] = None
    return Operacion(**base)


def propuesta(**cambios) -> Propuesta:
    """``op={...}`` mezcla claves en la operación por defecto; ``ops=[...]`` (dicts) la sustituye."""
    op = cambios.pop("op", {})
    ops = cambios.pop("ops", None)
    operaciones = tuple(operacion(**o) for o in ops) if ops is not None else (operacion(**op),)
    base = {"version": 1, "id": "P-20261112-004", "tipo": "presupuesto", "creada": datetime(2026, 11, 12, 19, 5, tzinfo=UTC),
            "origen": "/leer --intradia", "cuenta": CUENTA, "producto": "p-0001-hotmart-i107039122g", "pais": "BG",
            "motivo": "prueba", "evidencia": None, "reinicia_aprendizaje": False, "prioridad": "normal",
            "expira_en_min": 45}
    base.update(cambios)
    base.setdefault("clase", clase_de(base["tipo"]))
    return Propuesta(operaciones=operaciones, **base)
