"""El píxel visto desde fuera (plan 19, Tarea 7): el HTML público de la tienda, la landing y el checkout.

GET con ``urllib`` (https, sin redirecciones a otro host, tope de 5 MB, el mismo patrón que la landing del 18):
sin JavaScript, así que no dispara el píxel ni manda eventos a Meta. Sin sesión en ningún panel.

- ``ok``: el único id que se ve es el del dataset;
- ``otro``: aparece otro id (tienda reciclada: hay que quitarlo, V1 0:31:50);
- ``no_visto``: ninguno (la tienda puede cargarlo por JavaScript: entonces manda la lectura del MCP);
- ``None`` + motivo: no se pudo leer el checkout (ahí se compra: sin él no hay «ok») ni ninguna página.

Entre dos GET al mismo dominio se esperan 5–8 s al azar (contrato 8, `navegador.esperar_entre_navegaciones`).
"""
from __future__ import annotations

import re
import urllib.error
from typing import Literal
from urllib.parse import urlsplit

from trovefy import navegador
from trovefy.landing.publicar import _abrir_seguro

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 20
_INIT = re.compile(r"(?<![\w$.])fbq\s*\(\s*['\"]init['\"]\s*,\s*['\"](\d+)['\"]", re.IGNORECASE)
_TR = re.compile(r"facebook\.com/tr/?\?[^\s\"'<>]*?(?:&amp;|&|\?)?\bid=(\d+)", re.IGNORECASE)
_ID = re.compile(r"\d{6,20}")


def pixeles_en_html(html: str) -> set[str]:
    """Ids de píxel de ``fbq('init', '<id>')`` y del ``<img>`` de ``facebook.com/tr?id=<id>`` (6 a 20 dígitos)."""
    ids = set(_INIT.findall(html)) | set(_TR.findall(html))
    return {i for i in ids if _ID.fullmatch(i)}


def _esperar(host: str) -> None:
    navegador.esperar_entre_navegaciones(host)


def _urls(ctx) -> list[str]:
    urls = [ctx.tienda + "/"] if ctx.tienda else []
    for extra in (ctx.landing_url, ctx.checkout_url):
        if extra and extra.startswith("https://") and extra not in urls:
            urls.append(extra)
    return urls


def _leer(url: str, abrir) -> str:
    host = urlsplit(url).hostname
    with abrir(url, timeout=TIMEOUT_S) as r:
        final = getattr(r, "geturl", None)
        if callable(final) and urlsplit(final()).hostname != host:
            raise ValueError("redirige a otro host")
        datos = r.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise ValueError("pasa de 5 MB")
    return datos.decode("utf-8", errors="replace")


def leer_pixel_publico(ctx, dataset_id: str | None, abrir=_abrir_seguro, esperar=None
                       ) -> tuple[Literal["ok", "otro", "no_visto"] | None, set[str], str | None]:
    """``(estado, ids vistos, motivo)`` de la tienda, la landing y el checkout públicos.

    Otro píxel en cualquier página es ``otro``; ``ok`` y ``no_visto`` exigen haber leído el checkout."""
    esperar = esperar or _esperar
    urls = _urls(ctx)
    if not urls:
        return None, set(), "no medido: falta la tienda de este país en config/mercados.yaml"
    ids: set[str] = set()
    leidas: list[str] = []
    fallos: list[str] = []
    for url in urls:
        try:
            esperar(urlsplit(url).hostname or "")
            ids |= pixeles_en_html(_leer(url, abrir))
            leidas.append(url)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            fallos.append(f"{url} ({type(exc).__name__}{': ' + str(exc) if isinstance(exc, ValueError) else ''})")
    nota = ("no se pudo leer " + "; ".join(fallos)) if fallos else None
    ajenos = sorted(ids - {dataset_id}) if dataset_id else sorted(ids)
    if ajenos:
        return "otro", ids, (f"la tienda carga otro píxel ({', '.join(ajenos)}): quítalo (V1 0:31:50)"
                             + (f"; {nota}" if nota else ""))
    if not leidas:
        return None, set(), f"no medido: {nota}"
    if ctx.checkout_url and ctx.checkout_url not in leidas:
        return None, ids, f"no medido: el checkout ({ctx.checkout_url}) no se pudo leer; {nota}"
    if not ids:
        return "no_visto", ids, ("ningún píxel en el HTML: la tienda puede cargarlo por JavaScript; manda la "
                                 "lectura del MCP de Impultienda" + (f"; {nota}" if nota else ""))
    return "ok", ids, nota
