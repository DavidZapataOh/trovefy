"""Señales por oferta y país (§4.3). Lo que no se puede medir se dice («no medido: …»), nunca 0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from trovify.caza.modelo import AnuncioBiblioteca
from trovify.caza.oferta import Oferta
from trovify.caza.snapshots import Snapshot
from trovify.config.mercados import Mercado
from trovify.config.umbrales import Umbral
from trovify.idioma import detectar

# Ventana de la foto de comparación del crecimiento: hace 6 a 8 días (se toma la más cercana a 7).
_VENTANA_FOTO = (6, 8)


@dataclass(frozen=True)
class Medida:
    """Una señal. ``valor=None`` exige ``motivo`` («no medido: …»); ``suelo=True`` significa «≥»."""

    valor: float | None
    motivo: str | None = None
    suelo: bool = False

    def __post_init__(self) -> None:
        if self.valor is None and not self.motivo:
            raise ValueError("una Medida sin valor necesita un motivo («no medido: …»)")


def _nm(motivo: str) -> Medida:
    return Medida(None, f"no medido: {motivo}")


@dataclass
class Senales:
    c8: Medida
    c7: Medida
    total: Medida
    supervivencia: Medida
    escalonado_semanas: Medida
    edad_max_dias: Medida
    vida_mediana_dias: Medida
    crecimiento_7d: Medida
    expansion: Medida
    duplicacion: Medida
    alcance_ue: Medida
    idiomas: list[str] = field(default_factory=list)
    banderas: list[str] = field(default_factory=list)
    # Últimos y con valor por defecto: se rellenan solo desde lecturas completas con corrida previa.
    nuevos: Medida = field(default_factory=lambda: _nm("primera caza"))
    parados: Medida = field(default_factory=lambda: _nm("primera caza"))


def _edad(a: AnuncioBiblioteca, hoy: date) -> int:
    return (hoy - a.inicio).days


def _crecimiento(
    activos_hoy: int, historial: list[Snapshot], hoy: date, incompleto: bool
) -> Medida:
    if incompleto:
        return _nm("muestra parcial (la lectura no llegó a todos los anuncios)")
    candidatas = [
        s for s in historial
        if _VENTANA_FOTO[0] <= (hoy - s.dia).days <= _VENTANA_FOTO[1] and s.activos is not None
    ]
    if not candidatas:
        return _nm("primera caza" if not historial else "sin foto de hace 6–8 días")
    foto = min(candidatas, key=lambda s: (abs((hoy - s.dia).days - 7), s.dia))
    if foto.activos == 0:
        return _nm("la foto de hace una semana tenía 0 anuncios activos")
    return Medida((activos_hoy - foto.activos) / foto.activos)


def calcular_senales(
    oferta: Oferta,
    pais: str,
    hoy: date,
    historial: list[Snapshot],
    inactivos: list[AnuncioBiblioteca] | None,
    total_aprox: int | None,
    completo: bool | None = None,
    *,
    umbrales: dict[str, Umbral],
    vistos: tuple[int | None, int | None, date | None] | None = None,
    mercados: dict[str, Mercado] | None = None,
) -> Senales:
    """Señales de ``oferta`` en ``pais`` (``"ALL"`` = todos los países).

    - ``completo``: ``ResultadoBusqueda.completo``. Las cifras son suelo («≥») si ``completo`` es
      False o ``total_aprox`` supera los anuncios cargados; None = desconocido, y entonces solo
      decide ``total_aprox``.
    - ``vistos``: ``(nuevos, parados, dia_anterior)`` ya calculado por el llamador con
      ``snapshots.registrar_vistos(..., completo=True)`` y ``snapshots.dia_anterior``. Aquí nunca
      se calculan desde una lectura parcial: con ``completo=False`` o sin datos quedan «no medido».
      El motivo indica la ventana («desde AAAA-MM-DD»).
    - ``umbrales``: contenido de ``config/umbrales.yaml`` (``caza.crecimiento.acelerando`` y
      ``caza.crecimiento.cayendo`` fijan las banderas).
    - ``mercados``: país → moneda e idioma; sin ellos no se detectan idiomas (``expansion`` queda
      «no medido») ni se evalúa ``moneda_distinta``.
    """
    todos = list(oferta.anuncios)
    en_pais = [a for a in todos if pais == "ALL" or a.pais == pais]
    activos = [a for a in en_pais if a.activo]
    incompleto = completo is False or (total_aprox is not None and total_aprox > len(en_pais))

    c8 = [a for a in activos if _edad(a, hoy) >= 8]
    c7 = [a for a in activos if _edad(a, hoy) >= 7]
    suelo = incompleto

    senales_medida = {
        "c8": Medida(float(len(c8)), suelo=suelo),
        "c7": Medida(float(len(c7)), suelo=suelo),
        "total": Medida(float(len(en_pais)), suelo=suelo),
    }

    if en_pais:
        sup = Medida(
            len(c7) / len(en_pais),
            "sobre una muestra parcial" if incompleto else None,
        )
    else:
        sup = _nm("sin anuncios cargados")

    semanas = {a.inicio.isocalendar()[:2] for a in c7}
    escalonado = Medida(float(len(semanas)), suelo=suelo) if c7 else _nm("sin anuncios con 7 días o más")

    edad_max = (
        Medida(float(max(_edad(a, hoy) for a in activos)), suelo=suelo)
        if activos
        else _nm("sin anuncios activos")
    )

    if inactivos is None:
        vida = _nm("sin búsqueda de inactivos")
    else:
        vidas = [
            (a.fin - a.inicio).days
            for a in inactivos
            if not a.activo and a.fin is not None and (pais == "ALL" or a.pais == pais)
        ]
        vida = Medida(float(median(vidas)), suelo=False) if vidas else _nm("sin anuncios inactivos con fecha de fin")

    crec = _crecimiento(len(activos), historial, hoy, incompleto)

    candidatos_idioma = sorted({m.idioma for m in (mercados or {}).values()})
    idiomas: list[str] = []
    if candidatos_idioma:
        for a in todos:
            i = detectar(a.texto, candidatos_idioma)
            if i and i not in idiomas:
                idiomas.append(i)
        paises = {a.pais for a in todos}
        expansion = Medida(float(len(paises) + len(idiomas) + len(oferta.page_ids)))
    else:
        expansion = _nm("sin mercados para detectar idiomas")

    if not c7:
        dup = _nm("cohorte C7 vacía")
    elif all(a.collation_count is None for a in c7):
        dup = _nm("la Biblioteca no informa collation_count")
    else:
        dup = Medida(float(sum(max((a.collation_count or 1) - 1, 0) for a in c7)), suelo=suelo)

    alcance = _nm("requiere /ads_archive (paso 15)")

    nuevos = _nm("primera caza")
    parados = _nm("primera caza")
    if completo is False:
        nuevos = parados = _nm("muestra parcial")
    elif vistos is not None and vistos[0] is not None and vistos[1] is not None:
        ventana = f"desde {vistos[2].isoformat()}" if vistos[2] else None
        nuevos = Medida(float(vistos[0]), ventana)
        parados = Medida(float(vistos[1]), ventana)

    banderas: list[str] = []
    if crec.valor is not None:
        if crec.valor >= umbrales["caza.crecimiento.acelerando"].valor:
            banderas.append("acelerando")
        if crec.valor <= umbrales["caza.crecimiento.cayendo"].valor:
            banderas.append("cayendo")
    destino = oferta.destino
    mercado = (mercados or {}).get(pais)
    if destino is not None and destino.moneda and mercado is not None and destino.moneda != mercado.moneda:
        banderas.append("moneda_distinta")

    return Senales(
        c8=senales_medida["c8"],
        c7=senales_medida["c7"],
        total=senales_medida["total"],
        supervivencia=sup,
        escalonado_semanas=escalonado,
        edad_max_dias=edad_max,
        vida_mediana_dias=vida,
        crecimiento_7d=crec,
        expansion=expansion,
        duplicacion=dup,
        alcance_ue=alcance,
        idiomas=idiomas,
        banderas=banderas,
        nuevos=nuevos,
        parados=parados,
    )
