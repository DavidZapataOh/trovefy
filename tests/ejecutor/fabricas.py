"""Fábricas de propuestas como dict (Tarea 3). Cuenta ficticia en COP (resolución 17)."""
from __future__ import annotations

import copy

CUENTA = "act_0000000000000000"
ADSET = "120245000000000101"


def operacion(**cambios) -> dict:
    base = {"entidad": "adset", "id": ADSET, "campo": "daily_budget", "de_esperado": 20000, "a": 26000,
            "unidad": "minima", "moneda": "COP"}
    base.update(cambios)
    return base


def presupuesto(**cambios) -> dict:
    base = {"version": 1, "id": "P-20261112-004", "tipo": "presupuesto", "creada": "2026-11-12T14:05:00-05:00",
            "origen": "/leer --intradia", "producto": "p-0001-hotmart-i107039122g", "pais": "BG", "cuenta": CUENTA,
            "operaciones": [operacion()],
            "motivo": "ROAS neto acum. 2,6 (3 días cerrados); 2 ventas nuevas desde 12:00",
            "evidencia": {"ventana": "2026-11-09..2026-11-11", "ventas": 6, "fiabilidad": "alta"},
            "reinicia_aprendizaje": False, "prioridad": "normal", "expira_en_min": 45}
    base.update(copy.deepcopy(cambios))
    return base


def pausar(**cambios) -> dict:
    base = presupuesto(id="P-20261112-005", tipo="pausar", motivo="ROAS por debajo del mínimo 3 días",
                       operaciones=[{"entidad": "adset", "id": ADSET, "campo": "status",
                                     "de_esperado": "ACTIVE", "a": "PAUSED"}])
    base.update(copy.deepcopy(cambios))
    return base
