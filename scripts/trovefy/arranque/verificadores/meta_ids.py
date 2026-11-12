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

from trovefy.arranque.estado import ResultadoVerificacion, cargar
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import (
    Confirmacion,
    confirmacion_de,
    guardar_evidencia,
    huella_de,
    registrar_lector,
    resultado_provisional,
    sin_query,
)
from trovefy.vault.rutas import vault_root

URL_BUSINESS = "https://business.facebook.com/settings/"
# Con un business_id guardado se abre su portfolio directamente: con varios portfolios, /settings/ lleva a
# «Seleccionar negocio» (https://business.facebook.com/select/, captura real del 2026-11-11).
URL_BUSINESS_INFO = "https://business.facebook.com/latest/settings/business_info?business_id={bid}"
COMANDO_ABRIR = "trovefy navegador abrir meta https://business.facebook.com/"
COMANDO_GUARDAR_ID = "trovefy arranque hecho 04 --dato business_id=<id>"
SIN_SESION = f"no medido: inicia sesión en el navegador de Trovefy (`{COMANDO_ABRIR}`)"
VARIOS_PORTFOLIOS = f"no medido: tienes varios portfolios: guarda cuál usas con `{COMANDO_GUARDAR_ID}`"
ARREGLO_VARIOS = (
    f"abre tu portfolio con `{COMANDO_ABRIR}`, elígelo en «Seleccionar negocio» y copia el número de `business_id=` "
    "de la dirección; luego guárdalo con ese comando"
)
VERIFICACION_SEGURIDAD = (
    "no medido: Meta pide una verificación de seguridad en el navegador de Trovefy; hazla tú y vuelve a verificar"
)
ARREGLO_SEGURIDAD = f"ábrelo con `{COMANDO_ABRIR}`, completa tú la verificación que pide Meta y cierra la ventana"

# Intersticial de seguridad de Meta (captura real del 2026-11-11, en la facturación: «Verificación necesaria …
# Verificar cuenta»). Basta el título: «Verificar» suelto aparece en pantallas normales (dominios, etc.).
_INTERSTICIAL = re.compile(r"^\s*(?:Verificación necesaria|Verification (?:required|needed))\s*$", re.MULTILINE | re.IGNORECASE)

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


def es_selector_de_negocio(url: str) -> bool:
    """La URL final es «Seleccionar negocio» (business.facebook.com/select/): hay varios portfolios."""
    partes = urlparse(url)
    return (partes.hostname or "").lower() == "business.facebook.com" and partes.path.rstrip("/") == "/select"


def pide_verificacion_seguridad(texto: str | None) -> bool:
    return bool(texto) and bool(_INTERSTICIAL.search(texto))


def business_id_guardado(vault: Path) -> str | None:
    """El business_id del paso 04 (guardado con `--dato business_id=` o por una verificación anterior)."""
    p = next((p for p in cargar(vault) if p.id == "04"), None)
    valor = (p.datos.get("business_id") or "").strip() if p else ""
    return valor if re.fullmatch(r"\d+", valor) else None


def varios_portfolios() -> ResultadoVerificacion:
    return ResultadoVerificacion(None, [], VARIOS_PORTFOLIOS, [ARREGLO_VARIOS], {}, [f"? {VARIOS_PORTFOLIOS}"])


def selector_con_id(bid: str) -> ResultadoVerificacion:
    m = f"no medido: Meta abrió «Seleccionar negocio» en vez del portfolio {bid}"
    return ResultadoVerificacion(
        None, [], m,
        [f"comprueba que {bid} es el `business_id=` de tu portfolio (sale en la dirección al abrirlo) o guarda el correcto con `{COMANDO_GUARDAR_ID}`"],
        {}, [f"? {m}"],
    )


def extraer_page_id(html: str) -> str | None:
    cuenta = Counter(i for p in PATRONES_PAGE_ID for i in p.findall(html))
    return cuenta.most_common(1)[0][0] if cuenta else None


def texto_04(url_final: str) -> str:
    """Lo que lee el patrón del 04: la URL sin query y, si está, solo `business_id=<dígitos>`."""
    bid = extraer_business_id(url_final)
    return sin_query(url_final) + (f"?business_id={bid}" if bid else "") + "\n"


def capturar_por_defecto(servicio: str, url: str, **kw):
    from trovefy.navegador import capturar

    return capturar(servicio, url, **kw)


def sin_sesion(servicio: str) -> str:
    return SIN_SESION if servicio == "meta" else (
        f"no medido: inicia sesión en el navegador de Trovefy (`trovefy navegador abrir {servicio} <dirección de {servicio}>`)"
    )


def leer_pagina(url: str, capturar: Callable, servicio: str = "meta") -> tuple[object | None, bytes | None, str | None]:
    """Devuelve (captura, png, motivo_no_medido) con el perfil de navegador `servicio`."""
    from trovefy.navegador import NavegadorError, sesion_caducada

    with tempfile.TemporaryDirectory(prefix="trovefy-") as tmp:
        destino = Path(tmp) / "captura.png"
        try:
            cap = capturar(servicio, url, captura_png=destino)
        except NavegadorError as exc:
            return None, None, f"no medido: {exc}"
        if sesion_caducada(cap.url_final):
            return None, None, sin_sesion(servicio)
        if servicio == "meta" and pide_verificacion_seguridad(getattr(cap, "texto", None)):
            return None, None, VERIFICACION_SEGURIDAD
        png = destino.read_bytes() if destino.is_file() else None
    return cap, png, None


def no_medido(motivo: str) -> ResultadoVerificacion:
    arreglos = [ARREGLO_SEGURIDAD] if motivo == VERIFICACION_SEGURIDAD else []
    return ResultadoVerificacion(None, [], motivo, arreglos, {}, [f"? {motivo}"])


def _evidencia(vault: Path, id_: str, png: bytes | None, resumen: dict) -> list[str]:
    rel = [guardar_evidencia(vault, id_, "captura", png)] if png else []
    return rel + [guardar_evidencia(vault, id_, "ids", resumen)]


def verificar_business(
    vault: Path | None = None, capturar: Callable | None = None, confirmacion: Confirmacion = CONFIRMACION_04
) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    confirmacion = confirmacion_de(vault, "04", confirmacion)
    guardado = business_id_guardado(vault)
    url = URL_BUSINESS_INFO.format(bid=guardado) if guardado else URL_BUSINESS
    cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo)
    if es_selector_de_negocio(cap.url_final):
        return selector_con_id(guardado) if guardado else varios_portfolios()
    if not confirmacion.confirmada:
        return resultado_provisional(vault, "04", cap, png, texto=texto_04(cap.url_final), motivo=confirmacion.aviso)
    bid = extraer_business_id(cap.url_final)
    if guardado and bid and bid != guardado:
        m = f"Meta abrió el portfolio {bid}, no el guardado ({guardado})"
        return ResultadoVerificacion(
            False, [], m, [f"comprueba que tu perfil tiene acceso al portfolio {guardado} o guarda el correcto con `{COMANDO_GUARDAR_ID}`"],
            {}, [f"✗ {m}"],
        )
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
    ev = _evidencia(vault, "04", png, {"url": sin_query(url), "business_id": bid})
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
        return ResultadoVerificacion(None, [], m, ["guárdala con `trovefy arranque hecho 05 --dato url=https://www.facebook.com/<tu-página>`"],
                                     {}, [f"? {m}"])
    cap, png, motivo = leer_pagina(url, capturar or capturar_por_defecto)
    if cap is None:
        return no_medido(motivo)
    if not confirmacion.confirmada:
        # el HTML con sesión lleva tokens (fb_dtsg…): solo se guardan las líneas (o trozos) que casan, sin contexto
        return resultado_provisional(vault, "05", cap, png, texto=cap.html, patrones_extracto=PATRONES_PAGE_ID, contexto=0,
                                     motivo=confirmacion.aviso)
    pid = extraer_page_id(cap.html)
    esperado = _id_numerico_de_url(url)
    if pid is not None and esperado is not None and pid != esperado:
        m = "el ID de la página no coincide con el de la dirección guardada"
        return ResultadoVerificacion(False, [], m, ["guarda la dirección de tu página con `trovefy arranque hecho 05 --dato url=…`"], {}, [f"✗ {m}"])
    if pid is None:
        m = "la página no muestra un ID reconocible"
        return ResultadoVerificacion(False, [], m, ["comprueba que la URL es la de tu página y que está publicada"], {}, [f"✗ {m}"])
    ev = _evidencia(vault, "05", png, {"url": url, "url_final": sin_query(cap.url_final), "page_id": pid})
    return ResultadoVerificacion(True, ev, f"página de Facebook con ID {pid}", [], {"page_id": pid}, [f"✓ page_id {pid}"])


registrar_lector(
    "04", lambda textos, _v: {"business_id": extraer_business_id(textos.get("pagina", "").strip())}, ("business_id",),
    huella=huella_de("04", "business_id=<dígitos> en la query de la URL final (parse_qs)"),
)
registrar_lector(
    "05", lambda textos, _v: {"page_id": extraer_page_id(textos.get("pagina", ""))}, ("page_id",),
    huella=huella_de("05", *PATRONES_PAGE_ID, "el ID más repetido"),
)


@verificador("04")
def _v04(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_business(vault)


@verificador("05")
def _v05(vault: Path | None = None) -> ResultadoVerificacion:
    return verificar_pagina(vault)
