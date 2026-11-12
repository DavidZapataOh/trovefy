"""Pruebas contra la Graph API real (marca vivo; se ejecutan con ``-m vivo``). Solo lectura y ``validate_only``:
no crean nada. El token y la cuenta llegan por entorno (la cuenta real nunca va en el repo, D-35). El token no
se guarda en variables locales: con ``--showlocals`` pytest las imprimiría."""
import os
import warnings

import pytest
from trovefy_ejecutor.comprobar_meta import comprobar_meta, informe_a_dict
from trovefy_ejecutor.graph import ClienteGraph

_SIN_ENTORNO = "faltan TROVEFY_META_TOKEN_PRUEBA y TROVEFY_META_CUENTA_PRUEBA"


def _cuenta() -> str:
    return os.environ.get("TROVEFY_META_CUENTA_PRUEBA") or pytest.skip(_SIN_ENTORNO)


@pytest.mark.vivo
def test_cuenta_real_cop():
    cuenta = _cuenta()
    cliente = ClienteGraph(os.environ.get("TROVEFY_META_TOKEN_PRUEBA") or pytest.skip(_SIN_ENTORNO))
    i = comprobar_meta(cliente, cuenta)
    # el usuario compara spend_cap con el de Ads Manager (P-21)
    warnings.warn(str(informe_a_dict(i)), stacklevel=1)
    assert i.ok and (i.cuenta.currency, i.cuenta.offset) == ("COP", 1)


@pytest.mark.vivo
def test_campana_validate_only_vivo():
    """``validate_only`` de una campaña PAUSED en la cuenta real: Meta la acepta y no se crea nada. El payload
    no lleva datos de ubicación; la comprobación de ``publisher_platforms`` sin ``threads`` a nivel de conjunto
    NO queda cubierta (un conjunto exige una campaña existente y crearla sería crear algo real)."""
    cuenta = _cuenta()
    cliente = ClienteGraph(os.environ.get("TROVEFY_META_TOKEN_PRUEBA") or pytest.skip(_SIN_ENTORNO))
    r = cliente.crear(cuenta, "campaigns", {"name": "trovefy validate conjunto", "objective": "OUTCOME_SALES",
                                            "status": "PAUSED", "special_ad_categories": [],
                                            "is_adset_budget_sharing_enabled": False},
                      validate_only=True)
    assert r.get("success") is True and "id" not in r
