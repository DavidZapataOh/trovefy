"""URLs reproducibles de la Biblioteca de anuncios y detección de bloqueos."""

from typing import Literal
from urllib.parse import urlencode, urlsplit

_BASE = "https://www.facebook.com/ads/library/"


def url_biblioteca(
    pais: str,
    q: str | None = None,
    page_id: str | None = None,
    estado: Literal["active", "all"] = "active",
) -> str:
    """Enlace reproducible; parámetros siempre en orden alfabético."""
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


def detectar_bloqueo(url_final: str, html: str) -> Literal["captcha", "login", "checkpoint"] | None:
    if "xfb_ad_library_is_captcha_required" in html:
        return "captcha"
    ruta = urlsplit(url_final).path
    if ruta.startswith("/login"):
        return "login"
    if ruta.startswith("/checkpoint"):
        return "checkpoint"
    return None
