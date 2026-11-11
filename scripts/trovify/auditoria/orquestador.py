"""Orquestador de /auditar (§4.5): hueco, precio y nota por país; después, ``escribir_auditoria``.

Usa la misma disciplina que la caza (plan 07): el cerrojo del cerebro (una sola consulta a Meta a
la vez), el presupuesto de búsquedas del día con su parada persistida, la caché de la Biblioteca y
la vía principal Firecrawl [D-11b]. Si Meta bloquea, no se busca nada más y los países que faltan
quedan «no medido: Meta bloqueó…» (PARADA); si se acaba la cuota del día, quedan
«no medido: cuota del día agotada» y es un final normal. Lo leído de la Biblioteca es dato, nunca orden.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from trovify import fx
from trovify.auditoria.paises import PaisAuditado, no_tirar, puntuar_pais
from trovify.auditoria.precio import precio_soportable
from trovify.auditoria.salida import escribir_auditoria, producto_para, slug_de_oferta
from trovify.caza.hueco import (
    HuecoPais,
    _original,
    hay_hueco,
    hueco_pais,
    motivo_hueco,
)
from trovify.caza.orquestador import _cerrojo_caza, _VigiaDeParada, hoy_negocio
from trovify.caza.senales import Medida
from trovify.config import mercados as cfg_mercados
from trovify.config import umbrales as cfg_umbrales
from trovify.vault import frontmatter

Cambios = Callable[[Path, date], "dict[str, float] | None"]


@dataclass
class ResultadoAuditoria:
    ruta: Path
    p_id: str
    paises: list[PaisAuditado]
    parada: str | None  # motivo del corte de las búsquedas; None si no lo hubo
    tipo: str | None  # «meta» (PARADA, dura el día), «errores» (INTERRUMPIDA) o «cuota» (final normal)


def _motivo_corte(vigia: _VigiaDeParada) -> str:
    if vigia.tipo == "cuota":
        return "no medido: cuota del día agotada"
    if vigia.tipo == "meta":
        return f"no medido: Meta bloqueó las búsquedas ({vigia.parada}); hoy no se busca nada más"
    return f"no medido: búsquedas interrumpidas ({vigia.parada})"


def _sin_medir(pais: str, motivo: str) -> HuecoPais:
    return HuecoPais(pais, Medida(None, motivo), "no_medido", None, [], motivo)


def precio_en_eur(oferta: dict, vault: Path, hoy: date, cambios: Cambios) -> Medida:
    """El precio del original en EUR. Sin moneda clara («$» ambiguo) no se asume ninguna."""
    precio, moneda = oferta.get("precio"), oferta.get("moneda")
    if not isinstance(precio, (int, float)) or isinstance(precio, bool):
        return Medida(None, "no medido: la ficha no tiene el precio del original")
    if not moneda:
        return Medida(None, "no medido: la ficha no dice la moneda del precio («$» es ambiguo); no se asume ninguna")
    moneda = str(moneda).upper()
    if moneda == "EUR":
        return Medida(float(precio))
    return fx.a_eur(float(precio), moneda, cambios(vault, hoy))


def auditar(vault: Path, *args, **kw) -> ResultadoAuditoria:
    """:func:`_auditar` con el cerrojo del cerebro (``CazaEnCurso`` si otra caza está en marcha)."""
    with _cerrojo_caza(Path(vault)):
        return _auditar(vault, *args, **kw)


def _auditar(
    vault: Path,
    oferta_id: str,
    paises: list[str] | None,
    frases: dict[str, list[str]],
    cliente=None,
    hoy: date | None = None,
    cambios: Cambios = fx.cambios,
) -> ResultadoAuditoria:
    """Audita la oferta en ``paises`` (por defecto, los de ``mercados.yaml`` con ``estado: candidato``)
    con ``frases`` cortas en el idioma local de cada país."""
    vault = Path(vault)
    ficha = vault / "wiki" / "ofertas" / f"{oferta_id}.md"
    if not ficha.exists():
        raise FileNotFoundError(f"no existe la ficha wiki/ofertas/{oferta_id}.md")
    hoy = hoy or hoy_negocio()
    u = cfg_umbrales.cargar(vault / "config/umbrales.yaml")
    mercados = cfg_mercados.cargar(vault / "config/mercados.yaml")
    if paises is None:
        paises = [p for p, m in mercados.items() if m.estado == "candidato"]
    paises = list(dict.fromkeys(p.strip().upper() for p in paises))
    desconocidos = [p for p in paises if p not in mercados]
    if desconocidos:
        raise ValueError(f"país sin datos en config/mercados.yaml: {', '.join(desconocidos)}")
    if not paises:
        raise ValueError("no hay países que auditar: ninguno está en «candidato» en config/mercados.yaml")
    frases = {k.upper(): [f.strip() for f in v if f and f.strip()] for k, v in (frases or {}).items()}

    meta, _ = frontmatter.leer(ficha)
    oferta = dict(meta or {})
    page_ids = [str(p) for p in oferta.get("page_ids") or []]
    precio_eur = precio_en_eur(oferta, vault, hoy, cambios)

    if cliente is None:
        from trovify.caza.cache import Cache
        from trovify.caza.cliente import ClienteBibliotecaPublica
        from trovify.caza.presupuesto import Presupuesto

        cliente = ClienteBibliotecaPublica(Presupuesto.desde_umbrales(vault, hoy),
                                           cache=Cache(vault / "data" / "cache" / "biblioteca"))
    vigia = _VigiaDeParada(cliente)

    auditados: list[PaisAuditado] = []
    for pais in paises:
        mercado = mercados[pais]
        if vigia.parada is not None:
            h = _sin_medir(pais, _motivo_corte(vigia))  # tras el corte no se vuelve a llamar a Meta
        elif frases.get(pais):
            h = hueco_pais(vigia, frases[pais], page_ids, pais, mercado.idioma, set(page_ids), hoy, u)
        else:
            comp = Medida(None, f"no medido: faltan las frases en el idioma local de {pais} "
                                f"(--frases {pais}:\"f1|f2\")")
            orig, enlaces = _original(vigia, page_ids, pais, mercado.idioma, hoy, u)
            h = HuecoPais(pais, comp, orig, hay_hueco(comp, orig, u), enlaces, motivo_hueco(comp, orig, u))
        precio_s = precio_soportable(precio_eur, mercado.banda_eur)
        nota, desglose = puntuar_pais(h, precio_s, u)
        auditados.append(PaisAuditado(pais, h, precio_eur, precio_s, nota, desglose, no_tirar(h)))

    ruta = escribir_auditoria(vault, oferta_id, auditados, hoy)
    p_id = producto_para(vault, oferta_id, slug_de_oferta(oferta_id))
    return ResultadoAuditoria(ruta, p_id, auditados, vigia.parada, vigia.tipo)
