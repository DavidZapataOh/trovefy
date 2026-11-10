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

from trovify.arranque.estado import ResultadoVerificacion, cargar
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import (
    Confirmacion,
    guardar_evidencia,
    resultado_provisional,
)
from trovify.arranque.verificadores.meta_ids import (
    SIN_SESION,
    _capturar_por_defecto,
    _leer_pagina,
    _no_medido,
)
from trovify.config import mercados, umbrales
from trovify.vault import frontmatter
from trovify.vault.rutas import vault_root

URL_AJUSTES = "https://www.facebook.com/ads/manager/account_settings/account_billing/"
CLAVE_LIMITE = "cuenta.limite_gasto_inicial_usd"

CONFIRMACION_06 = Confirmacion(
    fecha=None,
    fuente=(
        "documentación Meta Business Help Center 754049591334898 y 141820733085330 (2026-11-10); "
        "falta la captura de tu pantalla real de Payment settings"
    ),
)

_MONEDA = re.compile(r"^\s*Currency\s*:\s*([A-Z]{3})\s*$", re.MULTILINE)
_ZONA = re.compile(r"^\s*Time zone\s*:\s*(?:\(GMT[^)]*\)\s*)?([A-Za-z]+(?:/[A-Za-z_+\-0-9]+)+)\s*$", re.MULTILINE)
_LIMITE = re.compile(r"^\s*Account spending limit\s*:\s*(?:US)?\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:USD)?\s*$", re.MULTILINE)


def extraer_act(url: str) -> str | None:
    for valor in parse_qs(urlparse(url).query).get("act", []):
        if re.fullmatch(r"\d+", valor):
            return valor
    return None


def leer_ajustes_cuenta(texto: str) -> dict[str, str | None]:
    def uno(patron: re.Pattern[str]) -> str | None:
        m = patron.search(texto)
        return m.group(1) if m else None

    limite = uno(_LIMITE)
    return {"moneda": uno(_MONEDA), "zona": uno(_ZONA), "limite_gasto": limite.replace(",", "") if limite else None}


def mercado_elegido(vault: Path) -> str | None:
    """Zona horaria del mercado del `*-eleccion.md` más reciente (lo crea /auditar); None si no hay."""
    archivos = sorted(
        Path(vault).glob("productos/*/decisiones/*-eleccion.md"),
        key=lambda p: (p.name, p.stat().st_mtime),
    )
    if not archivos:
        return None
    try:
        meta, _ = frontmatter.leer(archivos[-1])
        todos = mercados.cargar(Path(vault) / "config" / "mercados.yaml")
    except (OSError, ValueError):
        return None
    pais = meta.get("pais") if isinstance(meta, dict) else None
    mercado = todos.get(pais) if isinstance(pais, str) else None
    return mercado.zona if mercado else None


def evaluar_cuenta(ajustes: dict, zona_esperada: str | None, limite_max: float) -> ResultadoVerificacion:
    def resultado(ok: bool | None, motivo: str, arreglo: str) -> ResultadoVerificacion:
        marca = "?" if ok is None else "✗"
        return ResultadoVerificacion(ok, [], motivo, [arreglo], {}, [f"{marca} {motivo}"])

    if not zona_esperada:
        return resultado(
            None,
            "no medido: elige primero el mercado con /auditar (la zona horaria no se puede cambiar después)",
            "ejecuta /trovify:auditar y elige el mercado antes de crear o revisar la cuenta",
        )
    if ajustes.get("moneda") != "USD":
        return resultado(
            False,
            f"la moneda de la cuenta es {ajustes.get('moneda') or 'desconocida'}, no USD",
            "la moneda no se puede cambiar: crea otra cuenta publicitaria con USD",
        )
    if ajustes.get("zona") != zona_esperada:
        return resultado(
            False,
            f"la zona horaria es {ajustes.get('zona') or 'desconocida'}, no {zona_esperada}",
            "cámbiala en Ajustes de pago → Información de la empresa antes de crear campañas (cierra la cuenta y crea otra)",
        )
    try:
        limite = float(ajustes.get("limite_gasto"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return resultado(False, "la cuenta no tiene límite de gasto", f"pon un límite de gasto de la cuenta de hasta US$ {limite_max:g}")
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
    act = _act_guardado(vault)
    url = f"{URL_AJUSTES}?act={act}" if act else URL_AJUSTES
    cap, png, motivo = _leer_pagina(url, capturar or _capturar_por_defecto)
    if cap is None:
        return _no_medido(motivo or SIN_SESION)
    if not confirmacion.confirmada:
        return resultado_provisional(vault, "06", cap, png)
    ajustes = leer_ajustes_cuenta(cap.texto)
    if ajustes["moneda"] is None and ajustes["zona"] is None:
        return _no_medido("no medido: la pantalla de ajustes no muestra moneda ni zona horaria")
    act = extraer_act(cap.url_final) or act
    if act is None:
        return _no_medido("no medido: no se ve el número de la cuenta (`act=`) en la dirección")
    r = evaluar_cuenta(ajustes, mercado_elegido(vault), umbrales.valor(vault, CLAVE_LIMITE))
    if r.ok is not True:
        return r
    ev = [guardar_evidencia(vault, "06", "captura", png)] if png else []
    ev.append(guardar_evidencia(vault, "06", "ajustes", {"act_id": act, **ajustes}))
    return ResultadoVerificacion(True, ev, r.motivo, [], {"act_id": act}, r.lineas)


@verificador("06")
def _v06(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_cuenta(vault)
