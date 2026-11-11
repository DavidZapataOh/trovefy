import pathlib

import pytest
from trovefy.caza.filtros import Descarte
from trovefy.caza.nota import calcular_nota, decidir, lineal, log_share
from trovefy.caza.senales import Medida, Senales
from trovefy.config.umbrales import cargar

U = cargar(pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml")
NM = Medida(None, "no medido: prueba")


def senales(**kw):
    base = {"c8": NM, "c7": NM, "total": NM, "supervivencia": NM, "escalonado_semanas": NM, "edad_max_dias": NM,
                "vida_mediana_dias": NM, "crecimiento_7d": NM, "expansion": NM, "duplicacion": NM, "alcance_ue": NM,
                "idiomas": [], "banderas": []}
    base.update(kw)
    return Senales(**base)


def maximas(**kw):
    base = {"c8": Medida(50), "edad_max_dias": Medida(90), "escalonado_semanas": Medida(6),
                "crecimiento_7d": Medida(1.0), "expansion": Medida(8), "duplicacion": Medida(20),
                "supervivencia": Medida(1.0)}
    base.update(kw)
    return senales(**base)


def test_nota_reescala_sin_crecimiento():
    n = calcular_nota(senales(c8=Medida(15), supervivencia=Medida(0.5)), U)
    assert n.valor == pytest.approx(67.10, abs=0.01)
    assert "crecimiento_7d" in n.no_medidas


def test_nota_maxima_y_decision_a():
    s = maximas()
    n = calcular_nota(s, U)
    assert n.valor == pytest.approx(100.0)
    assert decidir(n, s.c8, "tomi", True, None, U)[0] == "A"
    assert decidir(n, s.c8, "tomi", None, None, U) == ("B", "sin hueco comprobado")
    assert decidir(n, s.c8, "tomi", True, None, U, landing="dudoso")[0] == "B"


def test_cayendo_multiplica():
    s = maximas(crecimiento_7d=Medida(-0.5), banderas=["cayendo"])
    n = calcular_nota(s, U)
    assert n.valor == pytest.approx(41.67, abs=0.01) and ("cayendo", 0.5) in n.multiplicadores
    assert decidir(n, s.c8, "tomi", True, None, U)[0] == "observar"


def test_nada_medido():
    n = calcular_nota(senales(), U)
    assert n.valor is None and n.desglose == []
    assert decidir(n, NM, "tomi", True, None, U)[0] == "observar"


def test_funciones_base():
    assert log_share(50, 50) == 1 and log_share(500, 50) == 1
    assert lineal(3, 6) == 0.5 and lineal(60, 6) == 1


def test_longevidad_media_de_edad_y_semanas():
    n = calcular_nota(senales(edad_max_dias=Medida(45), escalonado_semanas=Medida(6)), U)
    assert n.valor == pytest.approx(75.0)  # (0.5*0.5 + 0.5*1) = 0.75 sobre el único peso medido
    n2 = calcular_nota(senales(edad_max_dias=Medida(45)), U)
    assert n2.valor == pytest.approx(50.0)  # una sola mitad medida: se usa sola


def test_suelo_se_puntua_como_su_valor():
    a = calcular_nota(senales(c8=Medida(15, suelo=True)), U)
    b = calcular_nota(senales(c8=Medida(15)), U)
    assert a.valor == b.valor


def test_multiplicadores_supervivencia_y_vida_corta():
    n = calcular_nota(maximas(supervivencia=Medida(0.1), vida_mediana_dias=Medida(7)), U)
    assert ("supervivencia_baja", 0.7) in n.multiplicadores
    assert ("vida_corta", 0.7) in n.multiplicadores


def test_descartada():
    n = calcular_nota(maximas(), U)
    assert decidir(n, maximas().c8, "tomi", True, Descarte("x", "d"), U)[0] == "descartada"


def test_a_exige_c8_del_perfil():
    # bajo el mínimo del perfil nunca es A ni B, aunque la nota dé para A
    s = maximas(c8=Medida(15))
    n = calcular_nota(s, U)
    assert decidir(n, s.c8, "europa-caro", True, None, U) == ("observar", "C8 15 < 20 del perfil europa-caro")


@pytest.mark.parametrize("c8", [5, 8, 11])
def test_c8_suelo_que_no_alcanza_es_observar_y_volver_a_medir(c8):
    # caza real del 2026-11-11: C8 ≥ 5, ≥ 8 y ≥ 11 (lecturas parciales) salían como B en el perfil tomi
    s = maximas(c8=Medida(c8, suelo=True))
    n = calcular_nota(s, U)
    for hueco, landing in ((True, "modelable"), (None, "dudoso")):
        est, porque = decidir(n, s.c8, "tomi", hueco, None, U, landing=landing)
        assert est == "observar"
        assert porque.startswith(f"C8 ≥ {c8} no alcanza 15 del perfil tomi: lectura parcial, volver a medir")


def test_c8_suelo_que_alcanza_sigue_siendo_a_o_b():
    ok = maximas(c8=Medida(20, suelo=True))
    n = calcular_nota(ok, U)
    assert decidir(n, ok.c8, "tomi", True, None, U)[0] == "A"
    assert decidir(n, ok.c8, "tomi", None, None, U) == ("B", "sin hueco comprobado")
    justo = maximas(c8=Medida(15))
    assert decidir(calcular_nota(justo, U), justo.c8, "tomi", True, None, U)[0] == "A"


def test_c8_exacto_bajo_el_minimo_con_otras_faltas_es_observar():
    s = maximas(c8=Medida(9))
    est, porque = decidir(calcular_nota(s, U), s.c8, "tomi", None, None, U, landing="dudoso")
    assert est == "observar"
    assert porque == "C8 9 < 15 del perfil tomi; sin hueco comprobado; landing dudosa"


def test_santino_usa_c7():
    s = maximas(c7=Medida(10))
    n = calcular_nota(s, U)
    assert decidir(n, s.c8, "santino", True, None, U, c7=s.c7) == ("observar", "C7 10 < 30 del perfil santino")
    s2 = maximas(c7=Medida(30))
    assert decidir(calcular_nota(s2, U), s2.c8, "santino", True, None, U, c7=s2.c7)[0] == "A"
