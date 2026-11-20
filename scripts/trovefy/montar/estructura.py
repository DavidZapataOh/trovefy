"""La estructura del test, sus nombres, su huella y el resumen en seco (plan 22, Tareas 3 y 13).

**Qué hacen los vídeos:** objetivo Ventas, «Maximize number of conversions», compra del píxel de esa tienda, ubicación =
país e idioma = idioma local (L2 0:19:35; L1 0:56:23); sin edad ni intereses, y el sexo del público si el avatar es de
uno solo (L2 0:19:35, «Rumania · Women»). Audience Network y Threads fuera (L1 0:56:40); solo el catálogo apagado
(L1 1:03:43, lo hace el ejecutor). Nombres ``PRODUCTO PAÍS | G1 | ABO | dd-mm-aa`` y ``ADnn G1 <ángulo>``, cada conjunto
como su anuncio (L1 1:02:20, L2 0:19:35). Una página para todo (L1 0:53:10) y el píxel del producto-país. UTM en todos
los anuncios (S1 8:30). Salida a las 00:00 (L1 0:58:29), en la zona de la cuenta (desvío D2: Meta programa en la zona de
la cuenta, America/Bogota). DSA en la UE: lo exige Meta (desvío de plataforma).

Renovación (Tarea 13, T3 18:55 y T3 19:55): las piezas nuevas van en conjuntos nuevos **de la misma ABO**
(``campana_existente``), a US$ 5/día cada uno y con los mismos ajustes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from trovefy.montar import MontajeInvalido, NoMedido
from trovefy.montar.config import ConfigMontar, cargar_config, generos, sexo_del_avatar
from trovefy.montar.importes import Importes, texto_importes
from trovefy.montar.tanda import PiezaTanda, bloque_pais
from trovefy.vault import frontmatter
from trovefy.vault.producto import ruta_producto

OBJETIVO = "OUTCOME_SALES"
PUJA = "LOWEST_COST_WITHOUT_CAP"
EVENTO = "PURCHASE"
_NUM = re.compile(r"[0-9]{1,20}")
_RELLENO = {"id": "P-20000101-001"}


@dataclass(frozen=True)
class ContextoMontaje:
    producto: str
    pais: str
    cuenta: str
    pagina_id: str
    dataset_id: str
    dataset_nombre: str
    idioma: str
    zona_pais: str
    avatar: str | None
    cfg: ConfigMontar


def _texto(v: object) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def cargar_contexto(vault: Path, p_id: str, pais: str) -> ContextoMontaje:
    """Lo que el montaje lee del vault. ``NoMedido`` con el dato que falte."""
    from trovefy.arranque.estado import cargar as pasos
    from trovefy.caja.config import cargar_caja
    from trovefy.config import mercados

    vault = Path(vault)
    cuenta = cargar_caja(vault).cuenta.id
    if not isinstance(cuenta, str) or not re.fullmatch(r"act_[0-9]{1,20}", cuenta):
        raise NoMedido("falta cuenta.id en config/caja.yaml (`trovefy caja iniciar`)")
    pagina = next((p.datos.get("page_id", "") for p in pasos(vault) if p.id == "05"), "")
    if not isinstance(pagina, str) or not _NUM.fullmatch(pagina):
        raise NoMedido("falta el page_id de la página del paso 05 de /arranque")
    tracking = bloque_pais(vault, p_id, pais).get("tracking")
    tracking = tracking if isinstance(tracking, dict) else {}
    dataset, nombre = str(tracking.get("dataset_id") or ""), _texto(tracking.get("dataset_nombre"))
    if not _NUM.fullmatch(dataset) or not nombre:
        raise NoMedido("falta paises.<PAIS>.tracking.dataset_id o dataset_nombre en PRODUCTO.md (/trovefy:tracking)")
    m = mercados.cargar(vault / "config" / "mercados.yaml").get(pais)
    if m is None:
        raise NoMedido(f"{pais} no está en config/mercados.yaml")
    avatar = None
    oferta = ruta_producto(vault, p_id).parent / "OFERTA.md"
    if oferta.is_file():
        meta, _ = frontmatter.leer(oferta)
        core = meta.get("core") if isinstance(meta, dict) else None
        avatar = _texto(core.get("avatar")) if isinstance(core, dict) else None
    return ContextoMontaje(p_id, pais, cuenta, pagina, dataset, nombre, m.idioma, m.zona, avatar,
                           cargar_config(vault))


def nombre_campana(dataset_nombre: str, grupo: int, fecha: date) -> str:
    """``PRODUCTO PAÍS | G1 | ABO | dd-mm-aa`` (L1 1:02:20); ``dataset_nombre`` ya es «PRODUCTO PAÍS» (C1 33:35)."""
    return f"{dataset_nombre} | G{grupo} | ABO | {fecha:%d-%m-%y}"


def inicio_programado(ahora: datetime, zona: str, hora_local: str, margen_h: int = 2) -> datetime:
    """La próxima ``hora_local`` en ``zona`` con al menos ``margen_h`` horas por delante."""
    z = ZoneInfo(zona)
    hh, mm = (int(x) for x in hora_local.split(":"))
    local = ahora.astimezone(z)
    candidato = datetime.combine(local.date(), time(hh, mm), tzinfo=z)
    while candidato - local < timedelta(hours=margen_h):
        candidato = datetime.combine(candidato.date() + timedelta(days=1), time(hh, mm), tzinfo=z)
    return candidato


def _paises_ue() -> frozenset[str]:
    from trovefy_ejecutor.esquema import PAISES_UE

    return frozenset(PAISES_UE)


def _comprobar_idioma(idioma: str) -> None:
    from trovefy_ejecutor.montaje import IDIOMAS_META

    if idioma not in IDIOMAS_META:
        raise MontajeInvalido(f"el idioma «{idioma}» no tiene clave de Meta en el ejecutor (IDIOMAS_META): "
                              "no se puede segmentar por idioma")


def _anuncio(p: PiezaTanda, cfg: ConfigMontar) -> dict:
    a = {"nombre": p.nombre, "medio": p.id.lower(), "texto": p.texto, "titulo": p.titulo,
         "descripcion": p.descripcion, "cta": p.cta or cfg.cta_por_defecto, "url": p.url_base, "url_tags": p.url_tags}
    if p.miniatura:
        a["miniatura"] = p.miniatura
    return a


def _conjunto(ctx: ContextoMontaje, p: PiezaTanda, importes: Importes, inicio: datetime) -> dict:
    c = {"nombre": p.nombre, "daily_budget": importes.diario_conjunto, "paises": [ctx.pais], "idiomas": [ctx.idioma],
         "evento": EVENTO, "ubicaciones_excluidas": list(ctx.cfg.ubicaciones_excluidas),
         "inicio": inicio.isoformat(timespec="seconds"), "anuncios": [_anuncio(p, ctx.cfg)]}
    g = generos(ctx.cfg, ctx.avatar)
    if g:
        c["generos"] = list(g)
    return c


def construir(ctx: ContextoMontaje, piezas: tuple[PiezaTanda, ...], importes: Importes, grupo: int, ahora: datetime,
              *, campana_existente: str | None = None, origen: str = "/montar") -> dict:
    """El JSON de ``crear_estructura_pausada`` (§5.2) **sin** ``id`` ni ``creada``; validado por el esquema del
    ejecutor antes de devolverlo. Nunca lleva ``status``: todo nace en PAUSED (lo fija el ejecutor)."""
    from trovefy_ejecutor.esquema import PropuestaInvalida, cargar_propuesta

    _comprobar_idioma(ctx.idioma)
    if not piezas:
        raise MontajeInvalido("no hay piezas que montar")
    inicio = inicio_programado(ahora, ctx.cfg.zona, ctx.cfg.hora_local, ctx.cfg.margen_min_h)
    hoy = ahora.astimezone(ZoneInfo(ctx.cfg.zona)).date()
    d: dict = {
        "tipo": "crear_estructura_pausada", "origen": origen, "producto": ctx.producto, "pais": ctx.pais,
        "cuenta": ctx.cuenta, "pagina_id": ctx.pagina_id, "dataset_id": ctx.dataset_id,
        "medios": [{"ref": p.id.lower(), "ruta": p.ruta, "sha256": p.sha256} for p in piezas],
        "campana": {"nombre": nombre_campana(ctx.dataset_nombre, grupo, hoy), "objetivo": OBJETIVO,
                    "tipo_presupuesto": "ABO", "spend_cap": importes.spend_cap, "bid_strategy": PUJA},
        "conjuntos": [_conjunto(ctx, p, importes, inicio) for p in piezas],
        "unidad": "minima", "moneda": importes.moneda,
    }
    if ctx.pais in _paises_ue() or ctx.cfg.dsa_beneficiario and ctx.cfg.dsa_pagador:
        d["dsa"] = ctx.cfg.dsa()
    if campana_existente is not None:
        if not _NUM.fullmatch(str(campana_existente)):
            raise MontajeInvalido(f"campaña existente con id no válido: {campana_existente!r}")
        d["campana_existente"] = str(campana_existente)
    try:
        cargar_propuesta({**d, **_RELLENO, "version": 1, "creada": ahora.isoformat()})
    except PropuestaInvalida as e:
        raise MontajeInvalido(f"la estructura no pasa el esquema del ejecutor: {e.motivo}") from None
    return d


def huella(estructura: dict) -> str:
    """sha256 del JSON canónico sin ``solo_validar``, ``id``, ``creada`` ni ``version`` (incluye los sha256 de los
    medios: un byte cambiado en un medio da otra huella)."""
    limpia = {k: v for k, v in estructura.items() if k not in ("solo_validar", "id", "creada", "version")}
    texto = json.dumps(limpia, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _fin4(x: str) -> str:
    return "…" + x[-4:]


def resumen_en_seco(estructura: dict, importes: Importes, piezas: tuple[PiezaTanda, ...], ctx: ContextoMontaje,
                    avisos: list[str] | None = None) -> str:
    """Bloque de confirmación antes de depositar: sin ids completos."""
    conj = estructura["conjuntos"]
    inicio = datetime.fromisoformat(conj[0]["inicio"])
    sexo = (sexo_del_avatar(ctx.avatar) if ctx.cfg.sexo == "auto" else ctx.cfg.sexo) or "todos"
    renov = estructura.get("campana_existente")
    lineas = [
        f"Montaje en seco · {ctx.producto} · {ctx.pais}" + (" · renovación en la misma ABO" if renov else ""),
        f"Cuenta: {_fin4(ctx.cuenta)} ({importes.moneda})",
        f"Campaña: {estructura['campana']['nombre']}" + (f" (ya existe: {_fin4(renov)})" if renov else ""),
        (f"Estructura: ABO · {len(conj)} conjunto{'s' if len(conj) != 1 else ''} × 1 anuncio · objetivo Ventas · "
        f"evento {EVENTO} del dataset {ctx.dataset_nombre}"),
        *texto_importes(importes),
        (f"Total diario: {len(conj)} × {importes.diario_conjunto} = {len(conj) * importes.diario_conjunto} "
        f"{importes.moneda} (US$ {len(conj) * importes.usd_diario})"),
        f"País: {ctx.pais} · idioma: {ctx.idioma} · sexo: {sexo} · sin edad ni intereses",
        (f"Fuera: {', '.join(estructura['conjuntos'][0]['ubicaciones_excluidas']) or 'ninguna'} · catálogo de "
        "productos apagado"),
        f"Página: {_fin4(ctx.pagina_id)} · DSA: " + (
            f"{estructura['dsa']['beneficiario']} / {estructura['dsa']['pagador']}" if "dsa" in estructura
            else "no hace falta (fuera de la UE)"),
        (f"Salida: {inicio.astimezone(ZoneInfo(ctx.cfg.zona)):%Y-%m-%d %H:%M} ({ctx.cfg.zona}) = "
        f"{inicio.astimezone(ZoneInfo(ctx.zona_pais)):%Y-%m-%d %H:%M} ({ctx.zona_pais})"),
        "",
        "Anuncios:",
    ]
    for p, c in zip(piezas, conj, strict=True):
        a = c["anuncios"][0]
        lineas += [f"- {a['nombre']} · {p.tipo} · botón {a['cta']} · enlace {a['url']} (UTM aparte)",
                   f"  título: {a['titulo']} · descripción: {a['descripcion']}",
                   f"  texto: {a['texto']}"]
    for aviso in avisos or []:
        lineas.append(f"Aviso: {aviso}")
    lineas += ["", "Todo se crea en PAUSED; para gastar hace falta tu Aceptar en Telegram («Activar campaña»)."]
    return "\n".join(lineas)
