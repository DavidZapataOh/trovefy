"""Agrupar anuncios en ofertas y detectar la página original (§4.3)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from trovify.caza.destino import Destino, clave_oferta, oferta_id, veredicto_landing
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
    destinos: list[Destino] = field(default_factory=list)  # destinos distintos de los anuncios del grupo


def _clave(destino: Destino | None, page_id: str) -> str:
    """Clave de oferta del destino; sin destino resuelto o no medido, la página."""
    if destino is None or destino.estado != "ok" or not (destino.url_final or destino.checkout):
        return f"pagina:{page_id}"
    return clave_oferta(destino.url_final or destino.url_anuncio, destino.checkout)


def _consolidar(candidatos: list[tuple[date, Destino]]) -> tuple[Destino, list[Destino]]:
    """Destino único y determinista de un grupo, sea cual sea el orden de los anuncios.

    Destinos distintos ordenados por fecha de inicio del anuncio; ``destino`` = el primero modelable
    (si no, el primero), con ``cloaker`` True si alguno lo tiene y el precio explícito más bajo.
    """
    unicos: dict[str, tuple[date, Destino]] = {}
    for inicio, d in candidatos:
        previo = unicos.get(d.url_anuncio)
        if previo is None or inicio < previo[0]:
            unicos[d.url_anuncio] = (inicio, d)
    destinos = [d for _, d in sorted(unicos.values(), key=lambda t: (t[0], t[1].url_anuncio))]
    elegido = next((d for d in destinos if veredicto_landing(d) == "modelable"), destinos[0])
    precios = [d for d in destinos if d.precio is not None and d.moneda is not None]
    if elegido.moneda is not None:
        precios = [d for d in precios if d.moneda == elegido.moneda]
    cambios: dict = {}
    if any(d.cloaker for d in destinos):
        cambios["cloaker"] = True
    if precios:
        barato = min(precios, key=lambda d: (d.precio, d.url_anuncio))
        cambios.update(precio=barato.precio, moneda=barato.moneda)
    return replace(elegido, **cambios), destinos


def agrupar(anuncios: list[AnuncioBiblioteca], destinos: dict[str, Destino]) -> list[Oferta]:
    """Agrupa por clave de oferta; ``destinos`` va por ``enlace_destino``. Orden: primera aparición.

    Si varios anuncios del grupo tienen destinos distintos se guardan todos en ``Oferta.destinos``."""
    grupos: dict[str, Oferta] = {}
    candidatos: dict[str, list[tuple[date, Destino]]] = {}
    for a in anuncios:
        d = destinos.get(a.enlace_destino) if a.enlace_destino else None
        clave = _clave(d, a.page_id)
        o = grupos.get(clave)
        if o is None:
            o = grupos[clave] = Oferta(oferta_id(clave), clave, [], [], None)
            candidatos[clave] = []
        if clave != f"pagina:{a.page_id}" and d is not None:
            candidatos[clave].append((a.inicio, d))
        o.anuncios.append(a)
        if a.page_id not in o.page_ids:
            o.page_ids.append(a.page_id)
    for clave, o in grupos.items():
        if candidatos[clave]:
            o.destino, o.destinos = _consolidar(candidatos[clave])
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
