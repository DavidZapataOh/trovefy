from __future__ import annotations

from datetime import date

from fixtures.referencia.anuncios_ranking import E1, E2, HOY, A, B, C, D, F, anuncio
from trovefy.referencia.config import UmbralesReferencia
from trovefy.referencia.ranking import dias_activo, rankear, top

U = UmbralesReferencia(
    min_dias=7,
    max_variantes=30,
    peso_variantes=2,
    en_test_min_variantes=5,
    top=10,
    retencion_dias=30,
)


def test_ranking_fixture():
    p = rankear([A, B, C, D, F], HOY, U)
    assert [(x.library_id, x.puntuacion, x.estado) for x in p] == [
        ("A", 97, "ganador"),
        ("B", 84, "ganador"),
        ("F", 47, "ganador"),
        ("C", None, "en_test"),
        ("D", None, "nuevo"),
    ]


def test_variantes_cota_inferior():
    (e,) = rankear([E1, E2], HOY, U)
    assert (e.variantes, e.variantes_cota, e.puntuacion, e.ids_grupo) == (
        2,
        True,
        16,
        ("E1", "E2"),
    )


def test_variantes_exactas_sin_cota():
    (a,) = rankear([A], HOY, U)
    assert (a.variantes, a.variantes_cota, a.dias) == (12, False, 73)


def test_inactivo_sin_fin_no_medido():
    (g,) = rankear([anuncio("G", date(2026, 9, 1), activo=False)], HOY, U)
    assert (
        g.estado == "no_medido"
        and g.puntuacion is None
        and g.motivo.startswith("no medido")
    )


def test_dias_activo_ignora_fin_en_activos():
    a = anuncio("X", date(2026, 11, 1), fin=date(2026, 12, 31))
    assert dias_activo(a, HOY) == 12


def test_desempate_determinista():
    # 20 + 2*5 = 30 en ambos con 20 días; con 25 días y 2*2.5... usamos días distintos y puntuación igual
    a = anuncio("Z", date(2026, 10, 24), collation_id="z", count=5)  # 20 días -> 30
    b = anuncio(
        "Y", date(2026, 10, 24), collation_id="y", count=5
    )  # igual -> id menor primero
    c = anuncio(
        "W", date(2026, 10, 26), collation_id="w", count=6
    )  # 18 días -> 30, menos días
    assert [x.library_id for x in rankear([a, b, c], HOY, U)] == ["Y", "Z", "W"]


def test_top_solo_ganadores():
    assert [x.library_id for x in top(rankear([A, B, C, D, F], HOY, U), 2)] == [
        "A",
        "B",
    ]
    assert [x.library_id for x in top(rankear([A, C, D], HOY, U), 5)] == ["A"]
