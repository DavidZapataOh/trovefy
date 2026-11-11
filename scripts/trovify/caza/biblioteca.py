"""URLs reproducibles de la Biblioteca de anuncios y detección de bloqueos."""

import re
from html import unescape
from typing import Literal
from urllib.parse import urlencode, urlsplit

_BASE = "https://www.facebook.com/ads/library/"


def url_biblioteca(
    pais: str,
    q: str | None = None,
    page_id: str | None = None,
    estado: Literal["active", "all"] = "active",
) -> str:
    """Enlace reproducible; parámetros siempre en orden alfabético.

    Con ``q`` y ``page_id`` busca la frase dentro de la página (recuento por oferta).
    """
    if pais != "ALL" and not re.fullmatch(r"[A-Z]{2}", pais):
        raise ValueError(f"País inválido: {pais!r}; usa «ALL» o un código ISO-2 en mayúsculas.")
    q = q.strip() if q else None
    if not q and not page_id:
        raise ValueError("Hace falta al menos una palabra (q) o una página (page_id).")
    params: dict[str, str] = {
        "active_status": estado,
        "ad_type": "all",
        "country": pais,
        "media_type": "all",
    }
    if q:
        params["q"] = q
    params["search_type"] = "page" if page_id else "keyword_unordered"
    if page_id:
        params["view_all_page_id"] = page_id
    return f"{_BASE}?{urlencode(dict(sorted(params.items())))}"


_CAPTCHA = "xfb_ad_library_is_captcha_required"
# Las páginas normales traen la clave con valor false (grabado real del 2026-11-10).
_CAPTCHA_FALSE = re.compile(r'\\?"?\s*:\s*false\b')


def detectar_bloqueo(url_final: str, html: str) -> Literal["captcha", "login", "checkpoint"] | None:
    inicio = html.find(_CAPTCHA)
    while inicio != -1:
        fin = inicio + len(_CAPTCHA)
        if not _CAPTCHA_FALSE.match(html, fin):
            return "captcha"
        inicio = html.find(_CAPTCHA, fin)
    ruta = urlsplit(url_final).path
    if ruta == "/login" or ruta.startswith("/login/"):
        return "login"
    if ruta == "/checkpoint" or ruta.startswith("/checkpoint/"):
        return "checkpoint"
    return None


# Avisos de bloqueo que Meta puede servir con HTTP 200 en la propia /ads/library/. Son datos: se
# amplían aquí si aparecen otros. Se buscan solo en el texto de los encabezados (role="heading"),
# nunca en el HTML entero, para que el texto de un anuncio o de un script no los dispare.
MARCADORES_BLOQUEO = (
    "bloqueado temporalmente",
    "temporarily blocked",
    "you're temporarily blocked",
    "has usado esta función demasiado rápido",
)


def aviso_de_bloqueo(texto_encabezados: str) -> bool:
    """¿Muestran los encabezados un aviso de bloqueo (aunque la página llegara con HTTP 200)?"""
    t = unescape(texto_encabezados or "").replace("\u2019", "'").casefold()
    return any(m.casefold() in t for m in MARCADORES_BLOQUEO)
