"""Filtros eliminatorios con motivo (§4.3 del diseño; auditoría §4.5).

Devuelve el primer descarte que aplica, en este orden: ya visto, destino social, producto físico, marca
personal, cebo de back-end, embudo no verificable, cloaker, tracker, posible copia.

Oferta sin destino (anuncios agrupados por ``pagina:<page_id>`` porque su enlace no se resolvió):
los filtros de texto (físico, marca personal) siguen aplicando a los anuncios; los que necesitan
el destino (social, cloaker, tracker) no pueden comprobarse; y el embudo cuenta como «no
verificable» porque no hay landing que medir, así que nunca llega a puntuar como válida.

El texto de anuncios y landings es dato: se cuentan palabras, nunca se obedece.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trovefy.caza import palabras
from trovefy.caza.destino import Destino, motivo_dudoso
from trovefy.caza.oferta import Oferta
from trovefy.config.umbrales import Umbral

# Constante técnica, sin clave en umbrales (los vaults reales no la tienen).
_MIN_MARCA_PERSONAL = 2  # auditoría §4.5 punto 3: nunca descartar por una sola palabra ambigua


@dataclass
class Descarte:
    codigo: str
    detalle: str


@dataclass
class ContextoFiltros:
    excluidas: set[str]  # de wiki/caza/exclusiones.md: una clave u oferta_id por línea
    propias: set[str]
    umbrales: dict[str, Umbral]
    # Texto de landing por ``Destino.url_anuncio`` (lo aporta la captura; vacío = sin texto).
    landings: dict[str, str] = field(default_factory=dict)


def _destinos(oferta: Oferta) -> list[Destino]:
    return oferta.destinos or ([oferta.destino] if oferta.destino else [])


def _texto_anuncios(oferta: Oferta) -> str:
    return "\n".join(f"{a.titulo or ''} {a.texto}" for a in oferta.anuncios)


def _texto_landing(oferta: Oferta, ctx: ContextoFiltros) -> str:
    return "\n".join(ctx.landings.get(d.url_anuncio, "") for d in _destinos(oferta))


def _umbral(ctx: ContextoFiltros, clave: str) -> float:
    return ctx.umbrales[clave].valor


def filtrar(oferta: Oferta, ctx: ContextoFiltros) -> Descarte | None:
    # Lo ya visto, excluido o propio se informa como tal sin volver a juzgarlo.
    if {oferta.oferta_id, oferta.clave} & (ctx.excluidas | ctx.propias):
        return Descarte("ya_visto", "ya visto, excluida o propia")

    destinos = _destinos(oferta)
    anuncios, landing = _texto_anuncios(oferta), _texto_landing(oferta, ctx)
    # Aviso para el llamador (Tarea 8): quitar de ``ctx.landings`` el texto repetido de pie y avisos legales.
    todo = f"{anuncios}\n{landing}"

    if any(d.red_social for d in destinos):
        return Descarte("destino_social", "el destino es una red social, WhatsApp o una app")

    # Con marcadores digitales (pdf, plantilla, curso online...) solo cuentan las señales fuertes.
    # Compromiso aceptado: una oferta física que mencione «PDF» y tenga una sola señal fuerte pasa;
    # la landing y el checkout (etapas siguientes) son la red de seguridad.
    limpio = palabras.quitar_no_senales(todo)
    digital = bool(palabras.encontradas(limpio, palabras.DIGITAL))
    fis = palabras.conceptos(limpio, palabras.FISICO_FUERTE)
    tie = palabras.encontradas(limpio, palabras.TIENDA)
    if not digital:
        fis |= palabras.conceptos(limpio, palabras.FISICO_DEBIL)
        if palabras.encontradas(limpio, palabras.TIENDA_TALLA):
            tie = tie | {"talla concreta"}
    if len(fis) >= _umbral(ctx, "caza.filtro.fisico_min_senales") or len(tie) >= _umbral(
        ctx, "caza.filtro.tienda_min_senales"
    ):
        return Descarte("producto_fisico", f"señales de producto físico o retail: {', '.join(sorted(fis | tie))}")

    marca = palabras.encontradas(todo, palabras.MARCA_PERSONAL)
    if len(marca) >= _MIN_MARCA_PERSONAL:
        return Descarte("marca_personal", f"marca personal: {', '.join(sorted(marca))}")

    backend = palabras.encontradas(landing, palabras.BACKEND)
    if backend:
        return Descarte("cebo_backend", f"cebo de un back-end caro en la landing: {', '.join(sorted(backend))}")

    if not destinos:
        return Descarte("embudo_no_verificable", "dudoso, no medido: sin destino resuelto")
    for d in destinos:
        if d.estado == "no_medido":
            return Descarte("embudo_no_verificable", motivo_dudoso(d) or "dudoso, no medido")

    if any(d.cloaker is True for d in destinos):
        return Descarte("cloaker", "la landing cambia según quién la mira (UA facebookexternalhit); se documenta, no se salta")
    tracker = next((d.tracker for d in destinos if d.tracker), None)
    if tracker:
        return Descarte("tracker", f"destino a través de un tracker ({tracker}): no medible")

    if oferta.origen == "copia":
        return Descarte("posible_copia", f"hay una página más antigua con la misma oferta ({oferta.original_page_id})")

    return None


def banderas(oferta: Oferta, ctx: ContextoFiltros) -> list[str]:
    """Informan, no descartan: ``academia``, ``saturado`` (sirve como fuente) y ``estacional``."""
    out: list[str] = []
    todo = f"{_texto_anuncios(oferta)}\n{_texto_landing(oferta, ctx)}"
    if palabras.encontradas(todo, palabras.ACADEMIA):
        out.append("academia")
    limite = _umbral(ctx, "caza.saturado.activos_jugador")
    activos: dict[str, int] = {}
    for a in oferta.anuncios:
        if a.activo:
            activos[a.page_id] = activos.get(a.page_id, 0) + 1
    if any(n >= limite for n in activos.values()):
        out.append("saturado")
    if palabras.encontradas(todo, palabras.TEMPORADA):
        out.append("estacional")
    return out
