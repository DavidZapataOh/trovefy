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


def estructura(**cambios) -> dict:
    base = {"version": 1, "id": "P-20261112-002", "tipo": "crear_estructura_pausada",
            "creada": "2026-11-12T09:10:00-05:00", "origen": "/montar", "producto": "p-0001-hotmart-i107039122g",
            "pais": "BG", "cuenta": CUENTA, "pagina_id": "1357661930771909", "dataset_id": "8877665544",
            "medios": [{"ref": "img01", "ruta": "productos/p-0001-hotmart-i107039122g/creativos/BG/t1/AD01.jpg",
                        "sha256": "a" * 64},
                       {"ref": "vid01", "ruta": "productos/p-0001-hotmart-i107039122g/creativos/BG/t1/AD09.mp4",
                        "sha256": "b" * 64}],
            "campana": {"nombre": "SOMATIKA BG | G1 | ABO | 12-11-26", "objetivo": "OUTCOME_SALES",
                        "tipo_presupuesto": "ABO", "spend_cap": 120000, "bid_strategy": "LOWEST_COST_WITHOUT_CAP"},
            "conjuntos": [{"nombre": "01 IMG G1", "daily_budget": 20000, "paises": ["BG"], "idiomas": ["bg"],
                           "evento": "PURCHASE", "ubicaciones_excluidas": ["audience_network", "threads"],
                           "anuncios": [{"nombre": "AD01 G1 mapa", "medio": "img01", "texto": "Texto del anuncio",
                                         "titulo": "Titulo", "descripcion": "Descripcion", "cta": "LEARN_MORE",
                                         "url": "https://somatikalab.com/bg?utm_source=fb"}]}],
            "unidad": "minima", "moneda": "COP"}
    base.update(copy.deepcopy(cambios))
    return base


def alerta(**cambios) -> dict:
    base = {"version": 1, "id": "P-20261112-010", "tipo": "alerta", "creada": "2026-11-12T09:10:00-05:00",
            "origen": "/vigia", "nivel": "aviso", "titulo": "Saldo APIMart bajo",
            "texto": "Quedan 0,80 USD (tope de tanda 1,00)."}
    base.update(copy.deepcopy(cambios))
    return base
