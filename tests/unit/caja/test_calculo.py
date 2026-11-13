from ejemplos_caja import CFG, con_test, g, mov
from trovefy.caja.calculo import calcular
from trovefy.caja.gasto import GastoTest


def test_280_da_9_huecos():
    e = calcular(CFG, [], [])
    assert e.restante["tests"] == 28000 and e.huecos == 9 and e.vivos == 0


def test_prorroga_quita_un_hueco():
    assert calcular(CFG, [], []).huecos_con_prorroga == 8


def test_test_vivo_reserva_su_techo():
    e = calcular(con_test("vivo"), [], [g(1200)])
    assert (e.comprometido, e.huecos, e.vivos) == (1800, 8, 1)


def test_prorroga_concedida_reserva_55():
    e = calcular(con_test("vivo", prorroga=True), [], [g(3100)])
    assert (e.comprometido, e.restante["tests"], e.huecos) == (2400, 22500, 7)


def test_sobregasto_de_meta_cuenta_entero():
    e = calcular(con_test("cerrado"), [], [g(3120)])
    assert e.restante["tests"] == 24880


def test_sobregasto_de_tests_con_motivo():
    e = calcular(CFG, [], [GastoTest("sin-asignar", "—", 30000, None)])
    assert e.restante["tests"] == -2000 and e.huecos == 0
    assert any("sobregasto" in m for m in e.motivos)


def test_mover_reserva_a_tests():
    e = calcular(CFG, [mov("reserva", "tests", 5000)], [])
    assert (e.asignado["reserva"], e.asignado["tests"], e.huecos) == (15000, 33000, 11)


def test_herramientas_y_reserva():
    e = calcular(CFG, [mov("", "", 700, "herramienta")], [])
    assert e.gastado["herramientas"] == 700 and e.restante["herramientas"] == 1300
    assert e.gastado["reserva"] == 0 and e.restante["reserva"] == 20000


def test_gasto_no_medido_arrastra_none():
    e = calcular(CFG, [], [GastoTest("p", "CO", None, "no medido: x")])
    assert e.gastado["tests"] is None and e.restante["tests"] is None
    assert (
        e.huecos is None
        and e.huecos_con_prorroga is None
        and "no medido: x" in e.motivos
    )


def test_test_vivo_sin_gasto_no_medido():
    e = calcular(con_test("vivo"), [], [])
    assert e.comprometido is None and e.huecos is None
    assert any("sin gasto registrado de p1 CO" in m for m in e.motivos)


def test_techo_cero_no_medido():
    from dataclasses import replace

    e = calcular(replace(CFG, techo_test=0), [], [])
    assert e.huecos is None and e.huecos_con_prorroga is None
    assert any("techo_test" in m for m in e.motivos)


def test_sobregasto_de_herramientas_con_motivo():
    e = calcular(CFG, [mov("", "", 2500, "herramienta")], [])
    assert e.restante["herramientas"] == -500
    assert any("sobregasto de herramientas" in m for m in e.motivos)


def test_sobregasto_de_reserva_con_motivo():
    e = calcular(CFG, [mov("reserva", "tests", 25000)], [])
    assert e.restante["reserva"] == -5000
    assert any("sobregasto de reserva" in m for m in e.motivos)


def test_mover_con_sobre_desconocido_se_rechaza():
    import pytest
    from trovefy.caja.movimientos import MovimientosCorruptos

    with pytest.raises(MovimientosCorruptos):
        calcular(CFG, [mov("reserva", "cajon", 100)], [])
    with pytest.raises(MovimientosCorruptos):
        calcular(CFG, [mov("nada", "tests", 100)], [])


def test_sobregasto_formatea_con_usd_sin_floats():
    e = calcular(CFG, [mov("", "", 2550, "herramienta")], [])
    assert "sobregasto de herramientas: restante -5,50 USD" in e.motivos
    e = calcular(CFG, [], [GastoTest("sin-asignar", "—", 30000, None)])
    assert "sobregasto de tests: restante -20 USD" in e.motivos
