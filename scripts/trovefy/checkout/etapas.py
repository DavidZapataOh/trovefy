"""Plan del MCP por etapas (plan 19, Tarea 11; M6 de la revisión T6–10).

La receta (Tarea 10) lleva marcadores para los ids que no se conocen al escribirla. Unos salen de las lecturas
(``<store_id>`` de ``listar_tiendas``, ``<item_id:front>`` de ``listar_productos``) y otros solo existen después de
una escritura: ``<market_id>`` (al crear el mercado), ``<item_id:uN>`` (al crear el upsell), ``<ruta:X>`` (al pedir
la subida del PDF), ``<oferta_id:uN>`` (al crear el funnel; se lee con ``ver_postcompra``), ``<bloques:abajo>`` (la
vista previa de los bloques actuales, limpiados con `limpiar_bloques`) y ``<url:mockup>`` (la foto que sube el
usuario a Recursos; se lee con ``ver_recursos``). ``<html:uN>`` lo calcula trovefy de la página del upsell.

Por eso la receta se parte en **etapas**: cada etapa solo lleva llamadas cuyos marcadores ya se conocen, se rellena,
se resume, se aprueba con las palabras del usuario y la huella de esa etapa, se aplica, se relee por el MCP y de lo
leído salen los ids de la siguiente. Una escritura nunca se aprueba con un marcador sin resolver.

Además de los marcadores, hay dependencias de orden (`depende_de`): el funnel post-compra de un upsell va después de
crearlo, ponerle precio y cargarle el PDF, para no ofrecer nunca un upsell sin precio ni entregable. Dentro de una
etapa vale una dependencia que va antes en la misma etapa (Claude aplica en orden y para en el primer error).

Este módulo es puro (sin E/S): `pasos_de`, `etapas_de` (la proyección completa, para el test de M6 y el resumen) y
`listos` (la etapa siguiente a partir de lo ya conocido y hecho, que usa `trovefy.checkout.operaciones`).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from trovefy.checkout.receta import Ajuste, marcadores

LOCAL = re.compile(r"<html:[a-z0-9_]+>")
VISTA_BLOQUES = "impultienda_bloques_checkout"
SUBIDA_RECURSOS = "impultienda_link_subida_recursos"
_CLAVE_PIEZA = re.compile(r"(?:producto\.(front)|postcompra\.(u[123]))\.")


@dataclass(frozen=True)
class Paso:
    """Una llamada de la receta (sin repetir), con los ajustes a los que sirve y una clave estable: el sha256 corto
    de ``[herramienta, argumentos con marcadores]``. ``solo_vista_previa``: la llamada se hace con
    ``confirmar: false`` explícito y nunca se confirma (solo sirve para leer lo que hay)."""

    clave: str
    ajustes: tuple[str, ...]
    herramienta: str
    argumentos: dict
    lectura: str | None
    solo_vista_previa: bool = False


def clave_de(herramienta: str, argumentos: dict) -> str:
    texto = json.dumps([herramienta, argumentos], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def pieza_de(ajuste: str) -> str | None:
    """``front`` o ``uN`` de una clave de ajuste (``producto.front.precio`` → ``front``)."""
    m = _CLAVE_PIEZA.match(ajuste + ".")
    return (m.group(1) or m.group(2)) if m else None


def _vista_bloques(ajuste: str) -> Paso:
    args = {"store_id": "<store_id>", "posicion": "abajo", "bloques": [], "confirmar": False}
    return Paso(clave_de(VISTA_BLOQUES, args), (ajuste,), VISTA_BLOQUES, args, None, solo_vista_previa=True)


def _subida_recursos(ajuste: str) -> Paso:
    args = {"store_id": "<store_id>"}
    return Paso(clave_de(SUBIDA_RECURSOS, args), (ajuste,), SUBIDA_RECURSOS, args, "impultienda_ver_recursos")


def pasos_de(ajustes: Iterable[Ajuste]) -> list[Paso]:
    """Las llamadas de la receta en su orden, sin repetir (una llamada que sirve a dos ajustes lleva los dos), más
    las dos de preparación que piden sus marcadores: la vista previa de los bloques de abajo antes de reenviarlos y
    el enlace de subida a Recursos antes de poner la foto del checkout."""
    orden: list[str] = []
    por_clave: dict[str, Paso] = {}
    for a in ajustes:
        for ll in a.llamadas:
            k = clave_de(ll.herramienta, ll.argumentos)
            if k in por_clave:
                p = por_clave[k]
                if a.clave not in p.ajustes:
                    por_clave[k] = Paso(k, (*p.ajustes, a.clave), p.herramienta, p.argumentos, p.lectura)
                continue
            orden.append(k)
            por_clave[k] = Paso(k, (a.clave,), ll.herramienta, ll.argumentos, ll.lectura)
    salida: list[Paso] = []
    preparados: set[str] = set()
    for k in orden:
        p = por_clave[k]
        m = marcadores(p.argumentos)
        if "<bloques:abajo>" in m and "bloques" not in preparados:
            preparados.add("bloques")
            salida.append(_vista_bloques(p.ajustes[0]))
        if "<url:mockup>" in m and "recursos" not in preparados:
            preparados.add("recursos")
            salida.append(_subida_recursos(p.ajustes[0]))
        salida.append(p)
    return salida


def produce(paso: Paso) -> set[str]:
    """Los marcadores que se conocen después de aplicar ``paso`` (y releer)."""
    h, a = paso.herramienta, paso.argumentos
    if paso.solo_vista_previa and h == VISTA_BLOQUES:
        return {f"<bloques:{a.get('posicion')}>"}
    if h == SUBIDA_RECURSOS:
        return {"<url:mockup>"}
    if h == "impultienda_configurar_mercado" and "market_id" not in a:
        return {"<market_id>"}
    piezas = {pieza_de(x) for x in paso.ajustes} - {None}
    if h == "impultienda_crear_producto":
        return {f"<item_id:{p}>" for p in piezas}
    if h == "impultienda_cargar_entregable" and a.get("modo") == "subir":
        return {f"<ruta:{p}>" for p in piezas}
    if h in ("impultienda_crear_funnel_postcompra", "impultienda_agregar_oferta_postcompra"):
        # cada oferta del funnel trae su downsell de recuperación (``<oferta_id:uNr>``)
        return {f"<oferta_id:{p}{r}>" for p in piezas for r in ("", "r")}
    return set()


def requiere(paso: Paso) -> set[str]:
    """Los marcadores que hacen falta para rellenar ``paso`` (sin los locales, ``<html:…>``). El funnel de un
    upsell, además, necesita el upsell ya creado."""
    faltan = {m for m in marcadores(paso.argumentos) if not LOCAL.fullmatch(m)}
    if paso.herramienta == "impultienda_crear_funnel_postcompra":
        faltan |= {f"<item_id:{p}>" for p in {pieza_de(x) for x in paso.ajustes} - {None}}
    return faltan


def depende_de(paso: Paso, pasos: list[Paso]) -> set[str]:
    """Las claves de los pasos que tienen que estar hechos antes (en una etapa anterior o antes en la misma): el
    funnel de ``uN`` va después de crear ``uN``, fijarle el precio y cargar su PDF; el descuento de su oferta, después
    de meterla en el funnel; activar la página propia de una oferta, después de guardarla."""
    if paso.herramienta in ("impultienda_crear_funnel_postcompra", "impultienda_agregar_oferta_postcompra"):
        piezas = {pieza_de(x) for x in paso.ajustes} - {None}
        previos = {f"postcompra.{p}.{c}" for p in piezas for c in ("titulo", "precio", "entregable")}
        return {q.clave for q in pasos if q is not paso and set(q.ajustes) & previos}
    if paso.herramienta == "impultienda_modificar_oferta_postcompra":
        activos = {f"postcompra.{p}.activo" for p in {pieza_de(x) for x in paso.ajustes} - {None}}
        return {q.clave for q in pasos if q is not paso and set(q.ajustes) & activos}
    if paso.herramienta == "impultienda_alternar_html_postcompra":
        return {q.clave for q in pasos if q.herramienta == "impultienda_guardar_html_postcompra"
                and q.argumentos.get("oferta_id") == paso.argumentos.get("oferta_id")}
    return set()


def listos(pasos: list[Paso], conocidos: set[str], hechos: set[str]) -> tuple[list[Paso], list[tuple[Paso, set]]]:
    """La etapa siguiente: los pasos no hechos cuyos marcadores ya se conocen y cuyas dependencias están hechas (o
    van antes en esta misma etapa), en orden; y los que esperan, con lo que les falta."""
    etapa: list[Paso] = []
    en_etapa: set[str] = set()
    esperan: list[tuple[Paso, set]] = []
    for p in pasos:
        if p.clave in hechos:
            continue
        faltan = requiere(p) - conocidos
        deps = depende_de(p, pasos) - hechos - en_etapa
        if faltan or deps:
            esperan.append((p, faltan | {f"antes: {d}" for d in deps}))
            continue
        etapa.append(p)
        en_etapa.add(p.clave)
    return etapa, esperan


def etapas_de(ajustes: Iterable[Ajuste], conocidos: set[str], hechos: set[str] | None = None) -> list[list[Paso]]:
    """Todas las etapas que quedan, suponiendo que cada paso aplicado da sus marcadores (`produce`) para la etapa
    siguiente. Los pasos que nunca podrían rellenarse se quedan fuera (los muestra `listos` como «esperan»)."""
    pasos = pasos_de(ajustes)
    conocidos = set(conocidos)
    hechos = set(hechos or ())
    etapas: list[list[Paso]] = []
    while True:
        etapa, _ = listos(pasos, conocidos, hechos)
        if not etapa:
            return etapas
        etapas.append(etapa)
        for p in etapa:
            hechos.add(p.clave)
            conocidos |= produce(p)
