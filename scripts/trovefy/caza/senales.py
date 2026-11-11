"""Señales por oferta y país (§4.3). Lo que no se puede medir se dice («no medido: …»), nunca 0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from trovefy.caza.modelo import AnuncioBiblioteca
from trovefy.caza.oferta import Oferta
from trovefy.caza.snapshots import Snapshot
from trovefy.config.mercados import Mercado
from trovefy.config.umbrales import Umbral
from trovefy.idioma import detectar

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
    # Detalle de las banderas que lo llevan (``precio_bajo``: precio, USD, fecha del BCE y umbral).
    detalles_banderas: dict[str, str] = field(default_factory=dict)


def _edad(a: AnuncioBiblioteca, hoy: date) -> int:
    return (hoy - a.inicio).days


def _crecimiento(
    n_hoy: int | None, historial: list[Snapshot], hoy: date
) -> Medida:
    if n_hoy is None:
        return _nm("muestra parcial (lectura parcial sin total exacto de Meta)")
    en_ventana = [s for s in historial if _VENTANA_FOTO[0] <= (hoy - s.dia).days <= _VENTANA_FOTO[1]]
    if not en_ventana:
        return _nm("primera caza" if not historial else "sin foto de hace 6–8 días")
    con_total = [s for s in en_ventana if s.total is not None]
    if not con_total:
        return _nm("la foto de hace 7 días no tiene total exacto")
    foto = min(con_total, key=lambda s: (abs((hoy - s.dia).days - 7), s.dia))
    n_foto = foto.total
    if n_foto == 0:
        return _nm("la foto de hace una semana tenía 0 anuncios activos")
    return Medida((n_hoy - n_foto) / n_foto)


def crecimiento(n_hoy: int | None, fotos: list, hoy: date) -> Medida:
    """Crecimiento contra la foto de hace 6–8 días (la más cercana a 7). ``fotos`` tienen ``dia`` y
    ``total`` exacto. Lo usa también el crecimiento de una página (todas sus ofertas)."""
    return _crecimiento(n_hoy, fotos, hoy)


VENTANA_FOTO = _VENTANA_FOTO


def calcular_senales(
    oferta: Oferta,
    pais: str,
    hoy: date,
    historial: list[Snapshot],
    inactivos: list[AnuncioBiblioteca] | None,
    total_aprox: int | None,
    completo: bool | None = None,
    *,
    total_meta: int | None = None,
    umbrales: dict[str, Umbral],
    vistos: tuple[int | None, int | None, date | None] | None = None,
    mercados: dict[str, Mercado] | None = None,
) -> Senales:
    """Señales de ``oferta`` en ``pais`` (``"ALL"`` = todos los países).

    - ``completo``: ``ResultadoBusqueda.completo``. Las cifras son suelo («≥») si ``completo`` es
      False o ``total_aprox`` supera los anuncios cargados; None = desconocido, y entonces solo
      decide ``total_aprox``.
    - ``total_meta``: número EXACTO de anuncios activos de esta oferta en ``pais`` según Meta (suma
      de las páginas de la oferta); nunca una cota ni un tope: si Meta solo dijo «más de N», el
      llamador pasa None. Con él, ``total`` es exacto (``suelo=False``) y el crecimiento se mide
      aunque la lectura sea parcial; sin él, el crecimiento usa los anuncios cargados solo si la
      lectura es completa.
    - Contrato de las fotos (Tarea 8): ``Snapshot.total`` se escribe solo desde una cuenta exacta
      (``total_meta`` o los cargados de una lectura completa), si no NULL; ``Snapshot.activos`` es
      NULL en lecturas parciales. El crecimiento compara contra ``foto.total`` (una foto sin ``total`` da «no medido»).
    - ``inactivos``: la Tarea 8 pasa None si esa búsqueda fue parcial (la vida mediana saldría
      sesgada hacia anuncios longevos).
    - ``pais="ALL"`` no evalúa ``moneda_distinta`` (no hay una moneda de país única).
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

    if not en_pais:
        sup = _nm("sin anuncios cargados")
    elif incompleto:
        # Los primeros por impresiones sesgan hacia anuncios viejos: no es una cifra, solo cota.
        if total_meta:  # c7 cargados / total exacto de Meta es una cota inferior real
            cota = f"{len(c7) / total_meta:.2f}".replace(".", ",")
            sup = _nm(f"muestra parcial (≥ {cota})")
        else:
            sup = _nm("muestra parcial")
    else:
        sup = Medida(len(c7) / len(en_pais))

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

    if total_meta is not None:
        n_hoy: int | None = total_meta
    else:
        n_hoy = None if incompleto else len(activos)
    crec = _crecimiento(n_hoy, historial, hoy)
    if total_meta is not None:
        senales_medida["total"] = Medida(float(total_meta))

    candidatos_idioma = sorted({m.idioma for m in (mercados or {}).values()})
    idiomas: list[str] = []
    if candidatos_idioma:
        for a in todos:
            i = detectar(a.texto, candidatos_idioma)
            if i and i not in idiomas:
                idiomas.append(i)
        paises = {a.pais for a in todos}
        expansion = Medida(float(len(paises) + len(idiomas) + len(oferta.page_ids)), suelo=suelo)
    else:  # sin mercados no se cuentan idiomas: países + páginas es una cota inferior
        paises = {a.pais for a in todos}
        expansion = Medida(float(len(paises) + len(oferta.page_ids)), suelo=True)

    if not c7:
        dup = _nm("cohorte C7 vacía")
    elif all(a.collation_count is None for a in c7):
        dup = _nm("la Biblioteca no informa collation_count")
    else:
        faltan = any(a.collation_count is None for a in c7)
        dup = Medida(
            float(sum(max((a.collation_count or 1) - 1, 0) for a in c7)), suelo=suelo or faltan
        )

    alcance = _nm("requiere /ads_archive (paso 15)")

    nuevos = _nm("primera caza")
    parados = _nm("primera caza")
    if vistos is not None and incompleto is False:
        nuevos = parados = _nm("sin corrida completa previa")
    if incompleto:
        nuevos = parados = _nm("muestra parcial")
    if not incompleto and vistos is not None and vistos[0] is not None and vistos[1] is not None:
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
