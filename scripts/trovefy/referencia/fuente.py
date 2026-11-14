"""Listado de anuncios de una página (lote MCP o Biblioteca pública) y sus medios.

Con lote, el listado sale del MCP y solo los medios se leen en la pública (una lectura por
Playwright, sin Firecrawl ni caché: los medios necesitan la página viva). Si el lote no da un
listado (inválido, búsqueda fuera del lote, error o límite de Meta), no se abre el navegador ni se
gasta una búsqueda; un límite de Meta dentro del lote para el día entero. Sin lote, la lectura
pública da también el listado. Un bloqueo de Meta o una racha de errores es una parada: no se
reintenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from trovefy.caza.cliente import (
    ClienteBibliotecaPublica,
    NavegadorEfimero,
    PaginaCapturada,
    SesionBloqueada,
)
from trovefy.caza.mcp import ClienteMcp, LoteInvalido, cargar_lote
from trovefy.caza.modelo import AnuncioBiblioteca
from trovefy.caza.presupuesto import (
    ParadaDelDia,
    ParadaPorErrores,
    Presupuesto,
    PresupuestoAgotado,
)
from trovefy.referencia.medios import MediosAnuncio, medios_de_pagina

MOTIVO_SIN_NAVEGADOR = "no medido: sin navegador (pedido por el usuario)"
MOTIVO_CUOTA = "no medido: cuota del día agotada"
MOTIVO_SIN_FUENTE = "no medido: sin lote del MCP y sin navegador"
MOTIVO_SIN_LISTADO = "no medido: sin listado del MCP no se leen los medios"
MOTIVO_PARADA_DIA = "Meta ya bloqueó hoy; vuelve mañana"


class NavegadorQueGuarda:
    """Envuelve un ``Navegador`` y recuerda en memoria la última página capturada."""

    def __init__(self, navegador):
        self.navegador = navegador
        self.ultima: PaginaCapturada | None = None

    def abrir(self, url: str, max_anuncios: int) -> PaginaCapturada:
        self.ultima = self.navegador.abrir(url, max_anuncios)
        return self.ultima


@dataclass
class Listado:
    anuncios: list[AnuncioBiblioteca]
    via: Literal["mcp", "publica"]
    completo: bool
    url: str
    motivo: str | None
    medios: dict[str, MediosAnuncio] = field(default_factory=dict)
    via_medios: Literal["publica"] | None = None
    motivo_medios: str | None = None
    parada: Literal["meta", "errores"] | None = None


def listar(
    vault: Path,
    pais: str,
    page_id: str,
    *,
    lote: Path | None,
    sin_navegador: bool,
    navegador=None,
    hoy: date,
) -> Listado:
    from trovefy.caza.biblioteca import url_biblioteca

    url = url_biblioteca(pais, None, page_id, "active")
    out = Listado([], "mcp" if lote is not None else "publica", False, url, None)
    if lote is not None:
        try:
            busquedas = cargar_lote(lote)
        except LoteInvalido as exc:
            # Sin cambio silencioso de fuente: el listado queda sin medir (los mensajes no llevan datos del lote).
            out.motivo = f"no medido: lote inválido ({exc})"
            out.motivo_medios = MOTIVO_SIN_LISTADO
            return out
        r = ClienteMcp(busquedas).buscar(pais, None, page_id, "active")
        out.anuncios, out.completo, out.url = list(r.anuncios), r.completo, r.url
        if r.estado not in ("ok", "vacio"):
            # Con lote, la pública nunca da el listado: ni se abre el navegador ni se gasta una búsqueda.
            out.motivo = r.motivo
            out.motivo_medios = MOTIVO_SIN_LISTADO
            if r.estado == "bloqueado":
                out.parada = "meta"
                out.motivo_medios = r.motivo
                Presupuesto.desde_umbrales(vault, hoy).registrar_parada(f"bloqueo de Meta: {r.motivo}")
            return out
    if sin_navegador:
        out.motivo_medios = MOTIVO_SIN_NAVEGADOR
        if lote is None:
            out.motivo = MOTIVO_SIN_FUENTE
        return out

    nav = NavegadorQueGuarda(navegador or NavegadorEfimero())
    try:
        cliente = ClienteBibliotecaPublica(Presupuesto.desde_umbrales(vault, hoy), navegador=nav, cache=None)
        # firecrawl no se pasa: con navegador inyectado no hay Firecrawl y la lectura es completa.
        r = cliente.buscar(pais, page_id=page_id, estado="active", max_anuncios=60, completa=True)
    except SesionBloqueada:
        out.parada = "meta"
        return out
    except ParadaPorErrores as exc:
        out.parada = "errores"
        out.motivo_medios = str(exc)
        return out
    except ParadaDelDia:
        out.parada = "meta"
        out.motivo_medios = MOTIVO_PARADA_DIA
        return out
    except PresupuestoAgotado:
        out.motivo_medios = MOTIVO_CUOTA
        return out

    if r.estado == "bloqueado":
        out.parada = "meta"
        out.motivo_medios = r.motivo
        return out
    if lote is None:
        out.anuncios, out.completo, out.url = list(r.anuncios), r.completo, r.url
        out.motivo = r.motivo if r.estado == "error" else None
    if nav.ultima is None or r.estado == "error":
        out.motivo_medios = r.motivo or "no medido: la página pública no se pudo leer"
        return out
    out.medios = medios_de_pagina(nav.ultima)
    out.via_medios = "publica"
    return out
