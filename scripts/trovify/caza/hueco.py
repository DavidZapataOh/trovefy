"""Hueco por país en el idioma local (§4.3): competencia local y si el original ya está traducido.

Un recuento solo vale como cero si todas las búsquedas devolvieron ``ok``/``vacio`` y fueron
completas; un competidor más allá de la primera página nunca puede producir ``hueco=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from trovify.caza.cliente import SesionBloqueada
from trovify.caza.modelo import AnuncioBiblioteca, ResultadoBusqueda
from trovify.caza.presupuesto import ParadaPorErrores, PresupuestoAgotado
from trovify.caza.senales import Medida
from trovify.config.umbrales import Umbral
from trovify.idioma import detectar

Original = Literal["traducido", "sin_traducir", "ausente_reciente", "ausente", "no_medido"]

# Idiomas de contraste para decidir si un texto está en el idioma local: la detección necesita al
# menos dos candidatos y el idioma del país siempre va entre ellos.
_CONTRASTE = ("en", "es", "it", "fr", "pt", "ro")
_MAX_ANUNCIOS = 60
_DIAS_COMPETIDOR = 7  # edad mínima de un anuncio para contar como señal (cohorte C7)
_MOTIVO_SUELO = "no comprobado: hay más anuncios que los leídos"


@dataclass
class HuecoPais:
    pais: str
    competencia: Medida
    original: str
    hueco: bool | None
    enlaces: list[str] = field(default_factory=list)
    motivo: str | None = None


def _nm(motivo: str) -> Medida:
    return Medida(None, f"no medido: {motivo}")


def _idioma_de(texto: str, idioma: str) -> bool | None:
    """True si está en ``idioma``, False si se detecta otro, None si no se puede detectar."""
    d = detectar(texto, sorted({idioma.lower(), *_CONTRASTE}))
    return None if d is None else d == idioma.lower()


def _buscar(cliente, pais: str, **kw) -> ResultadoBusqueda | str:
    """El resultado, o el motivo si el cliente paró (nunca se confunde con «sin anuncios»)."""
    try:
        return cliente.buscar(pais, estado="active", max_anuncios=_MAX_ANUNCIOS, **kw)
    except (SesionBloqueada, ParadaPorErrores, PresupuestoAgotado) as e:
        return f"{type(e).__name__}: {e}"


def _incompleta(r: ResultadoBusqueda) -> bool:
    # Un ``vacio`` es completo por definición; un ``ok`` solo si Meta dice que no hay más.
    return r.estado == "ok" and not r.completo


def _competencia(cliente, frases, pais, idioma, excluir_page_ids, u, hoy) -> tuple[Medida, list[str], bool]:
    hoy = hoy or date.today()
    minimo = int(u["hueco.competidor_c7_min"].valor)
    intentos = int(u["hueco.intentos_para_cero"].valor)
    enlaces: list[str] = []
    vistos: dict[str, AnuncioBiblioteca] = {}
    fallos: list[str] = []
    parada = False
    incompleto = False
    hechas = 0
    for frase in frases:
        r = _buscar(cliente, pais, q=frase)
        if isinstance(r, str):
            fallos.append(f"búsqueda bloqueada o detenida ({r})")
            parada = True
            break  # no se insiste con una sesión bloqueada o parada
        enlaces.append(r.url)
        if r.estado in ("bloqueado", "error"):
            fallos.append(f"búsqueda {'bloqueada' if r.estado == 'bloqueado' else 'con error'}: {r.motivo or r.estado}")
            continue
        hechas += 1
        incompleto = incompleto or _incompleta(r)
        for a in r.anuncios:
            vistos.setdefault(a.library_id, a)

    por_pagina: dict[str, int] = {}
    dudosos: dict[str, int] = {}  # anuncios elegibles cuyo idioma no se pudo detectar
    for a in vistos.values():
        if a.page_id in excluir_page_ids or not a.activo or (hoy - a.inicio).days < _DIAS_COMPETIDOR:
            continue
        local = _idioma_de(a.texto, idioma)
        if local:
            por_pagina[a.page_id] = por_pagina.get(a.page_id, 0) + 1
        elif local is None:
            dudosos[a.page_id] = dudosos.get(a.page_id, 0) + 1
    n = float(sum(1 for c in por_pagina.values() if c >= minimo))
    posibles = sum(
        1 for p, d in dudosos.items() if por_pagina.get(p, 0) < minimo <= por_pagina.get(p, 0) + d
    )
    maximo = u["hueco.max_competencia_local"].valor
    degradada = bool(fallos) or incompleto or hechas < intentos or posibles > 0

    if n > maximo or (n > 0 and posibles == 0) or (n > 0 and degradada):
        return Medida(n, suelo=degradada), enlaces, parada
    if n + posibles > maximo:  # el idioma no detectable podría añadir competidores
        total = sum(dudosos.values())
        return _nm(f"idioma no detectable en {total} anuncios que podrían ser competencia local"), enlaces, parada
    if fallos:
        return _nm("; ".join(fallos)), enlaces, parada
    if hechas < intentos:
        return (
            _nm(f"solo hubo {hechas} de los {intentos} intentos con frases distintas que hacen falta "
                f"para confirmar que no hay competencia"),
            enlaces,
            parada,
        )
    return Medida(n, suelo=incompleto), enlaces, parada


def competencia_local(
    cliente,
    frases: list[str],
    pais: str,
    idioma: str,
    excluir_page_ids: set[str],
    u: dict[str, Umbral],
    hoy: date | None = None,
) -> Medida:
    """Páginas distintas (fuera de ``excluir_page_ids``) con ≥ ``hueco.competidor_c7_min`` anuncios
    activos de 7+ días en ``idioma``. ``suelo=True`` si alguna lectura quedó incompleta."""
    return _competencia(cliente, frases, pais, idioma, excluir_page_ids, u, hoy)[0]


def _original(cliente, page_ids, pais, idioma, hoy, u) -> tuple[Original, list[str]]:
    if not page_ids:
        return "no_medido", []
    minimo = int(u["hueco.sin_traducir_min_dias"].valor)
    enlaces: list[str] = []
    en_otro_idioma: list[AnuncioBiblioteca] = []
    sin_detectar: list[AnuncioBiblioteca] = []
    no_medido = False
    for pid in page_ids:
        r = _buscar(cliente, pais, page_id=pid)
        if isinstance(r, str):
            no_medido = True
            break
        enlaces.append(r.url)
        if r.estado in ("bloqueado", "error"):
            no_medido = True
            continue
        if _incompleta(r):
            no_medido = True  # puede haber un anuncio traducido que no se leyó
        for a in r.anuncios:
            if not a.activo:
                continue
            local = _idioma_de(a.texto, idioma)
            if local:
                return "traducido", enlaces  # un traducido leído es definitivo
            (sin_detectar if local is None else en_otro_idioma).append(a)
    if no_medido:
        return "no_medido", enlaces
    if not en_otro_idioma and not sin_detectar:
        return "ausente", enlaces
    if sin_detectar:  # cualquier anuncio en el idioma local sería «traducido», sea cual sea su edad
        return "no_medido", enlaces
    mas_viejo = max((hoy - a.inicio).days for a in en_otro_idioma)
    return ("sin_traducir" if mas_viejo >= minimo else "ausente_reciente"), enlaces


def original_presente(
    cliente, page_ids: list[str], pais: str, idioma: str, hoy: date, u: dict[str, Umbral]
) -> Original:
    """Estado del original en ``pais``. Fuera de la UE solo hay anuncios activos: «ausente» significa
    «sin anuncio activo ahora», no «nunca existió». Un texto indetectable no cuenta como traducido."""
    return _original(cliente, page_ids, pais, idioma, hoy, u)[0]


def hay_hueco(comp: Medida, orig: str, u: dict[str, Umbral]) -> bool | None:
    if orig == "traducido":
        return False  # regla de Tomi: no lanzar donde ya está traducido
    if comp.valor is None or orig == "no_medido":
        return None
    if comp.valor <= u["hueco.max_competencia_local"].valor:
        # Con lectura incompleta un competidor puede estar más allá de lo leído.
        return None if comp.suelo else True
    return False


def motivo_hueco(comp: Medida, orig: str, u: dict[str, Umbral]) -> str | None:
    """Por qué ``hay_hueco`` no decide (None si decide o no hace falta explicarlo)."""
    if hay_hueco(comp, orig, u) is not None:
        return "Fuera de la UE solo hay anuncios activos: «ausente» no prueba que nunca existiera." if orig.startswith("ausente") else None
    if comp.valor is None:
        return comp.motivo
    if orig == "no_medido":
        return "no medido: no se pudo determinar si el original está traducido en este país"
    return _MOTIVO_SUELO


def hueco_pais(
    cliente,
    frases: list[str],
    page_ids: list[str],
    pais: str,
    idioma: str,
    excluir_page_ids: set[str],
    hoy: date,
    u: dict[str, Umbral],
) -> HuecoPais:
    comp, e1, parada = _competencia(cliente, frases, pais, idioma, excluir_page_ids, u, hoy)
    if parada:  # sesión bloqueada o presupuesto agotado: no se sigue buscando
        orig, e2 = "no_medido", []
    else:
        orig, e2 = _original(cliente, page_ids, pais, idioma, hoy, u)
    return HuecoPais(pais, comp, orig, hay_hueco(comp, orig, u), e1 + e2, motivo_hueco(comp, orig, u))
