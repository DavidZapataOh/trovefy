from dataclasses import replace
from decimal import Decimal

import pytest
from trovefy.economia.escalera import (
    PASOS,
    PrecioInvalido,
    a_eur,
    a_usd,
    escalera_pais,
    front_objetivo_eur,
    redondear_psicologico,
)
from trovefy.economia.modelo import Cifra

from .ejemplos_economia import CAMBIO, XE, XM, XR, XU, reglas_escalera

D = Decimal
R = reglas_escalera()


def test_redondeo_psicologico():
    assert redondear_psicologico(D("13.95"), "EUR") == D("13.90")
    assert redondear_psicologico(D("4.865"), "EUR") == D("4.90")
    assert redondear_psicologico(D("24.15"), "RON") == D("29")
    assert redondear_psicologico(D("151.8"), "RON") == D("149")


def test_redondeo_empate_hacia_arriba_y_nunca_cero():
    assert redondear_psicologico(D("14.40"), "USD") == D("14.90")
    assert redondear_psicologico(D("14"), "RON") == D("19")
    assert redondear_psicologico(D("0.20"), "EUR") == D("0.90")
    assert redondear_psicologico(D("2"), "RON") == D("9")
    assert redondear_psicologico(D("0.05"), "EUR") > 0


def test_cambios_en_decimal():
    assert a_eur(D("49.77"), "RON", CAMBIO) == Cifra(D("49.77") / D("4.977"))
    assert a_eur(D("10"), "EUR", None) == Cifra(D("10"))
    assert a_usd(D("10"), "EUR", CAMBIO) == Cifra(D("10.80"))
    assert a_usd(D("10"), "USD", None) == Cifra(D("10"))
    assert a_eur(D("10"), "MDL", CAMBIO).motivo == "no medido: sin cambio de referencia para MDL"
    assert a_usd(D("10"), "RON", None).motivo == "no medido: sin cambio de referencia para RON"
    assert isinstance(a_usd(D("10"), "RON", CAMBIO).valor, Decimal)


def test_front_objetivo():
    assert front_objetivo_eur((D("11.90"), D("15.90")), R) == (D("13.95"), [])
    eur, avisos = front_objetivo_eur((D("25"), D("30")), R)
    assert eur == D("24") and avisos == ["la banda de precios del país queda fuera del rango del front (12–24 €)"]
    assert front_objetivo_eur((D("5"), D("9")), R)[0] == D("12")


def test_escalera_eur():
    e = escalera_pais(XE, R, CAMBIO, None, None, 1, None)
    assert tuple(e.pasos) == PASOS and e.moneda == "EUR" and e.pais == "XE" and e.motivo is None
    precios = {k: p.precio for k, p in e.pasos.items()}
    assert precios == {"front": D("13.90"), "bump": D("4.90"), "u1": D("19.90"), "u2": D("30.90"),
                       "u3": D("12.90"), "downsell": D("7.90")}
    assert [k for k, p in e.pasos.items() if p.activo] == ["front", "u1"]
    assert "apagado en el test 1" in e.pasos["bump"].motivo_inactivo
    assert e.pasos["downsell"].motivo_inactivo == "no medido: P-05"
    assert e.pasos["u2"].motivo_inactivo == e.pasos["u3"].motivo_inactivo == "el plan de la tienda admite 1 upsell"
    assert e.pasos["front"].motivo_inactivo is None and e.front_eur == Cifra(D("13.90"))
    assert e.fuente_precio == "banda del país" and e.avisos == ()


def test_escalera_ron():
    e = escalera_pais(XR, R, CAMBIO, None, None, 3, True)
    assert {k: p.precio for k, p in e.pasos.items()} == {"front": D("69"), "bump": D("29"), "u1": D("99"),
                                                          "u2": D("149"), "u3": D("59"), "downsell": D("39")}
    assert all(p.activo for k, p in e.pasos.items() if k != "bump")
    assert all(p.moneda == "RON" for p in e.pasos.values())
    assert e.front_eur.valor == D("13.86")


def test_upsells_no_medidos_y_downsell_no_admitido():
    e = escalera_pais(XE, R, CAMBIO, None, None, None, False)
    assert e.pasos["u2"].motivo_inactivo == "no medido: upsells del plan"
    assert not e.pasos["downsell"].activo and e.pasos["downsell"].motivo_inactivo
    e2 = escalera_pais(XE, R, CAMBIO, None, None, 2, None)
    assert e2.pasos["u2"].activo and not e2.pasos["u3"].activo
    assert e2.pasos["u3"].motivo_inactivo == "el plan de la tienda admite 2 upsells"


def test_bump_activo_si_la_regla_lo_dice():
    e = escalera_pais(XE, replace(R, bump_activo_test1=True), CAMBIO, None, None, 1, None)
    assert e.pasos["bump"].activo and e.pasos["bump"].motivo_inactivo is None


def test_nunca_por_debajo_de_10():
    with pytest.raises(PrecioInvalido):
        escalera_pais(XE, R, CAMBIO, None, D("9.90"), 1, None)
    with pytest.raises(PrecioInvalido):
        escalera_pais(XR, R, CAMBIO, None, D("39"), 1, None)  # 39 RON ≈ 7,84 €


def test_precio_manual_valido():
    e = escalera_pais(XE, R, CAMBIO, None, D("19.90"), 1, None)
    assert e.pasos["front"].precio == D("19.90") and e.fuente_precio == "usuario"
    assert e.pasos["u1"].precio == D("27.90")  # 1,4 × 19,90 = 27,86


def test_banda_fuera_del_rango_avisa():
    xa = replace(XE, banda_eur=(25.0, 30.0))
    e = escalera_pais(xa, R, CAMBIO, None, None, 1, None)
    assert e.pasos["front"].precio == D("23.90")
    assert "la banda de precios del país queda fuera del rango del front (12–24 €)" in e.avisos


def test_banda_estrecha_sin_precio_psicologico_dentro_avisa():
    xb = replace(XE, banda_eur=(13.92, 14.80))  # punto medio 14,36 → 13,90; el escalón (14,90) tampoco cabe
    e = escalera_pais(xb, R, CAMBIO, None, None, 1, None)
    assert e.pasos["front"].precio == D("13.90")
    assert any("cabe en la banda del país" in a for a in e.avisos)


def test_mercado_en_usd():
    e = escalera_pais(XU, R, CAMBIO, None, None, 1, None)
    # banda 11,90–15,90 € = 12,85–17,17 USD ∩ 17–27 = 17–17,17 → 16,90 (17,90 tampoco cabe)
    assert e.moneda == "USD" and e.pasos["front"].precio == D("16.90")
    assert e.front_eur.valor == D("15.65")
    with pytest.raises(PrecioInvalido):
        escalera_pais(XU, R, CAMBIO, None, D("9.90"), 1, None)


def test_mercado_en_usd_sin_cambio():
    e = escalera_pais(XU, R, None, None, None, 1, None)
    assert e.pasos is None and e.motivo == "no medido: sin cambio de referencia para USD"


def test_original_mas_barato_no_baja_del_suelo():
    e = escalera_pais(XE, R, CAMBIO, (D("9.00"), "EUR"), None, 1, None)
    assert e.pasos["front"].precio == D("13.90") and any("el original cuesta 9,00 €" in a for a in e.avisos)


def test_original_mas_caro_sin_aviso():
    e = escalera_pais(XE, R, CAMBIO, (D("39.00"), "EUR"), None, 1, None)
    assert e.avisos == ()


def test_original_sin_moneda_no_compara():
    e = escalera_pais(XE, R, CAMBIO, (D("9.00"), None), None, 1, None)
    assert any("no medido (moneda del original no medida)" in a for a in e.avisos)
    assert not any("el original cuesta" in a for a in e.avisos)


def test_moneda_sin_cambio_no_medido():
    e = escalera_pais(XM, R, CAMBIO, None, None, 1, None)
    assert e.pasos is None and e.motivo == "no medido: sin cambio de referencia para MDL"
    assert e.front_eur.valor is None


def test_precio_manual_sin_cambio_avisa_minimo():
    e = escalera_pais(XM, R, CAMBIO, None, D("249"), 1, None)
    assert e.pasos["front"].precio == D("249") and e.fuente_precio == "usuario"
    assert any("no se pudo comprobar el mínimo de 10" in a for a in e.avisos)
    assert "no se pudo comprobar el mínimo de 10: sin cambio para MDL" in e.avisos
    assert e.front_eur.valor is None and e.pasos["u1"].precio == D("349")  # 1,4 × 249 = 348,6


def test_ajuste_de_un_escalon_para_quedar_dentro():
    xb = replace(XE, banda_eur=(5.0, 9.0))  # objetivo 12 → 11,90 queda fuera de 12–24: sube un escalón
    e = escalera_pais(xb, R, CAMBIO, None, None, 1, None)
    assert e.pasos["front"].precio == D("12.90")
    assert e.avisos == ("la banda de precios del país queda fuera del rango del front (12–24 €)",)
