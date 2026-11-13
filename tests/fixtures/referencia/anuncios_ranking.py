"""Anuncios sintéticos para el ranking (cuenta y página ficticias, sin datos reales)."""

from __future__ import annotations

from datetime import date

from trovefy.caza.modelo import AnuncioBiblioteca


def anuncio(
    id: str,
    inicio: date,
    activo: bool = True,
    fin: date | None = None,
    collation_id: str | None = None,
    count: int | None = None,
) -> AnuncioBiblioteca:
    return AnuncioBiblioteca(
        library_id=id,
        page_id="800000000001",
        page_name="Página ficticia",
        inicio=inicio,
        fin=fin,
        activo=activo,
        plataformas=("facebook",),
        texto="texto",
        titulo=None,
        enlace_destino=None,
        collation_id=collation_id,
        collation_count=count,
        pais="MX",
    )


HOY = date(2026, 11, 13)

A = anuncio("A", date(2026, 9, 1), collation_id="ca", count=12)
B = anuncio("B", date(2026, 10, 20), collation_id="cb", count=40)
C = anuncio("C", date(2026, 11, 10), collation_id="cc", count=5)
D = anuncio("D", date(2026, 11, 11), collation_id="cd", count=1)
F = anuncio(
    "F",
    date(2026, 8, 1),
    activo=False,
    fin=date(2026, 9, 15),
    collation_id="cf",
    count=1,
)
E1 = anuncio("E1", date(2026, 11, 1), collation_id="g")
E2 = anuncio("E2", date(2026, 11, 1), collation_id="g")
