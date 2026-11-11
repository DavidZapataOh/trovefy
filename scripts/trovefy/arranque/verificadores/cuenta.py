"""Paso 06: la cuenta publicitaria con moneda USD, zona horaria del primer mercado y límite de gasto.

Moneda y zona horaria no se pueden cambiar después (cambiar la zona cierra la cuenta y crea otra).
Fuente de los rótulos de `leer_ajustes_cuenta` (documentación oficial vigente, leída el 2026-11-10):
- https://www.facebook.com/business/help/754049591334898 («How to change the time zone for your ad account
  in Meta Ads Manager»): pantalla «Payment settings» → sección «Business info» → «Currency and time zone».
- https://www.facebook.com/business/help/141820733085330 («About ad account spending limits»): el límite
  de gasto se ve en «Payment settings» como «ad account spending limit».
La pantalla real aún no se ha capturado: los patrones están sin confirmar (`CONFIRMACION_06.fecha is None`) y,
mientras tanto, el verificador devuelve «no medido» y guarda la captura como evidencia provisional.
"""

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import (
    Confirmacion,
    confirmacion_de,
    guardar_evidencia,
    huella_de,
    registrar_lector,
    resultado_provisional,
)
from trovefy.arranque.verificadores.meta_ids import (
    SIN_SESION,
    capturar_por_defecto,
    leer_pagina,
    no_medido,
)
from trovefy.config import mercados, umbrales
from trovefy.vault import frontmatter
from trovefy.vault.rutas import vault_root

URL_AJUSTES = "https://www.facebook.com/ads/manager/account_settings/account_billing/"
CLAVE_LIMITE = "cuenta.limite_gasto_inicial_usd"

CONFIRMACION_06 = Confirmacion(
    fecha=None,
    fuente=(
        "documentación Meta Business Help Center 754049591334898 y 141820733085330 (2026-11-10); "
        "falta la captura de tu pantalla real de Payment settings"
    ),
)

ILEGIBLE = "ilegible"  # la línea del límite existe, pero el número es ambiguo
SIN_LIMITE = "sin_limite"  # el rótulo del límite está, pero sin cantidad

_MONEDA = re.compile(r"^\s*(?:Currency|Moneda)\s*:\s*([A-Z]{3})\s*$", re.MULTILINE)
_ZONA = re.compile(
    r"^\s*(?:Time zone|Zona horaria)\s*:\s*(?:\(GMT[^)]*\)\s*)?"
    r"(UTC|GMT(?:[+\-]\d{1,2}(?::\d{2})?)?|[A-Za-z]+(?:/[A-Za-z_+\-0-9]+)+)\s*$",
    re.MULTILINE,
)
_LIMITE = re.compile(r"^\s*(?:Account spending limit|Límite de gasto de la cuenta)\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_ROTULO_LIMITE = re.compile(r"Account spending limit|Límite de gasto de la cuenta", re.IGNORECASE)


def _numero(texto: str) -> str | None:
    """Número en formato inglés o español → cadena con punto decimal; None si es ambiguo."""
    t = re.sub(r"US\$|\$|USD|\s", "", texto)
    if not re.fullmatch(r"\d[\d.,]*", t):
        return None
    puntos, comas = t.count("."), t.count(",")
    if puntos and comas:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        mil = "," if dec == "." else "."
        ent, _, frac = t.rpartition(dec)
        if not re.fullmatch(r"\d{1,2}", frac) or t.count(dec) != 1:
            return None
        grupos = ent.split(mil)
        if mil in frac or not re.fullmatch(r"\d{1,3}", grupos[0]) or not all(re.fullmatch(r"\d{3}", g) for g in grupos[1:]):
            return None
        return "".join(grupos) + "." + frac
    sep = "." if puntos else "," if comas else None
    if sep is None:
        return t
    partes = t.split(sep)
    if len(partes) == 2 and re.fullmatch(r"\d{1,2}", partes[1]) and partes[0]:
        return partes[0] + "." + partes[1]
    if sep == "," and re.fullmatch(r"\d{1,3}", partes[0]) and all(re.fullmatch(r"\d{3}", g) for g in partes[1:]):
        return "".join(partes)  # 1,000 o 1,000,000: miles
    if sep == "." and len(partes) > 2 and re.fullmatch(r"\d{1,3}", partes[0]) and all(re.fullmatch(r"\d{3}", g) for g in partes[1:]):
        return "".join(partes)  # 1.000.000: miles sin ambigüedad
    return None  # «1.000» o «12,345,6»: no se sabe si son miles o decimales


def extraer_act(url: str) -> str | None:
    for valor in parse_qs(urlparse(url).query).get("act", []):
        if re.fullmatch(r"\d+", valor):
            return valor
    return None


def leer_ajustes_cuenta(texto: str) -> dict[str, str | None]:
    def uno(patron: re.Pattern[str]) -> str | None:
        m = patron.search(texto)
        return m.group(1) if m else None

    bruto = uno(_LIMITE)
    if bruto is None:
        limite = SIN_LIMITE if _ROTULO_LIMITE.search(texto) else None  # rótulo sin cantidad / ni rótulo
    elif not re.search(r"\d", bruto):
        limite = SIN_LIMITE
    else:
        limite = _numero(bruto) or ILEGIBLE
    return {"moneda": uno(_MONEDA), "zona": uno(_ZONA), "limite_gasto": limite}


def mercado_elegido(vault: Path) -> str | None:
    """Zona horaria del mercado del `*-eleccion.md` válido más reciente (lo crea /auditar); None si no hay.

    Se saltan las decisiones de un país que no está en config/mercados.yaml (una errata como «RU»,
    marcada ``fuera_de_mercados``): nunca tapan una elección válida anterior."""
    archivos = sorted(
        Path(vault).glob("productos/*/decisiones/*-eleccion.md"),
        key=lambda p: (p.name, p.stat().st_mtime),
    )
    if not archivos:
        return None
    try:
        todos = mercados.cargar(Path(vault) / "config" / "mercados.yaml")
    except (OSError, ValueError):
        return None
    for archivo in reversed(archivos):
        try:
            meta, _ = frontmatter.leer(archivo)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("fuera_de_mercados") is True:
            continue
        pais = meta.get("pais")
        mercado = todos.get(pais) if isinstance(pais, str) else None
        if mercado:
            return mercado.zona
    return None


def evaluar_cuenta(ajustes: dict, zona_esperada: str | None, limite_max: float) -> ResultadoVerificacion:
    def resultado(ok: bool | None, motivo: str, arreglo: str) -> ResultadoVerificacion:
        marca = "?" if ok is None else "✗"
        return ResultadoVerificacion(ok, [], motivo, [arreglo], {}, [f"{marca} {motivo}"])

    if ajustes.get("moneda") != "USD":  # primero: una moneda equivocada es irreversible, haya mercado o no
        return resultado(
            False,
            f"la moneda de la cuenta es {ajustes.get('moneda') or 'desconocida'}, no USD",
            "la moneda no se puede cambiar: crea otra cuenta publicitaria con USD",
        )
    if not zona_esperada:
        return resultado(
            None,
            "no medido: elige primero el mercado con /auditar (la zona horaria no se puede cambiar después)",
            "ejecuta /trovefy:auditar y elige el mercado antes de crear o revisar la cuenta",
        )
    if ajustes.get("zona") != zona_esperada:
        return resultado(
            False,
            f"la zona horaria es {ajustes.get('zona') or 'desconocida'}, no {zona_esperada}",
            "cámbiala en Ajustes de pago → Información de la empresa antes de crear campañas (cierra la cuenta y crea otra)",
        )
    if ajustes.get("limite_gasto") is None:
        return resultado(None, "no medido: no se ve el límite de gasto en la pantalla", "revisa el límite en Ajustes de pago (hasta US$ " f"{limite_max:g})")
    if ajustes.get("limite_gasto") == ILEGIBLE:
        return resultado(None, "no medido: no se entiende el número del límite de gasto", "revisa el límite en Ajustes de pago (hasta US$ " f"{limite_max:g})")
    try:
        limite = float(ajustes.get("limite_gasto"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return resultado(
            False,
            "la cuenta no tiene límite de gasto",
            f"pon un límite de gasto de la cuenta de hasta US$ {limite_max:g}; si tu cuenta usa fondos prepagados no admite límite: "
            "cambia a pago automático con tarjeta",
        )
    if limite <= 0:
        return resultado(False, "límite de gasto inválido (debe ser mayor que 0)", f"pon un límite de hasta US$ {limite_max:g}")
    if limite > limite_max:
        return resultado(False, f"el límite de gasto (US$ {limite:g}) supera el máximo (US$ {limite_max:g})", f"bájalo a US$ {limite_max:g} o menos")
    return ResultadoVerificacion(
        True, [], f"moneda USD, zona {zona_esperada}, límite US$ {limite:g}", [], {},
        ["✓ moneda USD", f"✓ zona {zona_esperada}", f"✓ límite de gasto US$ {limite:g}"],
    )


def _act_guardado(vault: Path) -> str | None:
    p = next((p for p in cargar(vault) if p.id == "06"), None)
    valor = p.datos.get("act_id") if p else None
    return valor if valor and re.fullmatch(r"\d+", valor) else None


def verificar_cuenta(
    vault: Path | None = None, capturar: Callable | None = None, confirmacion: Confirmacion = CONFIRMACION_06
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "06", confirmacion)
    act = _act_guardado(vault)
    url = f"{URL_AJUSTES}?act={act}" if act else URL_AJUSTES
    cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo or SIN_SESION)
    if not confirmacion.confirmada:
        return resultado_provisional(vault, "06", cap, png, motivo=confirmacion.aviso)
    ajustes = leer_ajustes_cuenta(cap.texto)
    if ajustes["moneda"] is None and ajustes["zona"] is None:
        return no_medido("no medido: la pantalla de ajustes no muestra moneda ni zona horaria")
    act = extraer_act(cap.url_final) or act
    if act is None:
        return no_medido("no medido: no se ve el número de la cuenta (`act=`) en la dirección")
    r = evaluar_cuenta(ajustes, mercado_elegido(vault), umbrales.valor(vault, CLAVE_LIMITE))
    if r.ok is not True:
        return r
    ev = [guardar_evidencia(vault, "06", "captura", png)] if png else []
    ev.append(guardar_evidencia(vault, "06", "ajustes", {"act_id": act, **ajustes}))
    return ResultadoVerificacion(True, ev, r.motivo, [], {"act_id": act}, r.lineas)


def _aceptar_06(valores: dict[str, str | None]) -> str | None:
    limite = valores.get("limite_gasto")
    if limite in (None, SIN_LIMITE):
        return "pon primero el límite de gasto (paso 5 de la guía) y vuelve a capturar"
    if limite == ILEGIBLE:
        return "el número del límite de gasto no se entiende; hay que ajustar el patrón (cambio en el repo)"
    return None


registrar_lector(
    "06", lambda textos, _v: leer_ajustes_cuenta(textos.get("pagina", "")), ("moneda", "zona"), _aceptar_06,
    huella_de("06", _MONEDA, _ZONA, _LIMITE, _ROTULO_LIMITE),
)


@verificador("06")
def _v06(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_cuenta(vault)
