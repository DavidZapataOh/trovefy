"""Propuestas del buzón y memoria de lo ya propuesto (plan 23, Tarea 7; §5.2, §5.5, D-32).

**Qué hacen los vídeos:** «Claude propone con ID y monto» y «los presupuestos los toca el humano» (C1, documento
CEREBRO); el admin monta en pausa y la prende el dueño (C1 51:00); la ronda «qué apagar y qué prender» se propone con
IDs (L2 22:40). En Trovefy nada se ejecuta sin el Aceptar del usuario ([U], D-32): cambia quién pulsa, no el método.

Funciones puras que construyen el JSON de cada propuesta (lo valida ``trovefy_ejecutor.esquema`` al depositar) y la
memoria ``trafico/<PAIS>/propuestas-leer.json``: una propuesta pendiente no se repite y una caducada o rechazada no se
reenvía sin un cambio material (una venta nueva o US$ 3 más de gasto; en el surf, una venta nueva o otro presupuesto).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from trovefy.leer.fiabilidad import Fiabilidad
from trovefy.leer.modelo import Corte, LecturaOferta
from trovefy.leer.surf import Surf

MOTIVO_MAX = 300
TERMINALES = ("ejecutada", "fallida", "discrepancia", "rechazada", "caducada", "obsoleta")
GASTO_MATERIAL_C = 300  # D-32: US$ 3 más de gasto desde la última propuesta igual (= el corte de anuncio, C1 20:05)


def _motivo(texto: str, f: Fiabilidad | None) -> str:
    sufijo = f" · fiabilidad {f.nivel}" if f is not None else ""
    if len(texto) + len(sufijo) > MOTIVO_MAX:
        texto = texto[: MOTIVO_MAX - len(sufijo) - 1].rstrip() + "…"
    return texto + sufijo


def _evidencia(o: LecturaOferta, f: Fiabilidad | None, extra: dict | None = None) -> dict:
    ventana = f"{o.activacion.date().isoformat() if o.activacion else '—'}..{o.dia.isoformat()}"
    return {"ventana": ventana, "gasto_usd_c": o.gasto_usd_c, "ventas_tienda": o.ventas_tienda,
            "fiabilidad": f.nivel if f else None, **(extra or {})}


def a_propuesta(corte: Corte, o: LecturaOferta, f: Fiabilidad | None, cuenta: str, origen: str) -> dict:
    """``pausar_conjuntos`` → ``pausar`` (1) o ``lote`` (≥ 2); ``pausar_campana`` → ``pausar`` de la campaña."""
    if corte.tipo == "pausar_campana":
        ops = [{"entidad": "campaign", "id": corte.ids[0], "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}]
        tipo, expira = "pausar", 360
    else:
        ops = [{"entidad": "adset", "id": i, "campo": "status", "de_esperado": "ACTIVE", "a": "PAUSED"}
               for i in corte.ids]
        tipo, expira = ("pausar" if len(ops) == 1 else "lote"), 360
    return {"tipo": tipo, "origen": origen, "cuenta": cuenta, "producto": o.producto, "pais": o.pais,
            "operaciones": ops, "motivo": _motivo(corte.motivo, f), "prioridad": corte.prioridad,
            "expira_en_min": expira, "reinicia_aprendizaje": False,
            "evidencia": _evidencia(o, f, {"corte": corte.tipo, **corte.evidencia})}


def surf_a_propuesta(cambios: list[Surf], o: LecturaOferta, f: Fiabilidad | None, cuenta: str, origen: str,
                     *, base: bool = False) -> dict:
    """``presupuesto`` (1 conjunto) o ``lote`` (≥ 2) en unidades mínimas de la moneda de la cuenta."""
    moneda = o.moneda or "COP"
    ops = [{"entidad": "adset", "id": s.conjunto_id, "campo": "daily_budget", "de_esperado": s.de_minima,
            "a": s.a_minima, "unidad": "minima", "moneda": moneda} for s in cambios]
    if base:
        texto = f"Vuelta a la base de las 23:00 del país: {len(cambios)} conjunto(s) a {cambios[0].a_minima} {moneda} " \
                "(S2 14:40)"
    else:
        texto = " · ".join(f"{s.nombre}: {s.motivo}, de {s.de_minima} a {s.a_minima} {moneda} ({s.regla})"
                           for s in cambios)
    reinicia = any(abs(s.a_minima - s.de_minima) * 5 > s.de_minima for s in cambios)  # > 20 %
    return {"tipo": "presupuesto" if len(ops) == 1 else "lote", "origen": origen, "cuenta": cuenta,
            "producto": o.producto, "pais": o.pais, "operaciones": ops, "motivo": _motivo(texto, f),
            "prioridad": "normal", "expira_en_min": 60 if base else 120, "reinicia_aprendizaje": reinicia,
            "evidencia": _evidencia(o, f, {"surf": {s.conjunto_id: s.regla for s in cambios}})}


def alerta(titulo: str, texto: str, nivel: str, origen: str) -> dict:
    return {"tipo": "alerta", "origen": origen, "nivel": nivel, "titulo": titulo[:120], "texto": texto[:3000],
            "prioridad": "normal"}


# --- memoria ------------------------------------------------------------------------------------------------------


def clave(tipo: str, ids: tuple[str, ...] | list[str]) -> str:
    return f"{tipo}|{','.join(sorted(ids))}"


def ruta_memoria(vault: Path, p_id: str, pais: str) -> Path:
    from trovefy.vault.producto import ruta_producto

    return ruta_producto(vault, p_id).parent / "trafico" / pais / "propuestas-leer.json"


def cargar_memoria(vault: Path, p_id: str, pais: str) -> dict:
    try:
        datos = json.loads(ruta_memoria(vault, p_id, pais).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    if not isinstance(datos, dict):
        datos = {}
    datos.setdefault("propuestas", {})
    datos.setdefault("surf", {})
    return datos


def guardar_memoria(vault: Path, p_id: str, pais: str, memoria: dict) -> Path:
    from trovefy.vault.escritura import escribir_atomico

    ruta = ruta_memoria(vault, p_id, pais)
    escribir_atomico(ruta, json.dumps(memoria, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return ruta


def cambio_material(previa: dict, nueva: dict) -> bool:
    """Una venta nueva, US$ 3 más de gasto, otro presupuesto u otro día (alertas)."""
    if (nueva.get("ventas") or 0) > (previa.get("ventas") or 0):
        return True
    g0, g1 = previa.get("gasto_usd_c"), nueva.get("gasto_usd_c")
    if isinstance(g0, int) and isinstance(g1, int) and g1 - g0 >= GASTO_MATERIAL_C:
        return True
    return any(previa.get(k) != nueva.get(k) for k in ("presupuesto", "dia") if k in nueva or k in previa)


def debe_proponer(k: str, huella: dict, memoria: dict, estado_de: Callable[[str], str | None],
                  ahora: datetime) -> bool:
    """No si está pendiente; no si ya se ejecutó una pausa; no si caducó o se rechazó sin cambio material (D-32)."""
    previa = memoria.get("propuestas", {}).get(k)
    if previa is None:
        return True
    if k.startswith("alerta|"):
        return cambio_material(previa.get("huella") or {}, huella)
    est = estado_de(previa.get("id", ""))
    if est is None:
        try:
            creada = datetime.fromisoformat(previa.get("fecha"))
        except (TypeError, ValueError):
            return True
        vence = creada + timedelta(minutes=int(previa.get("expira_en_min") or 1440) + 60)
        if ahora < vence:
            return False  # pendiente: el usuario aún no la ha visto o el ejecutor no la ha copiado
        est = "caducada"
    if est == "ejecutada" and k.startswith("pausar"):
        return False
    return cambio_material(previa.get("huella") or {}, huella)


def anotar(memoria: dict, k: str, id_: str, tipo: str, huella: dict, ahora: datetime, expira: int | None,
           extra: dict | None = None) -> None:
    memoria.setdefault("propuestas", {})[k] = {"id": id_, "tipo": tipo, "huella": huella,
                                               "fecha": ahora.isoformat(timespec="seconds"),
                                               "expira_en_min": expira, **({"extra": extra} if extra else {})}
