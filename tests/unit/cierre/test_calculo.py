"""Cálculo del cierre como el bot (plan 24, Tarea 6)."""
from datetime import date
from decimal import Decimal

from trovefy.cierre.calculo import a_usd, calcular_cierre, contraste_utm
from trovefy.cierre.lectura import VentaLedger
from trovefy.cierre.plataforma import Venta
from trovefy.economia.comisiones import Comisiones
from trovefy.meta.insights import FilaInsight

from .ejemplos import CAMBIO, CAMPANA, DIA, PAIS, STORE, TRM, P

CERO = Comisiones("x", Decimal(0), Decimal(0), Decimal(0), ())
WHOP = Comisiones("impultienda_whop", Decimal("0.03"), Decimal("0.30"), Decimal(0), ())


def fila(gasto="1183.38", moneda="USD", compras=1, dia=DIA):
    return FilaInsight("campana", CAMPANA, "PRUEBA ZZ | G1", CAMPANA, dia, Decimal(gasto), moneda, 1000, 10, 5, 1,
                       compras, None)


def v(orden, total="13.90", moneda="EUR", post=False, prueba=False, dia=DIA):
    return Venta(STORE, orden, dia, Decimal(total), moneda, post, "impul_pay", P, PAIS, prueba)


def cierre(gasto=None, ventas=(), com=CERO, desap=(), **kw):
    return calcular_cierre(DIA, list(gasto if gasto is not None else [fila()]), list(ventas), list(desap), com, TRM,
                           CAMBIO, "America/Bogota", kw.pop("zona_tienda", "America/Bogota"), **kw)


def test_ganancia_como_el_bot():
    c = cierre(ventas=[v("A", "2644.92", "USD")])
    assert c.gasto_usd == (Decimal("1183.38"), None) and c.neto_usd == (Decimal("2644.92"), None)
    assert c.ganancia_usd == (Decimal("1461.54"), None) and c.roas_neto == (Decimal("2.24"), None)


def test_sin_comisiones_neto_no_medido():
    c = cierre(ventas=[v("A")], com=["falta plataformas.whop.comision_pct"])
    assert c.neto_usd[0] is None and c.neto_usd[1] == "falta la comisión de Whop"
    assert c.ganancia_usd[0] is None and c.gasto_usd[0] is not None and c.bruto_usd[0] is not None


def test_no_suma_monedas_distintas():
    c = cierre(ventas=[v("A", "10.00", "EUR"), v("B", "10.00", "USD")])
    assert c.bruto_usd == (Decimal("21.00"), None)  # 10 EUR × 1,10 + 10 USD
    sin_cambio = calcular_cierre(DIA, [fila()], [v("A", "10", "EUR"), v("B", "10", "USD")], [], CERO, TRM, None,
                                 "America/Bogota", None)
    assert sin_cambio.bruto_usd[0] is None and "sin cambio del 19/11" in sin_cambio.bruto_usd[1]


def test_gasto_al_alza_ingreso_a_la_baja():
    assert a_usd(Decimal(99201), "COP", DIA, TRM, None, True) == (Decimal("24.81"), None)
    assert a_usd(Decimal("13.91"), "EUR", DIA, None, CAMBIO, False) == (Decimal("15.30"), None)
    assert a_usd(Decimal(1), "COP", date(2027, 1, 5), TRM, None, True)[0] is None


def test_post_compra_suma_bruto_no_venta():
    c = cierre(ventas=[v("A", "10.00", "USD"), v("B", "5.00", "USD", post=True)])
    assert c.bruto_usd[0] == Decimal("15.00") and c.ventas == 1 and c.upsell == (1, 1)


def test_comisiones_por_pedido():
    c = cierre(ventas=[v("A", "10.00", "USD"), v("B", "5.00", "USD", post=True)], com=WHOP)
    assert c.comisiones_usd == (Decimal("1.05"), None)  # 15 × 3 % + 2 × 0,30
    assert c.neto_usd == (Decimal("13.95"), None)


def test_compra_de_prueba_no_cuenta():
    c = cierre(ventas=[v("A", "10.00", "USD"), v("P", "10.00", "USD", prueba=True)])
    assert c.bruto_usd[0] == Decimal("10.00") and c.ventas == 1


def test_reembolso_resta_el_dia_de_deteccion():
    d = VentaLedger(date(2026, 11, 17), STORE, "R", P, PAIS, Decimal("10.00"), "USD", False, None, "desaparecida",
                    "", "", "", DIA)
    otro = VentaLedger(date(2026, 11, 17), STORE, "R2", P, PAIS, Decimal("4.00"), "USD", False, None,
                       "desaparecida", "", "", "", date(2026, 11, 18))
    c = cierre(ventas=[v("A", "30.00", "USD")], desap=[d, otro])
    assert c.reembolsos_usd == (Decimal("10.00"), None) and c.neto_usd[0] == Decimal("20.00")


def test_sin_gasto_roas_no_medido():
    c = cierre(gasto=[fila("0")], ventas=[v("A", "10", "USD")])
    assert c.roas_neto == (None, "sin gasto")


def test_gasto_cop_con_trm():
    c = cierre(gasto=[fila("99200", "COP")], ventas=[])
    assert c.gasto_usd == (Decimal("24.80"), None) and c.gasto_original == {"COP": Decimal(99200)}
    assert any("TRM" in x for x in c.cambios)


def test_pixel_subnotifica():
    c = cierre(gasto=[fila(compras=0)], ventas=[v("A", "10", "USD")])
    assert any("píxel subnotifica" in a for a in c.anomalias)


def test_fiabilidad_alta_media_baja():
    assert cierre(ventas=[v("A", "10", "USD")]).fiabilidad == "alta"
    assert cierre(gasto=[fila(compras=5)], ventas=[v("A", "10", "USD")]).fiabilidad == "media"
    assert cierre(ventas=[v("A", "10", "USD")], fuente_ventas="export").fiabilidad == "media"
    assert cierre(ventas=[], ventas_completa=False).fiabilidad == "baja"
    assert cierre(ventas=[v("A", "10", "USD")], meta_completa=False).fiabilidad == "baja"


def test_zona_distinta_baja_a_media():
    c = cierre(ventas=[v("A", "10", "USD")], zona_tienda="Europe/Sofia")
    assert c.fiabilidad == "media" and "Europe/Sofia" in c.motivos_fiabilidad[0]


def test_contraste_utm_marca_diferencia():
    c = cierre(ventas=[v("A", "2644.92", "USD")])
    inst = {"structuredContent": {"meta_ads": {"disponible": True, "moneda": "USD",
                                               "totales": {"gasto": "1100", "ganancia": "1461.54"}}}}
    assert "gasto" in contraste_utm(c, inst)
    inst["structuredContent"]["meta_ads"]["totales"]["gasto"] = "1183.00"
    assert contraste_utm(c, inst) is None
    assert contraste_utm(c, None) is None
