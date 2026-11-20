"""Importes del test en COP con la TRM y contra los límites del ejecutor (plan 22, Tarea 2)."""
from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest
from trovefy.aprobaciones.fuentes import Lectura
from trovefy.montar import MontajeInvalido, NoMedido
from trovefy.montar.importes import calcular, texto_importes
from trovefy.trm import Trm

from .ejemplos import CUENTA, LIMITES, META, TRM

HOY = date(2026, 11, 20)


def _calc(trm=TRM, meta=META, limites=LIMITES, **kw):
    datos = {"conjuntos": 5, "usd_conjunto": Decimal(5), "usd_tope": Decimal(100)} | kw
    return calcular(CUENTA, Lectura(meta, None), Lectura(limites, None), trm, HOY, **datos)


def _lim(**cambios):
    d = copy.deepcopy(LIMITES)
    d["cuentas"][CUENTA].update(cambios)
    return d


def test_trm_4000():
    i = _calc()
    assert (i.diario_conjunto, i.spend_cap) == (20000, 400000)


def test_conversion_a_la_baja():
    i = _calc(trm=Trm(Decimal("3999.99"), HOY, HOY))
    assert i.diario_conjunto == 19999 and i.spend_cap == 399999


def test_limite_cop_manda():
    with pytest.raises(MontajeInvalido, match=r"límite del ejecutor \(US\$ 27,50\) recorta el techo de US\$ 100"):
        _calc(limites=_lim(spend_cap_test=110000))


def test_presupuesto_sobre_limite_falla():
    with pytest.raises(MontajeInvalido, match="max_presupuesto_conjunto"):
        _calc(limites=_lim(max_presupuesto_conjunto=15000))


def test_no_cabe_en_tope_diario():
    with pytest.raises(MontajeInvalido, match="tope diario"):
        _calc(limites=_lim(tope_gasto_diario_total=150000), usd_vivos=Decimal(25))


def test_sin_trm_no_medido():
    with pytest.raises(NoMedido, match="sin TRM"):
        _calc(trm=None)


def test_meta_de_otra_cuenta_no_medido():
    with pytest.raises(NoMedido, match="comprobar-meta"):
        _calc(meta={**META, "cuenta": "act_1"})


def test_cuenta_usd_sin_conversion():
    lim = copy.deepcopy(LIMITES)
    lim["cuentas"][CUENTA].update(moneda="USD", spend_cap_test=10000)
    i = _calc(trm=None, meta={**META, "currency": "USD", "offset": 100}, limites=lim)
    assert (i.diario_conjunto, i.spend_cap) == (500, 10000)


def test_texto():
    t = texto_importes(_calc())
    assert t[0].startswith("5 × 20.000 COP/día (US$ 5,00 c/u) · techo 400.000 COP (US$ 100,00)")
    assert "TRM 4.000,00" in t[1]
