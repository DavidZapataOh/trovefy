import pytest
from trovify.auditoria.paises import (
    PaisAuditado,
    no_tirar,
    puntuar_pais,
    recomendar,
    tres_senales,
)
from trovify.caza.hueco import HuecoPais
from trovify.caza.senales import Medida


def hp(pais, comp, orig, hueco):
    return HuecoPais(pais, Medida(comp) if comp is not None else Medida(None, "x"), orig, hueco, [])


def test_puntuacion_reescalada(umbrales):
    nota, _ = puntuar_pais(hp("RO", 0, "sin_traducir", True), Medida(1.0), umbrales)
    assert nota == pytest.approx(100.0)  # solo hueco (30) y precio (15) medidos
    nota, _ = puntuar_pais(hp("IT", 0, "ausente", True), Medida(0.5), umbrales)
    assert nota == pytest.approx(100 * (30 + 15 * 0.5) / 45)


def test_desglose_dice_lo_no_medido(umbrales):
    _, d = puntuar_pais(hp("RO", 0, "ausente", True), Medida(1.0), umbrales)
    nombres = [x[0] for x in d]
    assert nombres == ["hueco", "precio", "demanda", "cpm", "cultural"]
    assert [x[2] for x in d] == [1, 1.0, None, None, None]
    assert [x[1] for x in d] == [30, 15, 35, 10, 10]


def test_nada_medido_es_none(umbrales):
    nota, _ = puntuar_pais(hp("RO", None, "no_medido", None), Medida(None, "no medido: x"), umbrales)
    assert nota is None


def test_hueco_falso_puntua_cero(umbrales):
    nota, _ = puntuar_pais(hp("FR", 0, "traducido", False), Medida(1.0), umbrales)
    assert nota == pytest.approx(100 * 15 / 45)


def test_no_tirar():
    assert "traducido" in no_tirar(hp("FR", 0, "traducido", False))
    assert no_tirar(hp("RO", 0, "sin_traducir", True)) is None
    assert no_tirar(hp("DE", 3, "ausente", False)) == "hay competencia local (3 anunciantes)"
    assert no_tirar(hp("DE", None, "ausente", None)) is None


def pa(pais, nota, hueco, nt=None):
    return PaisAuditado(pais, hp(pais, 0, "ausente", hueco), Medida(13.9), Medida(1), nota, [], nt)


def test_recomendacion():
    assert recomendar([pa("RO", 90, True), pa("IT", 80, True), pa("FR", 99, False, "traducido")])[:2] == ("RO", "IT")


def test_un_solo_pais_sin_reserva():
    p, r, _ = recomendar([pa("RO", 90, True)])
    assert (p, r) == ("RO", None)


def test_no_tirar_excluye_aunque_hueco():
    p, _, _ = recomendar([pa("RO", 90, True, "el original ya anuncia traducido")])
    assert p is None


def test_sin_hueco_no_recomienda():
    p, r, explicacion = recomendar([pa("RO", 90, None), pa("FR", 99, False, "traducido")])
    assert p is None and r is None and "hueco comprobado" in explicacion


def test_tres_senales():
    ps = [pa("RO", 90, True)]
    s = tres_senales("A", ps)
    assert s == {"ya_se_vende": True, "hueco_por_pais": True, "se_puede_mejorar": None}
    assert tres_senales("C", [pa("RO", 1, False)])["ya_se_vende"] is False
    assert tres_senales("A", [pa("RO", 1, None)])["hueco_por_pais"] is None
    assert tres_senales("A", [pa("RO", 1, False)])["hueco_por_pais"] is False
