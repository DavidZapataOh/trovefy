"""Pasos 04 y 05: el ID del portfolio comercial y el de la página de Facebook.

Se leen con el perfil de navegador «meta», en el que el usuario inició sesión él mismo.
Patrones del ID de página, confirmados con una captura real el 2026-11-10 de la página
pública https://www.facebook.com/102506312071455 (sin sesión): `"delegate_page":{...,"id":"N"`
y `\\"page_id\\":\\"N\\"` (JSON dentro de una cadena). Con sesión iniciada el HTML puede traer
otros bloques: por eso se toma el ID más repetido y se guarda la captura como evidencia.
"""

import re
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trovify.arranque.estado import ResultadoVerificacion, cargar
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import (
    Confirmacion,
    confirmacion_de,
    guardar_evidencia,
    registrar_lector,
    resultado_provisional,
    sin_query,
)
from trovify.vault.rutas import vault_root

URL_BUSINESS = "https://business.facebook.com/settings/"
COMANDO_ABRIR = "trovify navegador abrir meta https://business.facebook.com/"
SIN_SESION = f"no medido: inicia sesión en el navegador de Trovify (`{COMANDO_ABRIR}`)"

# Hasta que el usuario haga el paso y se capture su pantalla real, ninguno de los dos certifica.
CONFIRMACION_04 = Confirmacion(fecha=None, fuente="encargo del plan 05: `business_id=` en la URL de business.facebook.com/settings/")
CONFIRMACION_05_SESION = Confirmacion(
    fecha=None,
    fuente="patrones confirmados solo en HTML público sin sesión (2026-11-10); falta el HTML con la sesión «meta»",
)

PATRONES_PAGE_ID = (
    re.compile(r'"delegate_page":\{[^{}]*?"id":"(\d+)"'),
    re.compile(r'\\"page_id\\":\\"(\d+)\\"'),
)


def extraer_business_id(url: str) -> str | None:
    for valor in parse_qs(urlparse(url).query).get("business_id", []):
        if re.fullmatch(r"\d+", valor):
            return valor
    return None


def extraer_page_id(html: str) -> str | None:
    cuenta = Counter(i for p in PATRONES_PAGE_ID for i in p.findall(html))
    return cuenta.most_common(1)[0][0] if cuenta else None


def texto_04(url_final: str) -> str:
    """Lo que lee el patrón del 04: la URL sin query y, si está, solo `business_id=<dígitos>`."""
    bid = extraer_business_id(url_final)
    return sin_query(url_final) + (f"?business_id={bid}" if bid else "") + "\n"


def capturar_por_defecto(servicio: str, url: str, **kw):
    from trovify.navegador import capturar

    return capturar(servicio, url, **kw)


def sin_sesion(servicio: str) -> str:
    return SIN_SESION if servicio == "meta" else (
        f"no medido: inicia sesión en el navegador de Trovify (`trovify navegador abrir {servicio} <dirección de {servicio}>`)"
    )


def leer_pagina(url: str, capturar: Callable, servicio: str = "meta") -> tuple[object | None, bytes | None, str | None]:
    """Devuelve (captura, png, motivo_no_medido) con el perfil de navegador `servicio`."""
    from trovify.navegador import NavegadorError, sesion_caducada

    with tempfile.TemporaryDirectory(prefix="trovify-") as tmp:
        destino = Path(tmp) / "captura.png"
        try:
            cap = capturar(servicio, url, captura_png=destino)
        except NavegadorError as exc:
            return None, None, f"no medido: {exc}"
        if sesion_caducada(cap.url_final):
            return None, None, sin_sesion(servicio)
        png = destino.read_bytes() if destino.is_file() else None
    return cap, png, None


def no_medido(motivo: str) -> ResultadoVerificacion:
    return ResultadoVerificacion(None, [], motivo, [], {}, [f"? {motivo}"])


def _evidencia(vault: Path, id_: str, png: bytes | None, resumen: dict) -> list[str]:
    rel = [guardar_evidencia(vault, id_, "captura", png)] if png else []
    return rel + [guardar_evidencia(vault, id_, "ids", resumen)]


def verificar_business(
    vault: Path | None = None, capturar: Callable | None = None, confirmacion: Confirmacion = CONFIRMACION_04
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "04", confirmacion)
    cap, png, motivo = leer_pagina(URL_BUSINESS, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo)
    if not confirmacion.confirmada:
        return resultado_provisional(vault, "04", cap, png, texto=texto_04(cap.url_final))
    bid = extraer_business_id(cap.url_final)
    if bid is None:
        m = "la página de ajustes de Business no muestra un portfolio con ID"
        return ResultadoVerificacion(
            False, [], m,
            [
                (
                    "crea el portfolio en https://business.facebook.com/ (sin VPN) y, si ya lo tienes, abre sus ajustes con "
                    f"`{COMANDO_ABRIR}` para que la URL lleve `business_id=`"
                ),
            ],
            {}, [f"✗ {m}"],
        )
    ev = _evidencia(vault, "04", png, {"url": URL_BUSINESS, "business_id": bid})
    return ResultadoVerificacion(True, ev, f"portfolio comercial con ID {bid}", [], {"business_id": bid}, [f"✓ business_id {bid}"])


def _url_pagina(vault: Path) -> str | None:
    p = next((p for p in cargar(vault) if p.id == "05"), None)
    url = p.datos.get("url") if p else None
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    ok = urlparse(url).scheme == "https" and (host in ("facebook.com", "fb.com") or host.endswith((".facebook.com", ".fb.com")))
    return url if ok else None


def _id_numerico_de_url(url: str) -> str | None:
    partes = urlparse(url)
    primero = partes.path.strip("/").split("/")[0]
    if primero.isdigit():
        return primero
    if primero == "profile.php":
        ids = [v for v in parse_qs(partes.query).get("id", []) if v.isdigit()]
        return ids[0] if ids else None
    return None


def verificar_pagina(
    vault: Path | None = None, capturar: Callable | None = None, confirmacion: Confirmacion = CONFIRMACION_05_SESION
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "05", confirmacion)
    url = _url_pagina(vault)
    if url is None:
        m = "no medido: falta la URL de la página (https://www.facebook.com/…)"
        return ResultadoVerificacion(None, [], m, ["guárdala con `trovify arranque hecho 05 --dato url=https://www.facebook.com/<tu-página>`"],
                                     {}, [f"? {m}"])
    cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo)
    if not confirmacion.confirmada:
        # el HTML con sesión lleva tokens (fb_dtsg…): solo se guardan las líneas (o trozos) que casan, sin contexto
        return resultado_provisional(vault, "05", cap, png, texto=cap.html, patrones_extracto=PATRONES_PAGE_ID, contexto=0)
    pid = extraer_page_id(cap.html)
    esperado = _id_numerico_de_url(url)
    if pid is not None and esperado is not None and pid != esperado:
        m = "el ID de la página no coincide con el de la dirección guardada"
        return ResultadoVerificacion(False, [], m, ["guarda la dirección de tu página con `trovify arranque hecho 05 --dato url=…`"], {}, [f"✗ {m}"])
    if pid is None:
        m = "la página no muestra un ID reconocible"
        return ResultadoVerificacion(False, [], m, ["comprueba que la URL es la de tu página y que está publicada"], {}, [f"✗ {m}"])
    ev = _evidencia(vault, "05", png, {"url": url, "url_final": sin_query(cap.url_final), "page_id": pid})
    return ResultadoVerificacion(True, ev, f"página de Facebook con ID {pid}", [], {"page_id": pid}, [f"✓ page_id {pid}"])


registrar_lector("04", lambda textos, _v: {"business_id": extraer_business_id(textos.get("pagina", "").strip())}, ("business_id",))
registrar_lector("05", lambda textos, _v: {"page_id": extraer_page_id(textos.get("pagina", ""))}, ("page_id",))


@verificador("04")
def _v04(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_business(vault)


@verificador("05")
def _v05(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_pagina(vault)
