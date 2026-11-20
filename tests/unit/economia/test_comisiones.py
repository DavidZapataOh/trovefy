"""Comisiones de la ruta activa (resolución 15): suma o lista de lo que falta. Valores ficticios de prueba."""
from dataclasses import replace
from decimal import Decimal

from trovefy.economia.comisiones import Comisiones, comisiones

from .ejemplos_economia import config_plantilla


def _con(**plataformas):
    cfg = config_plantilla()
    nuevas = dict(cfg.plataformas)
    for nombre, valores in plataformas.items():
        nuevas[nombre] = replace(nuevas[nombre], **valores)
    return replace(cfg, ruta_activa="impultienda_whop", plataformas=nuevas)


def test_ruta_sin_fijar_lista_faltantes():
    assert comisiones(config_plantilla()) == ["falta ruta_activa"]


def test_comision_null_lista_faltantes():
    faltan = comisiones(_con(impultienda={"comision_pct": Decimal(0), "comision_fija_usd": Decimal(0),
                                          "impuestos_pct": Decimal(0)}))
    assert "falta plataformas.whop.comision_pct" in faltan


def test_suma_de_la_ruta_y_cero_no_es_faltante():
    c = comisiones(_con(impultienda={"comision_pct": Decimal(0), "comision_fija_usd": Decimal(0),
                                     "impuestos_pct": Decimal(0)},
                        whop={"comision_pct": Decimal("0.03"), "comision_fija_usd": Decimal("0.30"),
                              "impuestos_pct": Decimal(0)}))
    assert isinstance(c, Comisiones)
    assert c.pct == Decimal("0.03") and c.fija_usd == Decimal("0.30") and c.impuestos_pct == 0
    assert c.fuentes == ("plataformas.impultienda", "plataformas.whop")
