"""Reglas de corte puras con fixtures de los vídeos (plan 23, Tarea 3)."""
from decimal import Decimal

from trovefy.leer.reglas import (
    cortes_conjuntos,
    falta_para_corte,
    veredicto_conjunto,
    veredicto_oferta,
)

from .ejemplos import ECO, U, conj, of


# C1 54:20: la tabla real
def test_c1_ad1_12_visitas_0_pi_apagar():
    v = veredicto_conjunto(conj(gasto="4.57", visitas=12, pi=0, cpc="0.16"), U, True)
    assert v.estado == "APAGAR" and "0 pagos iniciados de 12 visitas" in v.por_que


def test_c1_ad2_1_de_13_apaga_por_15():
    v = veredicto_conjunto(conj(gasto="4.27", visitas=13, pi=1, cpc="0.12"), U, True)
    assert v.estado == "APAGAR" and "1 pago iniciado de 13 visitas (7,7 %" in v.por_que


def test_c1_ad3_una_venta_mantener():
    assert veredicto_conjunto(conj(gasto="5.58", visitas=22, pi=4, ventas=1), U, True).estado == "MANTENER"


def test_cpc_alto_apagar():  # §7: US$ 3, CPC 0,7 y 0 PI
    v = veredicto_conjunto(conj(gasto="3.50", visitas=4, pi=0, cpc="0.70"), U, True)
    assert v.estado == "APAGAR" and "CPC 0,70 > 0,60" in v.por_que


def test_menos_de_3_usd_esperar():
    v = veredicto_conjunto(conj(gasto="2.99", visitas=3, pi=0, cpc="0.90"), U, True)
    assert v.estado == "ESPERAR" and "todavía no llega" in v.por_que


def test_3_usd_con_400_impresiones_y_cpc_alto_apagar():  # sin guarda de impresiones
    c = conj(gasto="3.00", visitas=2, pi=0, cpc="0.75")
    assert c.metricas.impresiones == 1000
    from dataclasses import replace

    c = replace(c, metricas=replace(c.metricas, impresiones=400))
    assert veredicto_conjunto(c, U, True).estado == "APAGAR"


def test_nunca_por_ctr():  # CTR 0,3 %, gasto 3,5, CPC 0,40, 2 PI de 8 visitas → ESPERAR
    from dataclasses import replace

    c = conj(gasto="3.50", visitas=8, pi=2, clics=9)
    c = replace(c, metricas=replace(c.metricas, impresiones=3000))
    assert c.metricas.ctr == Decimal("0.003")
    assert veredicto_conjunto(c, U, True).estado == "ESPERAR"


def test_pi_no_fiable_no_corta_por_pi():  # desvío D1
    v = veredicto_conjunto(conj(gasto="4.57", visitas=12, pi=0, cpc="0.16"), U, False)
    assert v.estado == "ESPERAR" and "desvío D1" in v.por_que
    assert veredicto_conjunto(conj(gasto="4.57", visitas=12, pi=0, cpc="0.70"), U, False).estado == "APAGAR"


def test_pi_no_fiable_en_todos_no_hay_corte():
    o = of("15", conjuntos=[conj(gasto="5", visitas=10, pi=0, cpc="0.20", sid=f"400000000000000{i}")
                            for i in range(1, 4)])
    assert cortes_conjuntos(o, U, pi_fiable=False) is None
    assert cortes_conjuntos(o, U, pi_fiable=True).ids == ("4000000000000001", "4000000000000002", "4000000000000003")


def test_cortes_solo_de_los_activos():
    o = of("10", conjuntos=[conj(gasto="5", cpc="0.80", sid="4000000000000001"),
                            conj(gasto="5", cpc="0.80", sid="4000000000000002", estado="PAUSED")])
    assert cortes_conjuntos(o, U, True).ids == ("4000000000000001",)


# L2 19:15 Trusa día 1: 20,11 gasto, 6 ventas, 104,01 → no hay corte
def test_trusa_dia1_sigue_en_test():
    e, cortes, _ = veredicto_oferta(of("20.11", ventas=6, bruto="104.01", horas=24), ECO, U, intradia=False,
                                    dias_con_ventas=1)
    assert e == "test" and cortes == []


def test_vende_tres_dias_roas_2_5_candidato():
    e, cortes, notas = veredicto_oferta(of("40", ventas=8, bruto="111.20", horas=80), ECO, U, intradia=False,
                                        dias_con_ventas=3)
    assert e == "candidato" and cortes == [] and any("candidato" in n for n in notas)


def test_dos_dias_con_ventas_no_es_candidato():
    e, _, _ = veredicto_oferta(of("40", ventas=8, bruto="111.20", horas=50), ECO, U, intradia=False,
                               dias_con_ventas=2)
    assert e == "test"


# C1 1:24:15
def test_sin_ventas_25_a_las_20h_muere_alta():
    e, c, _ = veredicto_oferta(of(gasto="25", ventas=0, horas=20), ECO, U, intradia=True)
    assert e == "muerto_sin_ventas" and c[0].prioridad == "alta" and c[0].tipo == "pausar_campana"
    assert "C1 1:24:15" in c[0].motivo


def test_sin_ventas_24_99_no_muere():
    e, c, _ = veredicto_oferta(of(gasto="24.99", ventas=0, horas=20), ECO, U, intradia=True)
    assert e == "test" and c == []
    assert falta_para_corte(of(gasto="18.80", ventas=0), U).startswith("faltan 6,20 USD")


def test_1_venta_30_gastados_roas_bajo_a_40h_no_corta():
    e, c, notas = veredicto_oferta(of("30", ventas=1, bruto="15", horas=40), ECO, U, intradia=False)
    assert e == "test" and c == [] and any("72 h" in n for n in notas)


def test_con_ventas_roas_1_2_a_80h_muere():
    e, c, _ = veredicto_oferta(of("30", ventas=3, bruto="37.60", horas=80), ECO, U, intradia=False)
    assert e == "muerto_con_ventas" and c[0].tipo == "pausar_campana"


def test_con_ventas_no_muere_intradia():
    e, c, _ = veredicto_oferta(of("30", ventas=3, bruto="37.60", horas=80), ECO, U, intradia=True)
    assert e == "test" and c == []


def test_plazo_7_dias_pausa():
    e, c, _ = veredicto_oferta(of("20", ventas=1, bruto="40", horas=7 * 24), ECO, U, intradia=False,
                               dias_con_ventas=1)
    assert e == "plazo_cumplido" and c[0].prioridad == "normal" and "C1 0:18:10" in c[0].motivo


def test_tienda_manda_sobre_pixel():
    e, c, notas = veredicto_oferta(of("26", ventas=1, bruto="13.90", pixel=0, horas=20), ECO, U, intradia=True)
    assert e != "muerto_sin_ventas" and not c and any("píxel subnotifica" in n for n in notas)


def test_gasto_cop_sin_trm_no_corta():
    e, c, notas = veredicto_oferta(of(gasto_c=-1, ventas=0, horas=20), ECO, U, intradia=True)
    assert e == "test" and c == [] and any("gasto en USD no medido" in n for n in notas)


def test_techo_cumplido_se_dice():
    _, c, notas = veredicto_oferta(of("100", ventas=1, bruto="13.90", horas=30), ECO, U, intradia=True)
    assert any("techo cumplido" in n for n in notas) and not c


def test_sin_economia_no_corta_con_ventas_pero_si_sin_ventas():
    from .ejemplos import ECO_NO

    e, c, notas = veredicto_oferta(of("30", ventas=3, bruto="37.60", horas=80), ECO_NO, U, intradia=False)
    assert e == "test" and not c and any("ROAS neto no medido" in n for n in notas)
    e, c, _ = veredicto_oferta(of("25", ventas=0, horas=5), ECO_NO, U, intradia=True)
    assert e == "muerto_sin_ventas"
