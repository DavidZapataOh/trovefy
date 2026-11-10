"""Agrupar anuncios en ofertas y detectar la página original (§4.3)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from trovify.caza.destino import Destino, clave_oferta, oferta_id
from trovify.caza.modelo import AnuncioBiblioteca


@dataclass
class Oferta:
    oferta_id: str
    clave: str
    page_ids: list[str]
    anuncios: list[AnuncioBiblioteca]
    destino: Destino | None
    origen: Literal["original", "copia", "desconocido"] = "desconocido"
    original_page_id: str | None = None
    copias: list[str] = field(default_factory=list)  # páginas que no son el original


def _clave(destino: Destino | None, page_id: str) -> str:
    """Clave de oferta del destino; sin destino resuelto o no medido, la página."""
    if destino is None or destino.estado != "ok" or not (destino.url_final or destino.checkout):
        return f"pagina:{page_id}"
    return clave_oferta(destino.url_final or destino.url_anuncio, destino.checkout)


def agrupar(anuncios: list[AnuncioBiblioteca], destinos: dict[str, Destino]) -> list[Oferta]:
    """Agrupa por clave de oferta; ``destinos`` va por ``enlace_destino``. Orden: primera aparición."""
    grupos: dict[str, Oferta] = {}
    for a in anuncios:
        d = destinos.get(a.enlace_destino) if a.enlace_destino else None
        clave = _clave(d, a.page_id)
        o = grupos.get(clave)
        if o is None:
            o = grupos[clave] = Oferta(oferta_id(clave), clave, [], [], d if clave != f"pagina:{a.page_id}" else None)
        o.anuncios.append(a)
        if a.page_id not in o.page_ids:
            o.page_ids.append(a.page_id)
    return list(grupos.values())


def marcar_original(oferta: Oferta) -> Oferta:
    """Con varias páginas, el original es la del anuncio más antiguo y, en empate, la de más países."""
    if len(oferta.page_ids) < 2:
        return replace(oferta, origen="desconocido", original_page_id=None, copias=[])

    def clave(page_id: str):
        propios = [a for a in oferta.anuncios if a.page_id == page_id]
        return (min(a.inicio for a in propios), -len({a.pais for a in propios}), page_id)

    original = min(oferta.page_ids, key=clave)
    return replace(
        oferta, origen="original", original_page_id=original, copias=[p for p in oferta.page_ids if p != original]
    )
