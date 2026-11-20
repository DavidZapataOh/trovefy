"""Criterio de salida de la fase 3: «el primer test corre y, durante 3 días, cada escritura queda en la auditoría con su
Aceptar».

**Qué hacen los vídeos:** el bot vuelve a mirar la campaña tras cada cambio (T3 13:20); «Claude propone con ID y monto, y
ejecuta el dueño» (C1 0:38:30); el admin monta en pausa y la prende el dueño (C1 51:00). En Trovefy el dueño ejecuta con
su Aceptar en Telegram. **Añadido (no cambia el método):** se cruza con el registro de actividad de la cuenta en Meta
(``ads_account_get_activity_logs``, solo lectura) para ver escrituras hechas fuera de Trovefy.

Pura sobre lo leído: la copia de la auditoría (``ledger/auditoria/*.jsonl``, encadenada por hash), los espejos
``propuestas/<id>.md``, las páginas de cierre y la respuesta guardada del registro de actividad.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from trovefy.vault.escritura import ZONA_NEGOCIO, escribir_atomico

VENTANA = timedelta(hours=72)
MARGEN_META = timedelta(minutes=15)
TIPOS_GASTO = frozenset({"activar", "pausar", "presupuesto", "puja", "spend_cap", "limite_cuenta", "lote", "agenda",
                         "regla_meta", "limite_ejecutor"})
SIN_META = frozenset({"alerta", "noop"})
ESTRUCTURA = "crear_estructura_pausada"
_LISTAS = ("data", "activities", "activity_logs", "events", "eventos", "results", "items")
_ACTOR_META = ("meta", "facebook", "sistema", "system")
_ID = re.compile(r"\b\d{10,20}\b")


@dataclass(frozen=True)
class Veredicto:
    pasa: bool
    ventana: tuple[datetime, datetime] | None
    escrituras: list[dict] = field(default_factory=list)
    sin_aceptar: list[str] = field(default_factory=list)
    dias_sin_cierre: list[str] = field(default_factory=list)
    fuera_de_trovefy: list[dict] = field(default_factory=list)
    de_meta: list[dict] = field(default_factory=list)
    motivos: list[str] = field(default_factory=list)


def _ts(v: object) -> datetime | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return datetime.fromtimestamp(v, ZONA_NEGOCIO)
    if not isinstance(v, str):
        return None
    try:
        f = datetime.fromisoformat(v.replace("Z", "+00:00") if v.endswith("Z") else v)
    except ValueError:
        return None
    return f if f.tzinfo else None


def _espejo(vault: Path, id_: str) -> str:
    ruta = Path(vault) / "propuestas" / f"{id_}.md"
    try:
        return ruta.read_text(encoding="utf-8") if ruta.is_file() and not ruta.is_symlink() else ""
    except (OSError, UnicodeDecodeError):
        return ""


def _eventos_actividad(actividad: object) -> list[dict] | None:
    datos = actividad
    for _ in range(4):
        if isinstance(datos, list):
            break
        if not isinstance(datos, dict):
            return None
        if isinstance(datos.get("structuredContent"), (dict, list)):
            datos = datos["structuredContent"]
            continue
        siguiente = next((datos[k] for k in _LISTAS if k in datos), None)
        if siguiente is None:
            return None
        datos = siguiente
    if not isinstance(datos, list):
        return None
    eventos = []
    for e in datos:
        if not isinstance(e, dict):
            return None
        t = _ts(e.get("event_time") or e.get("time") or e.get("timestamp") or e.get("fecha"))
        if t is None:
            return None
        objeto = e.get("object_id") or e.get("objeto_id") or e.get("object")
        actor = str(e.get("actor_name") or e.get("actor") or "")
        eventos.append({"hora": t, "objeto": str(objeto) if objeto is not None else "", "actor": actor,
                        "tipo": str(e.get("translated_event_type") or e.get("event_type") or ""),
                        "nombre": str(e.get("object_name") or "")})
    return eventos


def _es_de_meta(e: dict) -> bool:
    actor = e["actor"].strip().lower()
    return (not actor or actor in _ACTOR_META) or "límite de gasto" in e["tipo"].lower() or \
        "spend limit" in e["tipo"].lower()


def _casa(e: dict, w: dict) -> bool:
    """Un evento de Meta casa con una escritura de la auditoría por id de objeto o, si a uno le falta el id, por hora
    (±15 min)."""
    if e["objeto"] and e["objeto"] in w["ids"]:
        return True
    cerca = abs(datetime.fromisoformat(w["hora"]) - e["hora"]) <= MARGEN_META
    return cerca and (not e["objeto"] or not w["ids"])


def comprobar(vault: Path, ahora: datetime, actividad: dict | None, desde: date | None = None) -> Veredicto:
    from trovefy.aprobaciones.listado import tramos_de_auditoria
    from trovefy.cierre.salida import leer_cierre

    tramos, error = tramos_de_auditoria(vault)
    if error:
        return Veredicto(False, None, motivos=[error])
    lineas = [ln for t in tramos for ln in t.lineas]
    ejec = [ln for ln in lineas if ln.get("evento") == "ejecucion" and isinstance(ln.get("datos"), dict)]
    activaciones = [ln for ln in ejec if ln["datos"].get("tipo") == "activar" and ln["datos"].get("ok") is True
                    and ln["datos"].get("validate_only") is False and _ts(ln.get("ts"))
                    and (desde is None or _ts(ln["ts"]).astimezone(ZONA_NEGOCIO).date() >= desde)]
    if not activaciones:
        return Veredicto(False, None, motivos=[("el test aún no se activó: no hay una ejecución «activar» real en la "
                                               "auditoría")])
    ini = _ts(activaciones[0]["ts"])
    fin = ini + VENTANA
    motivos: list[str] = []
    if ahora < fin:
        horas = int((fin - ahora).total_seconds() // 3600) + 1
        motivos.append(f"faltan {horas} h para las 72 h desde la activación")
    dentro = lambda t: t is not None and ini <= t <= fin

    for t in tramos:
        horas_t = [_ts(ln.get("ts")) for ln in t.lineas]
        toca = any(dentro(h) for h in horas_t)
        if toca and not t.cuadra:
            motivos.append("la cadena de la auditoría no cuadra dentro de la ventana")
        if t.detalle.startswith("no medido") and horas_t and horas_t[0] is not None and horas_t[0] <= fin:
            motivos.append(f"auditoría: {t.detalle}")

    transiciones = [ln["datos"] for ln in lineas if ln.get("evento") == "transicion" and isinstance(ln.get("datos"),
                                                                                                    dict)]
    aceptar = {d.get("id"): d.get("callback_id") for d in transiciones
               if d.get("de") == "enviada" and d.get("a") == "aceptada" and d.get("callback_id")}
    escrituras: list[dict] = []
    sin_aceptar: list[str] = []
    for ln in ejec:
        d, hora = ln["datos"], _ts(ln.get("ts"))
        if d.get("validate_only") is not False or not dentro(hora) or d.get("tipo") in SIN_META:
            continue
        id_, tipo = str(d.get("id")), str(d.get("tipo"))
        espejo = _espejo(vault, id_)
        if tipo == ESTRUCTURA:
            bien = d.get("ok") is True and ("PAUSED" in str(d.get("detalle")) or "PAUSED" in espejo)
            cb = "sin botones (en PAUSED)"
        else:
            cb = aceptar.get(id_)
            bien = cb is not None
        if not bien:
            sin_aceptar.append(id_)
        ids = set(_ID.findall(str(d.get("detalle")))) | set(_ID.findall(espejo))
        escrituras.append({"id": id_, "tipo": tipo, "hora": hora.isoformat(timespec="minutes"), "ok": d.get("ok"),
                           "aceptar": (cb[:8] + "…") if isinstance(cb, str) and tipo != ESTRUCTURA else cb,
                           "con_aceptar": bien, "ids": sorted(ids)})
    if sin_aceptar:
        motivos.append(f"{len(sin_aceptar)} escritura(s) sin su Aceptar: {', '.join(sin_aceptar)}")

    dias = []
    d0, d1 = ini.astimezone(ZONA_NEGOCIO).date(), min(fin, ahora).astimezone(ZONA_NEGOCIO).date()
    while d0 <= d1:
        dias.append(d0)
        d0 += timedelta(days=1)
    sin_cierre = []
    for dia in dias:
        pagina = leer_cierre(vault, dia)
        momentos = (pagina[0].get("momentos") or {}) if pagina else {}
        if not pagina or not any(isinstance(m, dict) and m.get("alerta_id") for m in momentos.values()):
            sin_cierre.append(dia.isoformat())
    if sin_cierre:
        motivos.append(f"días sin cierre depositado: {', '.join(sin_cierre)}")

    fuera, de_meta = [], []
    if actividad is None:
        motivos.append("no medido: falta el registro de actividad de Meta (ads_account_get_activity_logs)")
    else:
        eventos = _eventos_actividad(actividad)
        if eventos is None:
            motivos.append("no medido: forma del registro de actividad de Meta desconocida")
        else:
            for e in (x for x in eventos if dentro(x["hora"])):
                casa = any(_casa(e, w) for w in escrituras)
                fila = {"hora": e["hora"].isoformat(timespec="minutes"), "objeto": e["objeto"], "tipo": e["tipo"],
                        "actor": e["actor"]}
                if casa:
                    continue
                (de_meta if _es_de_meta(e) else fuera).append(fila)
            if fuera:
                motivos.append(f"{len(fuera)} cambio(s) en Meta fuera de Trovefy")
    return Veredicto(not motivos, (ini, fin), escrituras, sin_aceptar, sin_cierre, fuera, de_meta, motivos)


def escribir_criterio(vault: Path, v: Veredicto, ahora: datetime) -> Path:
    from trovefy.aprobaciones.fuentes import enmascarar_cuentas

    ruta = Path(vault) / "wiki" / "analisis" / "fase-3-criterio.md"
    ventana = (f"{v.ventana[0]:%Y-%m-%d %H:%M} → {v.ventana[1]:%Y-%m-%d %H:%M}" if v.ventana else "—")
    filas = "\n".join(f"| {w['id']} | {w['tipo']} | {w['hora']} | {'sí' if w['con_aceptar'] else 'no'} "
                      f"({w['aceptar'] or '—'}) | {'ok' if w['ok'] else 'falló'} |" for w in v.escrituras) or "| — |"
    meta = "\n".join(f"- {e['hora']} · {e['tipo']} · objeto …{e['objeto'][-4:]} · {e['actor'] or '—'}"
                     for e in v.fuera_de_trovefy) or "- ninguno"
    propios = "\n".join(f"- {e['hora']} · {e['tipo']} (lo hizo Meta: no cuenta)" for e in v.de_meta) or "- ninguno"
    texto = (f"---\ntipo: criterio\nfase: 3\nfecha: {ahora.isoformat(timespec='seconds')}\n"
             f"pasa: {'true' if v.pasa else 'false'}\n---\n\n# Criterio de salida de la fase 3\n\n"
             f"«El primer test corre y, durante 3 días, cada escritura queda en la auditoría con su Aceptar».\n\n"
             f"**Veredicto: {'PASA' if v.pasa else 'NO PASA'}** · ventana {ventana}\n\n"
             + ("".join(f"- {m}\n" for m in v.motivos) + "\n" if v.motivos else "")
             + "## Escrituras\n\n| id | tipo | hora | Aceptar | resultado |\n|---|---|---|---|---|\n" + filas + "\n\n"
             + "## Días y cierres\n\n" + (f"Sin cierre: {', '.join(v.dias_sin_cierre)}\n\n" if v.dias_sin_cierre
                                          else "Todos los días tienen su cierre.\n\n")
             + "## Cambios en Meta fuera de Trovefy\n\n" + meta + "\n\n## Cambios que hizo Meta\n\n" + propios + "\n")
    escribir_atomico(ruta, enmascarar_cuentas(texto))
    return ruta
