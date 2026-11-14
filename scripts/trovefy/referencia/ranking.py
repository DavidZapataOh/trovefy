"""Ranking puro de anuncios de referencia: ganadores (llevan días activos) y en test.

Idea y fórmula tomadas de cuongbigdigi/meta-ads-library-skill @ aabd8ac (MIT),
``tools/ad-library/rank.js:23-30``; reimplementadas aquí, sin copiar código.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from trovefy.caza.modelo import AnuncioBiblioteca

if TYPE_CHECKING:
    from trovefy.referencia.config import UmbralesReferencia

Estado = Literal["ganador", "en_test", "nuevo", "no_medido"]

_ORDEN_ESTADO = {"ganador": 0, "en_test": 1, "nuevo": 2, "no_medido": 3}


@dataclass(frozen=True)
class Puesto:
    library_id: str
    collation_id: str | None
    dias: int | None
    variantes: int
    variantes_cota: bool
    puntuacion: int | None
    estado: Estado
    motivo: str | None
    ids_grupo: tuple[str, ...]


def dias_activo(a: AnuncioBiblioteca, hoy: date) -> int | None:
    """Días de vida medidos. Con el anuncio activo nunca se usa ``fin`` (es solo la fecha programada)."""
    if a.activo:
        return (hoy - a.inicio).days
    if a.fin is not None:
        return (a.fin - a.inicio).days
    return None


def _puesto(grupo: list[AnuncioBiblioteca], hoy: date, u: UmbralesReferencia) -> Puesto:
    medidos = [(dias_activo(a, hoy), a) for a in grupo]
    # Representante: el de más días; los no medidos van al final, empate por id.
    medidos.sort(key=lambda t: (t[0] is None, -(t[0] or 0), t[1].library_id))
    dias, rep = medidos[0]
    counts = [a.collation_count for a in grupo if a.collation_count is not None]
    cota = not counts
    variantes = max(counts) if counts else len(grupo)
    ids = tuple(sorted(a.library_id for a in grupo))
    puntuacion: int | None = None
    motivo: str | None = None
    estado: Estado
    if dias is None:
        estado = "no_medido"
        motivo = "no medido: anuncio inactivo sin fecha de fin"
    elif dias >= u.min_dias:
        estado = "ganador"
        puntuacion = dias + u.peso_variantes * min(variantes, u.max_variantes)
    elif variantes >= u.en_test_min_variantes:
        estado = "en_test"
    else:
        estado = "nuevo"
    return Puesto(
        rep.library_id,
        rep.collation_id,
        dias,
        variantes,
        cota,
        puntuacion,
        estado,
        motivo,
        ids,
    )


def rankear(
    anuncios: list[AnuncioBiblioteca], hoy: date, u: UmbralesReferencia
) -> list[Puesto]:
    grupos: dict[str, list[AnuncioBiblioteca]] = {}
    for a in anuncios:
        clave = f"c:{a.collation_id}" if a.collation_id else f"a:{a.library_id}"
        grupos.setdefault(clave, []).append(a)
    puestos = [_puesto(g, hoy, u) for g in grupos.values()]
    puestos.sort(
        key=lambda p: (
            _ORDEN_ESTADO[p.estado],
            -(p.puntuacion or 0),
            -(p.dias or 0),
            p.library_id,
        )
    )
    return puestos


def top(puestos: list[Puesto], n: int) -> list[Puesto]:
    return [p for p in puestos if p.estado == "ganador"][:n]
