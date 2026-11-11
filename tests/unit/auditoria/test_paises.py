import pytest
from trovefy.auditoria.paises import (
    PaisAuditado,
    no_tirar,
    puntuar_pais,
    recomendar,
    tres_senales,
)
from trovefy.caza.hueco import HuecoPais
from trovefy.caza.senales import Medida


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
    assert [x[3] for x in d] == [
        None,
        None,
        "no medido: requiere /ads_archive",
        "no medido: sin historial en la cuenta",
        "no medido: lo valora el usuario",
    ]


def test_motivos_de_hueco_y_precio_sin_medir(umbrales):
    h = HuecoPais("RO", Medida(None, "x"), "no_medido", None, [], motivo="no medido: sesión bloqueada")
    _, d = puntuar_pais(h, Medida(None, "no medido: sin cambio de referencia para MDL"), umbrales)
    assert d[0][3] == "no medido: sesión bloqueada"
    assert d[1][3] == "no medido: sin cambio de referencia para MDL"
    h2 = HuecoPais("RO", Medida(None, "x"), "no_medido", None, [])
    assert puntuar_pais(h2, Medida(1.0), umbrales)[1][0][3] == "no medido: hueco sin comprobar"
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
    h = hp("DE", 3, "ausente", False)
    h.competencia = Medida(3, suelo=True)
    assert no_tirar(h) == "hay competencia local (≥3 anunciantes)"
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


def test_empate_total_no_recomienda_por_orden_alfabetico():
    a = [pa("IT", 80, True), pa("RO", 80, True), pa("BG", 80, True)]
    for orden in (a, list(reversed(a))):
        p, r, texto = recomendar(orden)
        assert (p, r) == (None, None)
        assert "empate: elige tú" in texto and "BG, IT y RO" in texto
        assert "mejor" not in texto


def pe(pais, nota, original="ausente", comp=0, precio=1.0):
    h = HuecoPais(pais, Medida(comp), original, True, [])
    return PaisAuditado(pais, h, Medida(13.9), Medida(precio), nota, [], None)


def test_empate_se_rompe_por_el_original_sin_traducir():
    p, r, texto = recomendar([pe("BG", 100), pe("RO", 100, "sin_traducir"), pe("CZ", 90)])
    assert p == "RO" and r == "BG"
    assert "empata" in texto and "sin traducir" in texto and "mejor" not in texto


def test_empate_se_rompe_por_menos_competencia():
    p, _, texto = recomendar([pe("BG", 100, comp=1), pe("RO", 100, comp=0)])
    assert p == "RO" and "competencia local" in texto


def test_empate_se_rompe_por_precio_soportable():
    p, _, texto = recomendar([pe("BG", 100, precio=0.5), pe("RO", 100, precio=1.0)])
    assert p == "RO" and "precio soportable" in texto


def test_reserva_empatada_no_se_elige_por_orden_alfabetico():
    p, r, texto = recomendar([pe("RO", 100, "sin_traducir"), pe("BG", 100), pe("CZ", 100)])
    assert p == "RO" and r is None
    assert "reserva: empate entre BG y CZ: elige tú" in texto


def test_sin_pais_recomendable_dice_que_medir():
    from trovefy.auditoria.paises import que_medir

    sin_frases = HuecoPais("RO", Medida(None, "no medido: faltan las frases"), "ausente", None, [],
                           "no medido: faltan las frases en el idioma local de RO")
    cuota = HuecoPais("CZ", Medida(None, "x"), "no_medido", None, [], "no medido: cuota del día agotada")
    ps = [PaisAuditado("RO", sin_frases, Medida(13.9), Medida(1), 100, [], None),
          PaisAuditado("CZ", cuota, Medida(13.9), Medida(1), 100, [], None),
          pa("FR", 33, False, "el original ya anuncia traducido")]
    p, r, texto = recomendar(ps)
    assert (p, r) == (None, None)
    assert "no se recomienda ninguno" in texto and "Qué medir" in texto
    lineas = que_medir(ps)
    assert len(lineas) == 2
    assert lineas[0].startswith("RO: no medido: faltan las frases") and "--frases RO:" in lineas[0]
    assert lineas[1].startswith("CZ: no medido: cuota del día agotada") and "mañana" in lineas[1]


def test_ficha_sin_decision_de_la_caza_queda_pendiente():
    assert tres_senales("", [pa("RO", 90, True)])["ya_se_vende"] is None
    assert tres_senales(None, [pa("RO", 90, True)])["ya_se_vende"] is None
