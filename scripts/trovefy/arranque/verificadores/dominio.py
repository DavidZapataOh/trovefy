"""Pasos 07 y 08: el dominio propio en Cloudflare y su verificación en Meta.

07 y la parte TXT del 08 son públicas y se miden por DNS sobre HTTPS. El estado «verificado» de
business.facebook.com/settings/owned-domains es una pantalla privada (con un business_id guardado en el 04 se abre
/latest/settings/domains?business_id=<id>: con varios portfolios, la dirección sin ID lleva a «Seleccionar negocio»): mientras `CONFIRMACION_08`
no tenga fecha, el 08 no certifica aunque el TXT esté (el TXT solo no es la verificación de Meta; un TXT de otro Business
también queda provisional hasta confirmar esa pantalla).
"""

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import (
    MOTIVO_SIN_CONFIRMAR,
    Confirmacion,
    PantallaProvisional,
    confirmacion_de,
    guardar_evidencia,
    guardar_provisional,
    huella_de,
    lineas_provisionales,
    registrar_lector,
)
from trovefy.arranque.verificadores.meta_ids import (
    business_id_guardado,
    capturar_por_defecto,
    es_selector_de_negocio,
    leer_pagina,
    no_medido,
    selector_con_id,
    varios_portfolios,
)
from trovefy.dns import SinRed, normalizar
from trovefy.dns import consultar as consultar_doh
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vault.rutas import vault_root

URL_DOMINIOS = "https://business.facebook.com/settings/owned-domains"
URL_DOMINIOS_ID = "https://business.facebook.com/latest/settings/domains?business_id={bid}"
SUFIJO_NS = ".ns.cloudflare.com"
PREFIJO_TXT = "facebook-domain-verification="
SIN_RED = "no medido: sin red"
CONFIRMACION_08 = Confirmacion(
    fecha=None,
    fuente="encargo del plan 05: estado «verificado» en business.facebook.com/settings/owned-domains; falta la captura real",
)
MOTIVO_TXT_PENDIENTE = "TXT de Meta encontrado; falta confirmar el estado en Business Settings"

_VERIFICADO = re.compile(r"\b(verificado|verified)\b", re.IGNORECASE)
_NO_VERIFICADO = re.compile(r"\b(no verificado|not verified|unverified|sin verificar)\b", re.IGNORECASE)


def _resultado(ok: bool | None, motivo: str, arreglos: list[str] | None = None, **kw) -> ResultadoVerificacion:
    marca = {True: "✓", False: "✗", None: "?"}[ok]
    return ResultadoVerificacion(ok, kw.get("evidencia", []), motivo, arreglos or [], kw.get("datos", {}), [f"{marca} {motivo}"])


def evaluar_ns(ns: list[str]) -> ResultadoVerificacion:
    limpios = [n.strip().lower().rstrip(".") for n in ns]
    if any(n.endswith(SUFIJO_NS) for n in limpios):
        return _resultado(True, "el dominio usa los servidores de nombres de Cloudflare")
    motivo = "el dominio no usa los servidores de nombres de Cloudflare" if ns else "el dominio no responde con servidores de nombres"
    return _resultado(False, motivo, [
        "en Cloudflare, añade el dominio y copia los dos servidores de nombres que te da (terminan en .ns.cloudflare.com)",
        "en tu registrador, cámbialos por esos dos; si acabas de hacerlo, puede tardar horas en propagarse: repite la verificación más tarde",
    ])


def evaluar_txt(txt: list[str]) -> ResultadoVerificacion:
    if any(t.strip().strip('"').startswith(PREFIJO_TXT) for t in txt):
        return _resultado(True, "TXT de Meta encontrado")
    return _resultado(False, "no hay un TXT de Meta en el dominio", [
        "en Meta (Business Settings → Marcas → Dominios) copia el valor `facebook-domain-verification=…`",
        "en Cloudflare → DNS → Añadir registro: tipo TXT, nombre `@`, contenido ese valor; la propagación puede tardar: repite más tarde",
    ])


def _dominio_guardado(vault: Path) -> str | None:
    p = next((p for p in cargar(vault) if p.id == "07"), None)
    valor = p.datos.get("dominio") if p else None
    try:
        return normalizar(valor) if valor else None
    except ValueError:
        return None


def _sin_dominio() -> ResultadoVerificacion:
    return _resultado(None, "no medido: falta el dominio", [
        "guárdalo con `trovefy arranque hecho 07 --dato dominio=<tu-dominio>`",
    ])


def _sin_red() -> ResultadoVerificacion:
    return _resultado(None, SIN_RED, ["comprueba tu conexión y repite la verificación"])


def verificar_dominio(vault: Path | None = None, consultar: Callable = consultar_doh) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    dominio = _dominio_guardado(vault)
    if dominio is None:
        return _sin_dominio()
    try:
        ns = consultar(dominio, "NS")
    except SinRed:
        return _sin_red()
    r = evaluar_ns(ns)
    medida = {"dominio": dominio, "ns": ns, "fecha": f"{datetime.now(ZONA_NEGOCIO):%Y-%m-%d}"}
    ev = guardar_evidencia(vault, "07", "ns", medida, provisional=r.ok is not True)  # solo lo que certifica va a la raíz
    if r.ok is True:
        r.evidencia = [ev]
        r.datos = {"dominio": dominio}
    else:
        r.lineas.append(f"  medida guardada: {ev}")
    return r


def _posicion_dominio(texto: str, dominio: str) -> int:
    """Posición del dominio como palabra entera: «kits.com» no casa dentro de «mikits.com» ni de «shop.kits.com»."""
    m = re.search(rf"(?<![\w.-]){re.escape(dominio)}(?![\w-])", texto.lower())
    return m.start() if m else -1


def estado_del_dominio(texto: str, dominio: str) -> str | None:
    """«verificado» / «no verificado» justo después del dominio; None si no aparece o no se lee."""
    i = _posicion_dominio(texto, dominio)
    if i < 0:
        return None
    tramo = texto[i + len(dominio): i + len(dominio) + 120]
    if _NO_VERIFICADO.search(tramo):
        return "no verificado"
    return "verificado" if _VERIFICADO.search(tramo) else None


def _estado_verificado(texto: str, dominio: str) -> bool:
    """El dominio aparece y, justo después, el estado es «verificado» (no «no verificado»)."""
    return estado_del_dominio(texto, dominio) == "verificado"


def _leer_08(textos: dict[str, str], vault: Path) -> dict[str, str | None]:
    dominio, texto = _dominio_guardado(vault), textos.get("pagina", "")
    if dominio is None or _posicion_dominio(texto, dominio) < 0:
        return {"dominio": None, "estado": None}
    return {"dominio": dominio, "estado": estado_del_dominio(texto, dominio)}


def _aceptar_08(valores: dict[str, str | None]) -> str | None:
    # sin haber visto nunca «verificado», la rama positiva del patrón no está confirmada
    return None if valores.get("estado") == "verificado" else "confirma cuando Meta muestre el dominio verificado"


registrar_lector(
    "08", _leer_08, ("dominio", "estado"), _aceptar_08,
    huella_de("08", _VERIFICADO, _NO_VERIFICADO, r"(?<![\w.-]){dominio}(?![\w-])", "120 caracteres tras el dominio"),
)


def verificar_verificacion_meta(
    vault: Path | None = None,
    capturar: Callable | None = None,
    consultar: Callable = consultar_doh,
    confirmacion: Confirmacion = CONFIRMACION_08,
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "08", confirmacion)
    dominio = _dominio_guardado(vault)
    if dominio is None:
        return _sin_dominio()
    try:
        txt = consultar(dominio, "TXT")
    except SinRed:
        return _sin_red()
    t = evaluar_txt(txt)
    if not t.ok:
        return t
    bid = business_id_guardado(vault)
    url = URL_DOMINIOS_ID.format(bid=bid) if bid else URL_DOMINIOS
    cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo)
    if es_selector_de_negocio(cap.url_final):
        return selector_con_id(bid) if bid else varios_portfolios()
    if not confirmacion.confirmada:
        rutas, avisos = guardar_provisional(vault, "08", [PantallaProvisional("pagina", cap.url_final, png, cap.texto)])
        motivo = MOTIVO_TXT_PENDIENTE if confirmacion.aviso is None else f"{MOTIVO_TXT_PENDIENTE} ({confirmacion.aviso})"
        detalle = confirmacion.aviso or MOTIVO_SIN_CONFIRMAR
        lineas = [f"? {MOTIVO_TXT_PENDIENTE} ({detalle})", *lineas_provisionales(rutas, avisos)]
        return ResultadoVerificacion(None, [], motivo, [], {}, lineas)
    if not _estado_verificado(cap.texto, dominio):
        return _resultado(False, "Meta no muestra el dominio como verificado", [
            "en Business Settings → Marcas → Dominios, abre el dominio y pulsa «Verificar»; si el TXT es reciente, espera y repite",
        ])
    ev = [guardar_evidencia(vault, "08", "captura", png)] if png else []
    ev.append(guardar_evidencia(vault, "08", "dominio", {"dominio": dominio, "txt": True, "url": url}))
    return _resultado(True, f"{dominio} verificado en Meta", evidencia=ev, datos={"dominio": dominio})


@verificador("07")
def _v07(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_dominio(vault)


@verificador("08")
def _v08(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_verificacion_meta(vault)
