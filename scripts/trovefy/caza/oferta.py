"""Agrupar anuncios en ofertas y detectar la página original (§4.3)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from trovefy.caza.destino import (
    Destino,
    clave_oferta,
    elegir_precio,
    oferta_id,
    veredicto_landing,
)
from trovefy.caza.modelo import AnuncioBiblioteca


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


_AMBIGUO = "no medido: símbolo $ ambiguo"


def _sin_ambiguo(motivo: str | None) -> str | None:
    partes = [m.strip() for m in (motivo or "").split(";") if m.strip() and m.strip() != _AMBIGUO]
    return "; ".join(partes) or None


def _precio_de(d: Destino, moneda_pais: str | None) -> tuple[float, str | None] | None:
    if d.precios:
        return elegir_precio(d.precios, moneda_pais)
    return (d.precio, d.moneda) if d.precio is not None else None


def _consolidar(candidatos: list[tuple[date, Destino]], moneda_pais: str | None = None
                ) -> tuple[Destino, list[Destino]]:
    """Destino único y determinista de un grupo, sea cual sea el orden de los anuncios.

    Destinos distintos ordenados por fecha de inicio del anuncio; ``destino`` = el primero modelable
    (si no, el primero), con ``cloaker`` True si alguno lo tiene. Precio: un ``$`` ambiguo nunca gana
    a uno con moneda; entre monedas, la del país de los anuncios (``moneda_pais``), si no la del
    elegido, si no la primera; nunca el mínimo entre monedas. Dentro de esa moneda, el más bajo.
    """
    unicos: dict[str, tuple[date, Destino]] = {}
    for inicio, d in candidatos:
        previo = unicos.get(d.url_anuncio)
        if previo is None or inicio < previo[0]:
            unicos[d.url_anuncio] = (inicio, d)
    destinos = [d for _, d in sorted(unicos.values(), key=lambda t: (t[0], t[1].url_anuncio))]
    elegido = next((d for d in destinos if veredicto_landing(d) == "modelable"), destinos[0])
    precios = [(p, d) for d in destinos if (p := _precio_de(d, moneda_pais)) is not None]
    conocidos = [(p, d) for p, d in precios if p[1] is not None]
    cambios: dict = {}
    if any(d.cloaker for d in destinos):
        cambios["cloaker"] = True
    if conocidos:
        monedas = [p[1] for p, _ in conocidos]
        propia = _precio_de(elegido, moneda_pais)
        if moneda_pais in monedas:
            moneda = moneda_pais
        elif propia is not None and propia[1] is not None:
            moneda = propia[1]
        else:
            moneda = monedas[0]
        (precio, moneda), _ = min(((p, d) for p, d in conocidos if p[1] == moneda),
                                  key=lambda x: (x[0][0], x[1].url_anuncio))
        cambios.update(precio=precio, moneda=moneda, motivo=_sin_ambiguo(elegido.motivo))
    return replace(elegido, **cambios), destinos


def agrupar(anuncios: list[AnuncioBiblioteca], destinos: dict[str, Destino], mercados: dict | None = None
            ) -> list[Oferta]:
    """Agrupa por clave de oferta; ``destinos`` va por ``enlace_destino``. Orden: primera aparición.

    Si varios anuncios del grupo tienen destinos distintos se guardan todos en ``Oferta.destinos``.
    ``mercados`` (config/mercados.yaml) da la moneda del país con más anuncios del grupo: el precio
    se elige en esa moneda si la landing la muestra."""
    grupos: dict[str, Oferta] = {}
    candidatos: dict[str, list[tuple[date, Destino]]] = {}
    for a in anuncios:
        d = destinos.get(a.enlace_destino) if a.enlace_destino else None
        clave = _clave(d, a.page_id)
        o = grupos.get(clave)
        if o is None:
            o = grupos[clave] = Oferta(oferta_id(clave), clave, [], [], None)
            candidatos[clave] = []
        if d is not None:  # también el no medido: la clave es la página, pero el motivo se conserva
            candidatos[clave].append((a.inicio, d))
        o.anuncios.append(a)
        if a.page_id not in o.page_ids:
            o.page_ids.append(a.page_id)
    for clave, o in grupos.items():
        if candidatos[clave]:
            paises = Counter(a.pais for a in o.anuncios).most_common()
            principal = min(paises, key=lambda kv: (-kv[1], kv[0]))[0] if paises else None
            mercado = (mercados or {}).get(principal)
            o.destino, o.destinos = _consolidar(candidatos[clave], getattr(mercado, "moneda", None))
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
