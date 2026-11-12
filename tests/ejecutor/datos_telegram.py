"""Dicts con la forma de §5.2 para los tests de Telegram. Cuenta ficticia act_0000000000000000 (resolución 17)."""
from __future__ import annotations

import copy

CUENTA = "act_0000000000000000"
ADSET = "120210000000000"


def presupuesto_cop(**c):
    d = {"version": 1, "id": "P-20261112-004", "creada": "2026-11-12T14:05:00-05:00", "origen": "/leer --intradia",
         "producto": "p-0001-herramientas", "pais": "BG", "cuenta": CUENTA, "tipo": "presupuesto",
         "operaciones": [{"entidad": "adset", "id": ADSET, "campo": "daily_budget",
                          "de_esperado": 20000, "a": 26000, "unidad": "minima", "moneda": "COP"}],
         "motivo": "ROAS neto acum. 2,6 (3 días cerrados)", "evidencia": {}, "reinicia_aprendizaje": False,
         "prioridad": "normal", "expira_en_min": 45}
    d.update(copy.deepcopy(c))
    return d


def noop(**c):
    d = {"version": 1, "id": "P-20261112-001", "tipo": "noop", "creada": "2026-11-12T14:05:00-05:00",
         "origen": "/probar", "motivo": "Prueba de extremo a extremo", "prioridad": "normal", "expira_en_min": 30}
    d.update(copy.deepcopy(c))
    return d


def alerta(**c):
    d = {"version": 1, "id": "P-20261112-010", "tipo": "alerta", "creada": "2026-11-12T09:10:00-05:00",
         "origen": "/vigia", "nivel": "aviso", "titulo": "Saldo APIMart bajo",
         "texto": "Quedan 0,80 USD (tope de tanda 1,00)."}
    d.update(copy.deepcopy(c))
    return d


def id_conjunto(i: int) -> str:
    return f"1202100000{i:05d}"


def lote(n, **c):
    ops = [{"entidad": "adset", "id": id_conjunto(i), "campo": "daily_budget", "de_esperado": 30000,
            "a": 20000, "unidad": "minima", "moneda": "COP"} for i in range(1, n + 1)]
    return presupuesto_cop(id="P-20261112-007", tipo="lote", operaciones=ops, **c)


def limite_ejecutor(**c):
    d = presupuesto_cop(id="P-20261112-006", tipo="limite_ejecutor", origen="/limites",
                        operaciones=[{"entidad": "ejecutor", "id": CUENTA, "campo": "tope_gasto_diario_total",
                                      "de_esperado": 165000, "a": 150000, "unidad": "minima", "moneda": "COP"}])
    d.pop("producto"); d.pop("pais")
    d.update(copy.deepcopy(c))
    return d
