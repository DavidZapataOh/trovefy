"""Registro de lo que hizo el ejecutor: histórico, ``PRODUCTO.md → paises.<PAIS>.trafico``, estados, caja y veto
(plan 22, Tareas 9 y 13).

**Qué hacen los vídeos:** Claude cierra con la lista de lo verificado («20 anuncios activos y aprobados… programados
para las 00:00», L1 1:14:15); los partes llevan los IDs (C1 0:54:20). Sin desvío.

Solo lee lo que el ejecutor copia al vault (``propuestas/P-*.md``, ``raw/telegram/motivos/``); nunca habla con Meta.
Es idempotente: se puede llamar en cada parte (``trovefy montar registrar --pendientes``, resolución 12).
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from trovefy.estado.montaje import tras_activar, tras_montaje
from trovefy.montar import SKILL
from trovefy.montar.tanda import bloque_pais
from trovefy.secretos import buscar_secreto
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import avanzar_estado, ruta_producto, sustituir_clave_pais

_ID = re.compile(r"P-\d{8}-\d{3}")
TERMINALES = ("ejecutada", "fallida", "discrepancia", "rechazada", "caducada", "obsoleta")


@dataclass(frozen=True)
class ResultadoEjecutor:
    id: str
    tipo: str | None
    estado: str
    parcial: bool
    fecha: str | None
    detalle: str
    ids: dict = field(default_factory=dict)
    cuerpo: str = ""


def _valor(texto: str):
    try:
        v = ast.literal_eval(texto)
    except (ValueError, SyntaxError):
        return texto
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, dict):
        return {str(k): str(x) if isinstance(x, int) else x for k, x in v.items()}
    return v


def leer_resultado(vault: Path, id_: str) -> ResultadoEjecutor | None:
    """Lo que copió el ejecutor en ``propuestas/<id>.md``; ``None`` si aún no está."""
    if not isinstance(id_, str) or not _ID.fullmatch(id_):
        return None
    ruta = Path(vault) / "propuestas" / f"{id_}.md"
    try:
        meta, cuerpo = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get("estado"), str):
        return None
    detalle, ids, en_ids = "", {}, False
    for ln in cuerpo.splitlines():
        if ln.startswith("Detalle: "):
            detalle = ln[len("Detalle: "):]
        elif ln.strip() == "ids_creados:":
            en_ids = True
        elif en_ids and ln.startswith("- ") and ": " in ln:
            k, v = ln[2:].split(": ", 1)
            ids[k.strip()] = _valor(v.strip())
        elif en_ids and ln.strip():
            en_ids = False
    fecha = meta.get("fecha")
    return ResultadoEjecutor(id_, meta.get("tipo_propuesta"), meta["estado"], meta.get("parcial") is True,
                             str(fecha) if fecha is not None else None, detalle, ids, cuerpo)


def buscar_activar(vault: Path, montaje: str, excluir: set[str] | None = None) -> ResultadoEjecutor | None:
    """El ``activar`` que el ejecutor generó para ``montaje`` (su motivo cita el id del montaje), el más reciente."""
    carpeta = Path(vault) / "propuestas"
    candidatos = []
    for ruta in sorted(carpeta.glob("P-*.md")) if carpeta.is_dir() else ():
        if excluir and ruta.stem in excluir:
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
        except OSError:
            continue
        if montaje not in texto or "tipo_propuesta: activar" not in texto:
            continue
        r = leer_resultado(vault, ruta.stem)
        if r is not None and r.tipo == "activar" and r.id != montaje:
            candidatos.append(r)
    return candidatos[-1] if candidatos else None


def _fin4(x: object) -> str:
    return "…" + str(x)[-4:]


def _escribir(vault: Path, ruta: Path, meta: dict, cuerpo: str) -> None:
    texto = frontmatter.renderizar(meta, cuerpo)
    if buscar_secreto(texto):
        raise ValueError(f"{ruta.name}: aparece algo con forma de secreto; no se escribe")
    escribir_atomico(ruta, texto)


def _carpeta(vault: Path, p_id: str, pais: str) -> Path:
    return ruta_producto(vault, p_id).parent / "trafico" / pais


def leer_montaje_json(vault: Path, p_id: str, pais: str, tanda: str) -> dict:
    ruta = _carpeta(vault, p_id, pais) / f"MONTAJE-{tanda}.json"
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _historico(vault: Path, p_id: str, pais: str, r: ResultadoEjecutor, m: dict, trafico: dict,
               ahora: datetime) -> str:
    est = m.get("estructura") or {}
    imp = m.get("importes") or {}
    campana = r.ids.get("campana")
    nombre = f"historico-{campana}.md" if campana else f"historico-{r.id}.md"
    ruta = _carpeta(vault, p_id, pais) / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    piezas = {p["nombre"]: p for p in m.get("piezas") or []}
    vistas = r.ids.get("vistas_previas") or {}
    meta = {"tipo": "historico-trafico", "producto": p_id, "pais": pais, "fecha": ahora.date().isoformat(),
            "fuente": f"propuestas/{r.id}.md", "cuenta": _fin4(est.get("cuenta", "")), "campana": campana,
            "montaje": r.id, "estado_montaje": r.estado, "tanda": m.get("tanda")}
    lineas = [f"# Histórico de tráfico · {p_id} · {pais} · {est.get('campana', {}).get('nombre', '')}", "",
              f"- Montaje: [[propuestas/{r.id}]] ({r.estado}{', parcial' if r.parcial else ''})",
              f"- Validación: [[propuestas/{trafico.get('validacion')}]]" if trafico.get("validacion") else "",
              f"- Auditoría del día: [[ledger/auditoria/{ahora.astimezone(ZONA_NEGOCIO).date().isoformat()}.jsonl]]",
              f"- Cuenta: {_fin4(est.get('cuenta', ''))} ({imp.get('moneda', '—')})",
              f"- Campaña: {campana or 'no creada'}",
              (f"- Importes: {imp.get('conjuntos')} × {imp.get('diario_conjunto')} {imp.get('moneda')}/día "
               f"(US$ {imp.get('usd_diario')} c/u) · techo {imp.get('spend_cap')} {imp.get('moneda')} "
               f"(US$ {imp.get('usd_spend_cap')}) · TRM {imp.get('trm', '—')} ({imp.get('trm_fecha', '—')})"),
              f"- Relectura del ejecutor: {r.detalle or '—'}", "", "## Conjuntos y anuncios", ""]
    for nombre_ad, sid in (r.ids.get("conjuntos") or {}).items():
        p = piezas.get(nombre_ad, {})
        lineas.append(f"- {nombre_ad} · conjunto {sid} · anuncio {(r.ids.get('anuncios') or {}).get(nombre_ad, '—')}"
                      f" · {p.get('angulo', '—')} · {p.get('tipo', '—')} · {p.get('ruta', '—')}"
                      f" · vista previa: {vistas.get(nombre_ad) or 'no medido'}")
    lineas += ["", "## Registro", ""]
    previo = ruta.read_text(encoding="utf-8").split("## Registro", 1)[1].strip().splitlines() if ruta.is_file() \
        else []
    lineas += [x for x in previo if x.strip()]
    _escribir(vault, ruta, meta, "\n".join(x for x in lineas if x is not None) + "\n")
    return ruta.relative_to(ruta_producto(vault, p_id).parent).as_posix()


def _anotar_historico(vault: Path, p_id: str, trafico: dict, linea: str, ahora: datetime) -> None:
    rel = trafico.get("historico")
    if not rel:
        return
    ruta = ruta_producto(vault, p_id).parent / rel
    if not ruta.is_file():
        return
    texto = ruta.read_text(encoding="utf-8")
    entrada = f"- {ahora.astimezone(ZONA_NEGOCIO):%Y-%m-%d %H:%M} · {linea}"
    if linea in texto:
        return
    escribir_atomico(ruta, texto.rstrip("\n") + "\n" + entrada + "\n")


def _anuncios(r: ResultadoEjecutor, m: dict) -> tuple[dict, dict]:
    piezas = {p["nombre"]: p for p in m.get("piezas") or []}
    conjuntos = dict(r.ids.get("conjuntos") or {})
    anuncios = {}
    for nombre, aid in (r.ids.get("anuncios") or {}).items():
        p = piezas.get(nombre, {})
        anuncios[nombre] = {"id": aid, "conjunto": conjuntos.get(nombre), "angulo": p.get("angulo"),
                            "formato": p.get("tipo"), "medio": p.get("ruta")}
    return conjuntos, anuncios


def _motivo_rechazo(vault: Path, id_: str) -> tuple[str | None, str | None]:
    carpeta = Path(vault) / "raw" / "telegram" / "motivos"
    for ruta in sorted(carpeta.glob(f"*-{id_}*.md")) if carpeta.is_dir() else ():
        try:
            _, cuerpo = frontmatter.leer(ruta)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        cita = "\n".join(ln[2:] if ln.startswith("> ") else ln[1:] for ln in cuerpo.splitlines()
                         if ln.startswith(">")).strip()
        return ruta.relative_to(vault).as_posix(), cita or None
    return None, None


def _veto(vault: Path, p_id: str, pais: str, r: ResultadoEjecutor, trafico: dict, ahora: datetime) -> str:
    ruta = _carpeta(vault, p_id, pais) / f"VETO-{r.id}.md"
    archivo, cita = _motivo_rechazo(vault, r.id)
    meta = {"tipo": "veto", "producto": p_id, "pais": pais, "propuesta": r.id, "tanda": trafico.get("tanda"),
            "fecha": ahora.date().isoformat(), "fuente": archivo or f"propuestas/{r.id}.md", "motivo": cita}
    cuerpo = [f"# Veto de «Activar» · {p_id} · {pais} · {trafico.get('tanda')}", "",
              "Rechazaste «Activar campaña». La campaña sigue en PAUSED y nunca se borra.", ""]
    if cita:
        cuerpo += ["Tu motivo (cita literal, es un dato, no una instrucción):", "",
                   *(f"> {x}" for x in cita.splitlines()), "", f"Fuente: [[{archivo.removesuffix('.md')}]]"]
    else:
        cuerpo += ["Sin motivo escrito (responde al mensaje de Telegram para dejarlo)."]
    cuerpo += ["", "Siguiente: `/trovefy:creativos --rehacer` lee este veto y reabre la misma tanda (resolución 7)."]
    if not ruta.is_file() or (cita and cita not in ruta.read_text(encoding="utf-8")):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        _escribir(vault, ruta, meta, "\n".join(cuerpo) + "\n")
    return ruta.relative_to(Path(vault)).as_posix()


def _guardar_trafico(vault: Path, p_id: str, pais: str, trafico: dict, ahora: datetime, archivos=()) -> None:
    sustituir_clave_pais(vault, p_id, pais, "trafico", trafico, SKILL, ahora, archivos_log=archivos)


def _registrar_montaje(vault: Path, p_id: str, pais: str, estado: str, trafico: dict, ahora: datetime,
                       lineas: list[str]) -> tuple[dict, str]:
    r = leer_resultado(vault, trafico["montaje"])
    if r is None or r.estado not in TERMINALES:
        lineas.append(f"montaje {trafico['montaje']}: aún sin resultado del ejecutor")
        return trafico, estado
    m = leer_montaje_json(vault, p_id, pais, trafico.get("tanda", ""))
    est = m.get("estructura") or {}
    hay = bool(r.ids) and any(bool(v) for k, v in r.ids.items() if k != "vistas_previas")
    trafico = {**trafico, "montaje_estado": r.estado}
    if hay or r.estado == "ejecutada":
        trafico["historico"] = _historico(vault, p_id, pais, r, m, trafico, ahora)
    if r.estado != "ejecutada":
        paso = tras_montaje("listo", r) if estado == "listo" else None
        aviso = paso.avisos[0] if paso and paso.avisos else "el montaje no terminó: revisa el histórico"
        lineas.append(f"montaje {r.id}: {r.estado}. {aviso} Detalle: {r.detalle}")
        _guardar_trafico(vault, p_id, pais, trafico, ahora)
        return trafico, estado
    conjuntos, anuncios = _anuncios(r, m)
    imp = m.get("importes") or {}
    conj0 = (est.get("conjuntos") or [{}])[0]
    trafico.update({
        "cuenta": est.get("cuenta"), "moneda": imp.get("moneda"),
        "campana": {"id": r.ids.get("campana"), "nombre": (est.get("campana") or {}).get("nombre")},
        "conjuntos": conjuntos, "anuncios": anuncios,
        "spend_cap": {"minima": imp.get("spend_cap"), "usd": imp.get("usd_spend_cap"), "trm": imp.get("trm"),
                      "trm_fecha": imp.get("trm_fecha")},
        "plazo": {"dias": m.get("plazo_dias", 7), "fuente": "C1 0:18:10 «Plazo 1 semana»"},
        "diario_conjunto": {"minima": imp.get("diario_conjunto"), "usd": imp.get("usd_diario")},
        "montado": r.fecha or ahora.isoformat(timespec="seconds"), "activado": None,
        "inicio": conj0.get("inicio"), "renovaciones": trafico.get("renovaciones") or [],
    })
    _guardar_trafico(vault, p_id, pais, trafico, ahora)
    if estado == "listo":
        paso = tras_montaje(estado, r)
        avanzar_estado(vault, p_id, pais, "listo", paso.nuevo, f"propuestas/{r.id}.md", SKILL, ahora)
        estado = paso.nuevo
    lineas.append(f"montaje {r.id}: ejecutado; campaña {_fin4(r.ids.get('campana'))} con {len(conjuntos)} conjuntos "
                  f"en PAUSED. Estado: {estado}. Histórico: {trafico['historico']}")
    return trafico, estado


def _registrar_activar(vault: Path, p_id: str, pais: str, estado: str, trafico: dict, ahora: datetime,
                       lineas: list[str]) -> tuple[dict, str]:
    r = leer_resultado(vault, trafico["activar"]) if trafico.get("activar") else buscar_activar(
        vault, trafico["montaje"])
    if r is None or r.estado not in TERMINALES:
        lineas.append("«Activar campaña» sigue esperando tu toque en Telegram (caduca en 24 h)")
        return trafico, estado
    trafico = {**trafico, "activar": r.id, "activar_estado": r.estado}
    if estado != "montado":
        _guardar_trafico(vault, p_id, pais, trafico, ahora)
        return trafico, estado
    paso = tras_activar(estado, r)
    if paso.nuevo == "test":
        trafico["activado"] = r.fecha or ahora.isoformat(timespec="seconds")
        _guardar_trafico(vault, p_id, pais, trafico, ahora)
        avanzar_estado(vault, p_id, pais, "montado", "test", f"propuestas/{r.id}.md", SKILL, ahora)
        from trovefy.caja.tests import abrir_test

        n = len(trafico.get("conjuntos") or {})
        usd = Decimal(str((trafico.get("diario_conjunto") or {}).get("usd") or "5")) * n
        abrir_test(vault, p_id, pais, str(trafico["campana"]["id"]), usd)
        _anotar_historico(vault, p_id, trafico, f"activada con tu Aceptar ({r.id})", ahora)
        lineas.append(f"activar {r.id}: ejecutada. Estado: test. Test vivo en config/caja.yaml (US$ {usd}/día).")
        return trafico, "test"
    if paso.veto:
        veto = _veto(vault, p_id, pais, r, trafico, ahora)
        trafico["veto"] = veto
        _guardar_trafico(vault, p_id, pais, trafico, ahora, [veto])
        _anotar_historico(vault, p_id, trafico, f"«Activar» rechazado ({r.id}): {veto}", ahora)
        lineas.append(f"activar {r.id}: rechazada. {paso.avisos[0]} Veto: {veto}")
        return trafico, estado
    _guardar_trafico(vault, p_id, pais, trafico, ahora)
    lineas.append(f"activar {r.id}: {r.estado}. {paso.avisos[0] if paso.avisos else ''}".strip())
    return trafico, estado


def _registrar_renovaciones(vault: Path, p_id: str, pais: str, trafico: dict, ahora: datetime,
                            lineas: list[str]) -> dict:
    renov = [dict(x) for x in trafico.get("renovaciones") or [] if isinstance(x, dict)]
    cambio = False
    for x in renov:
        if not x.get("montaje") or x.get("activado"):
            continue
        if not x.get("conjuntos"):
            r = leer_resultado(vault, x["montaje"])
            if r is None or r.estado not in TERMINALES:
                lineas.append(f"renovación {x.get('tanda')}: montaje {x['montaje']} sin resultado aún")
                continue
            x["montaje_estado"] = r.estado
            cambio = True
            if r.estado != "ejecutada":
                lineas.append(f"renovación {x.get('tanda')}: montaje {r.estado}. Detalle: {r.detalle}")
                continue
            m = leer_montaje_json(vault, p_id, pais, x.get("tanda", ""))
            x["conjuntos"], x["anuncios"] = _anuncios(r, m)
            lineas.append(f"renovación {x.get('tanda')}: {len(x['conjuntos'])} conjuntos nuevos en PAUSED en la misma "
                          "ABO; falta tu Aceptar en Telegram")
        a = leer_resultado(vault, x["activar"]) if x.get("activar") else buscar_activar(vault, x["montaje"])
        if a is None or a.estado not in TERMINALES:
            continue
        x["activar"], x["activar_estado"] = a.id, a.estado
        cambio = True
        if a.estado == "ejecutada":
            x["activado"] = a.fecha or ahora.isoformat(timespec="seconds")
            trafico = {**trafico, "conjuntos": {**(trafico.get("conjuntos") or {}), **x["conjuntos"]},
                       "anuncios": {**(trafico.get("anuncios") or {}), **x["anuncios"]}}
            from trovefy.caja.config import cargar_caja
            from trovefy.caja.tests import actualizar_test

            cid = str((trafico.get("campana") or {}).get("id"))
            t = next((t for t in cargar_caja(vault).tests if t.campana_id == cid), None)
            if t is not None:
                usd = Decimal(t.presupuesto_diario) / 100 + Decimal(5) * len(x["conjuntos"])
                actualizar_test(vault, cid, diario_usd=usd)
            _anotar_historico(vault, p_id, trafico, f"renovación {x.get('tanda')} activada ({a.id})", ahora)
            lineas.append(f"renovación {x.get('tanda')}: activada ({a.id}); {len(x['conjuntos'])} conjuntos más")
        else:
            lineas.append(f"renovación {x.get('tanda')}: activar {a.estado}")
    if cambio:
        trafico = {**trafico, "renovaciones": renov}
        _guardar_trafico(vault, p_id, pais, trafico, ahora)
    return trafico


def registrar(vault: Path, p_id: str, pais: str, ahora: datetime) -> list[str]:
    """Recoge lo que haya copiado el ejecutor. Idempotente. Devuelve las líneas para el usuario."""
    vault = Path(vault)
    bloque = bloque_pais(vault, p_id, pais)
    trafico = dict(bloque.get("trafico")) if isinstance(bloque.get("trafico"), dict) else {}
    estado = bloque.get("estado")
    lineas: list[str] = []
    if not trafico.get("montaje"):
        return [f"{p_id} {pais}: sin montaje depositado"]
    if not (trafico.get("campana") or {}).get("id") and trafico.get("montaje_estado") not in (
            "fallida", "discrepancia"):
        trafico, estado = _registrar_montaje(vault, p_id, pais, estado, trafico, ahora, lineas)
    elif trafico.get("montaje_estado") in ("fallida", "discrepancia"):
        lineas.append(f"montaje {trafico['montaje']}: {trafico['montaje_estado']}; no se vuelve a montar sin tu "
                      "palabra (mira el histórico)")
    if (trafico.get("campana") or {}).get("id") and not trafico.get("activado") \
            and trafico.get("activar_estado") not in ("rechazada",):
        trafico, estado = _registrar_activar(vault, p_id, pais, estado, trafico, ahora, lineas)
    elif trafico.get("activar_estado") == "rechazada":
        lineas.append(f"«Activar» rechazado ({trafico.get('activar')}); veto en {trafico.get('veto')}")
    if trafico.get("renovaciones"):
        trafico = _registrar_renovaciones(vault, p_id, pais, trafico, ahora, lineas)
    if trafico.get("activado"):
        lineas.append(f"Test vivo desde {trafico['activado']} (salida {trafico.get('inicio')}).")
    if any("ejecutad" in x or "rechazad" in x for x in lineas):
        anadir_log(vault, SKILL, f"{p_id} {pais}: registro ({estado})", [], ahora=ahora)
    return [f"{p_id} {pais}: {x}" for x in lineas]


def pendientes(vault: Path) -> list[tuple[str, str]]:
    """Productos-país con un montaje, un «Activar» o una renovación sin cerrar."""
    salida = []
    for ruta in sorted((Path(vault) / "productos").glob("*/PRODUCTO.md")):
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        for pais, b in ((meta or {}).get("paises") or {}).items():
            t = b.get("trafico") if isinstance(b, dict) else None
            if not isinstance(t, dict) or not t.get("montaje"):
                continue
            abierto = (not (t.get("campana") or {}).get("id") and t.get("montaje_estado") not in ("fallida",
                                                                                                    "discrepancia"))
            abierto = abierto or (bool((t.get("campana") or {}).get("id")) and not t.get("activado")
                                  and t.get("activar_estado") not in ("rechazada", "caducada"))
            abierto = abierto or any(isinstance(x, dict) and x.get("montaje") and not x.get("activado")
                                     and x.get("montaje_estado") not in ("fallida", "discrepancia")
                                     and x.get("activar_estado") not in ("rechazada", "caducada")
                                     for x in t.get("renovaciones") or [])
            if abierto:
                salida.append((ruta.parent.name, pais))
    return salida
