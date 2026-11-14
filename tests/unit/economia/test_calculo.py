from decimal import Decimal

import pytest
from trovefy.economia.calculo import (
    AVISO_BE_BAJO,
    aov,
    cobros_esperados,
    cpa_objetivo,
    economia_de,
    neto_por_pedido,
    roas_equilibrio,
)
from trovefy.economia.modelo import Cifra, Costes, Tomas

from .ejemplos_economia import reglas_plantilla, usd

D = Decimal
T = Tomas(D("0"), D("0.10"), D("0.05"))
R = reglas_plantilla()
C = Costes(D("0.10"), D("0"), D("0"), D("0.05"))
ESCALERA_17 = {"front": usd("17"), "bump": None, "u1": usd("23.80"), "downsell": usd("9.52")}


def test_be_con_escalera_de_17_usd():
    e = economia_de(ESCALERA_17, C, T, R)
    assert e.aov_usd.valor == D("19.80")  # 19,8084 a la baja
    assert e.be_usd.valor == D("16.83")  # 19,8084 × 0,85 = 16,83714
    assert (e.cpa_test_usd.valor, e.cpa_escala_usd.valor) == (D("8.41"), D("10.94"))
    assert e.roas_be.valor == D("1.18")  # 19,8084 ÷ 16,83714 = 1,1764… al alza
    assert e.cobros == D("1.145")
    assert "AOV estimado 19,80 USD: lejos del objetivo de 30 USD (aspiracional)" in e.avisos
    assert AVISO_BE_BAJO not in e.avisos


def test_comision_fija_por_cobro():
    c = Costes(D("0.10"), D("0.50"), D("0"), D("0.05"))
    e = economia_de(ESCALERA_17, c, T, R)
    assert e.cobros == D("1.145") and e.be_usd.valor == D("16.26")


def test_funciones_sueltas():
    a = aov(D("17"), None, D("23.80"), D("9.52"), T)
    assert a == D("19.8084")
    assert cobros_esperados(T, True, True) == D("1.145")
    assert cobros_esperados(T, True, False) == D("1.10")
    assert cobros_esperados(T, False, True) == D("1")
    be = neto_por_pedido(a, D("1.145"), C)
    assert be == D("16.83714")
    assert cpa_objetivo(be, D("0.5")) == D("8.41")
    assert roas_equilibrio(a, be) == Cifra(D("1.18"))


def test_bump_apagado_no_suma():
    tomas = Tomas(D("0"), D("0.10"), D("0.05"))
    sin = economia_de({"front": usd("17"), "bump": None, "u1": None, "downsell": None}, C, tomas, R)
    con = economia_de({"front": usd("17"), "bump": usd("5.95"), "u1": None, "downsell": None}, C, tomas, R)
    assert sin.aov_usd == con.aov_usd == Cifra(D("17.00"))
    tomado = economia_de({"front": usd("17"), "bump": usd("5.95"), "u1": None, "downsell": None}, C,
                         Tomas(D("0.20"), D("0.10"), D("0.05")), R)
    assert tomado.aov_usd.valor == D("18.19")  # 17 + 5,95 × 0,20


def test_downsell_sin_u1_no_cuenta():
    e = economia_de({"front": usd("17"), "bump": None, "u1": None, "downsell": usd("9.52")}, C, T, R)
    assert e.aov_usd.valor == D("17.00") and e.cobros == D("1")
    assert aov(D("17"), None, None, D("9.52"), T) == D("17")


def test_be_bajo_avisa():
    c = Costes(D("0.15"), D("0.50"), D("0"), D("0.05"))
    e = economia_de({"front": usd("10"), "bump": None, "u1": None, "downsell": None}, c, Tomas(*[D(0)] * 3), R)
    assert e.be_usd.valor == D("7.50") and AVISO_BE_BAJO in e.avisos


def test_sostegno_cpa_15_75_supera_el_be():  # §7: front 13,90 → BE < 15,75
    e = economia_de({"front": usd("13.90"), "bump": None, "u1": None, "downsell": None}, C, T, R)
    assert e.be_usd.valor < D("15.75")


def test_neto_no_positivo_roas_no_medido():
    c = Costes(D("0.50"), D("6"), D("0"), D("0.05"))
    e = economia_de({"front": usd("10"), "bump": None, "u1": None, "downsell": None}, c, T, R)
    assert e.be_usd.valor == D("-1.50")
    assert e.roas_be.valor is None and "ningún CPA es rentable" in e.roas_be.motivo
    assert e.cpa_test_usd.valor is None and e.cpa_escala_usd.valor is None
    assert AVISO_BE_BAJO in e.avisos
    assert roas_equilibrio(D("10"), D("0")).valor is None


def test_costes_no_medidos_arrastran_motivo():
    e = economia_de({"front": usd("17"), "bump": None, "u1": None, "downsell": None},
                    Cifra(None, "no medido: falta ruta_activa en config/economia.yaml"), T, R)
    assert e.be_usd.valor is None and "falta ruta_activa" in e.cpa_test_usd.motivo
    assert e.roas_be.valor is None and e.cpa_escala_usd.valor is None
    # R-a: el aviso de AOV bajo depende solo del AOV; el de BE bajo, solo con BE medido.
    assert e.aov_usd.valor == D("17.00")
    assert e.avisos == ("AOV estimado 17 USD: lejos del objetivo de 30 USD (aspiracional)",)
    assert AVISO_BE_BAJO not in e.avisos


def test_precio_no_medido_arrastra_motivo():
    e = economia_de({"front": usd("17"), "bump": None,
                     "u1": Cifra(None, "no medido: sin cambio de referencia para MDL"), "downsell": None}, C, T, R)
    for cifra in (e.aov_usd, e.be_usd, e.cpa_test_usd, e.cpa_escala_usd, e.roas_be):
        assert cifra.valor is None and cifra.motivo == "no medido: sin cambio de referencia para MDL"
    assert e.cobros is None and e.avisos == ()


def test_falta_el_front():
    with pytest.raises(ValueError):
        economia_de({"front": None, "bump": None, "u1": None, "downsell": None}, C, T, R)


def test_nunca_float():
    e = economia_de(ESCALERA_17, Costes(D("0.10"), D("0.50"), D("0"), D("0.05")), T, R)
    for cifra in (e.aov_usd, e.be_usd, e.cpa_test_usd, e.cpa_escala_usd, e.roas_be):
        assert isinstance(cifra.valor, Decimal)
    assert isinstance(e.cobros, Decimal)
