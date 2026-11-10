"""Tipos de la caza en la Biblioteca pública de anuncios de Meta."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class AnuncioBiblioteca:
    """Un anuncio de la Biblioteca.

    ``fin`` viene presente también en anuncios activos (es la fecha programada, no el final real):
    quien consuma esto debe decidir con ``activo``, nunca con ``fin``.
    """

    library_id: str
    page_id: str
    page_name: str
    inicio: date
    fin: date | None
    activo: bool
    plataformas: tuple[str, ...]
    texto: str
    titulo: str | None
    enlace_destino: str | None
    collation_id: str | None
    collation_count: int | None
    pais: str


@dataclass
class Parseo:
    """Resultado de leer una página: anuncios, entradas descartadas por malformadas y el total del JSON."""

    anuncios: list[AnuncioBiblioteca]
    descartados: int
    total_json: int | None  # ``count`` de search_results_connection en el HTML; None si no viene
    # ``page_info.has_next_page`` de la última página leída; None si ninguna lo trae.
    hay_mas: bool | None = None


@dataclass
class ResultadoBusqueda:
    """Una búsqueda en la Biblioteca.

    ``completo`` es True solo cuando Meta dice que no hay más páginas (``has_next_page`` false) o
    su ``count`` no supera los anuncios leídos, sin recortar por ``max_anuncios`` ni descartar
    ninguno; un ``vacio`` es completo; ``bloqueado`` y ``error`` nunca. Un resultado incompleto es
    una muestra (los primeros por impresiones): sus recuentos son «≥» (cota inferior) y no sirven
    para calcular anuncios nuevos o parados (``snapshots.registrar_vistos(..., completo=False)``
    no registra nada).
    """

    estado: Literal["ok", "vacio", "bloqueado", "error"]
    url: str
    total_aprox: int | None
    anuncios: list[AnuncioBiblioteca]
    motivo: str | None
    capturado_en: datetime
    completo: bool = False
