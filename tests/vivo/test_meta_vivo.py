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
def test_conjunto_validate_only_vivo():
    """Un conjunto no se puede validar sin una campaña existente y crear una campaña sería crear algo real.
    Se valida en su lugar una campaña con los mismos datos de ubicación; ``publisher_platforms`` sin
    ``threads`` es un campo de conjunto, así que aquí solo se confirma que Meta acepta la campaña de prueba
    (``validate_only``) y que no se escribe nada."""
    cuenta = _cuenta()
    cliente = ClienteGraph(os.environ.get("TROVEFY_META_TOKEN_PRUEBA") or pytest.skip(_SIN_ENTORNO))
    r = cliente.crear(cuenta, "campaigns", {"name": "trovefy validate conjunto", "objective": "OUTCOME_SALES",
                                            "status": "PAUSED", "special_ad_categories": []},
                      validate_only=True)
    assert r.get("success") is True and "id" not in r
