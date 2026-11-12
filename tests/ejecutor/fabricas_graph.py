"""Fábricas de propuestas para las pruebas del ejecutor contra el Graph falso (plan 11).

Construyen ``Propuesta`` directamente (sin pasar por el esquema) para poder usar los ids cortos
del ``mundo_basico`` (``s1``, ``c1``...). Cuenta ficticia en COP (resolución 17).
"""
from __future__ import annotations

from datetime import UTC, datetime

from ejecutor.fabricas import presupuesto as presupuesto_dict
from trovefy_ejecutor.modelo import (
    Anuncio,
    Campana,
    Conjunto,
    Estructura,
    Medio,
    Operacion,
    Propuesta,
    clase_de,
)

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


# -- crear_estructura_pausada (Tarea 6) ----------------------------------------------------------
# Vault de prueba: ``entorno_montaje`` escribe estos bytes en estas rutas dentro de ``tmp_path``.
BYTES_IMG = b"\xff\xd8\xff imagen de prueba"
BYTES_VID = b"\x00\x00\x00\x18ftypmp42 video de prueba"
RUTA_IMG = "productos/p-0001/creativos/RO/t1/img01.jpg"
RUTA_VID = "productos/p-0001/creativos/RO/t1/vid01.mp4"
PAGINA = "1357661930771909"
DATASET = "8877665544"


def _sha(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


def medio(**cambios) -> Medio:
    base = {"ref": "img01", "ruta": RUTA_IMG, "sha256": _sha(BYTES_IMG)}
    base.update(cambios)
    return Medio(**base)


def medio_video(**cambios) -> Medio:
    return medio(**{"ref": "vid01", "ruta": RUTA_VID, "sha256": _sha(BYTES_VID), **cambios})


def anuncio(**cambios) -> Anuncio:
    base = {"nombre": "AD01 img", "medio": "img01", "texto": "Texto del anuncio", "titulo": "Titulo",
            "descripcion": "Descripcion", "cta": "LEARN_MORE", "url": "https://ejemplo.test/ro?utm_source=fb"}
    base.update(cambios)
    return Anuncio(**base)


def conjunto(**cambios) -> Conjunto:
    """Claves que el modelo no tiene (p. ej. ``status``) se ignoran: el montaje no las lee."""
    cambios.pop("status", None)
    base = {"nombre": "01 RO", "daily_budget": 20000, "paises": ("RO",), "idiomas": ("ro",), "evento": "PURCHASE",
            "ubicaciones_excluidas": (),
            "anuncios": (anuncio(), anuncio(nombre="AD02 vid", medio="vid01"))}
    base.update(cambios)
    for k in ("paises", "idiomas", "ubicaciones_excluidas", "anuncios"):
        base[k] = tuple(base[k])
    return Conjunto(**base)


def estructura(**cambios) -> Propuesta:
    """Propuesta ``crear_estructura_pausada`` (modelo, sin esquema: permite formas que el esquema
    rechazaría para probar la segunda barrera). ``campana={...}`` mezcla claves (``status`` se ignora)."""
    camp = {"nombre": "PRUEBA RO | ABO", "objetivo": "OUTCOME_SALES", "tipo_presupuesto": "ABO", "spend_cap": 120000,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "daily_budget": None}
    camp.update({k: v for k, v in cambios.pop("campana", {}).items() if k != "status"})
    est = {"pagina_id": PAGINA, "dataset_id": DATASET, "medios": (medio(), medio_video()),
           "campana": Campana(**camp), "conjuntos": (conjunto(),), "unidad": "minima", "moneda": "COP",
           "solo_validar": False}
    for k in list(cambios):
        if k in est:
            est[k] = cambios.pop(k)
    est["medios"] = tuple(est["medios"])
    est["conjuntos"] = tuple(est["conjuntos"])
    base = {"version": 1, "id": "P-20261112-002", "tipo": "crear_estructura_pausada", "clase": "no_gasto",
            "creada": datetime(2026, 11, 12, 14, 10, tzinfo=UTC), "origen": "/vigia", "cuenta": CUENTA,
            "producto": "p-0001", "pais": "RO", "operaciones": (), "motivo": None, "evidencia": None,
            "reinicia_aprendizaje": False, "prioridad": "normal", "expira_en_min": None}
    base.update(cambios)
    return Propuesta(**base, estructura=Estructura(**est))
