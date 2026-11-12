import dataclasses
import pathlib
import re

import pytest
from ejecutor.falsos.graph_falso import CUENTA, mundo_basico
from trovefy_ejecutor.comprobar_meta import InformeMeta, comprobar_meta, informe_a_dict
from trovefy_ejecutor.graph import ErrorGraph, ErrorRed


def test_cuenta_cop_ok():
    g = mundo_basico()
    i = comprobar_meta(g, CUENTA)
    d = informe_a_dict(i)
    assert set(d) == {"fecha", "cuenta", "currency", "offset", "timezone_name", "account_status",
                      "amount_spent", "spend_cap", "validate_only"}
    assert i.ok and (d["cuenta"], d["currency"], d["offset"], d["amount_spent"]) == (CUENTA, "COP", 1, 250000)
    assert d["validate_only"] == {"ok": True, "motivo": None}
    assert g.escrituras() == []
    assert [x.validate_only for x in g.llamadas if x.metodo == "crear"] == [True]
    assert g.llamadas[-1].datos == {"name": "trovefy comprobar-meta", "objective": "OUTCOME_SALES",
                                    "status": "PAUSED", "special_ad_categories": [],
                                    "is_adset_budget_sharing_enabled": False}


def test_token_caducado():
    g = mundo_basico()
    g.token_caduca_tras = 0
    i = comprobar_meta(g, CUENTA)
    assert not i.ok and "token" in i.problemas[0]
    d = informe_a_dict(i)
    assert d["validate_only"]["ok"] is False and d["currency"] is None
    assert [x for x in g.llamadas if x.metodo == "crear"] == []


def test_moneda_sin_offset():
    g = mundo_basico()
    g.cuentas[CUENTA]["currency"] = "XXX"
    i = comprobar_meta(g, CUENTA)
    assert not i.ok and not i.offset_confirmado
    assert "XXX" in " ".join(i.problemas)


def test_cuenta_inactiva():
    g = mundo_basico()
    g.cuentas[CUENTA]["account_status"] = 2
    i = comprobar_meta(g, CUENTA)
    assert not i.ok and "account_status 2" in " ".join(i.problemas)


def test_validate_only_falla():
    g = mundo_basico()
    g.fallar_validacion["campaigns"] = ErrorGraph(100, 1487, "mal")
    i = comprobar_meta(g, CUENTA)
    assert not i.ok and "Meta 100/1487" in i.problemas[0]
    assert informe_a_dict(i)["validate_only"] == {"ok": False, "motivo": i.problemas[0]}


def test_sin_red_en_lectura_y_en_validate():
    g = mundo_basico()
    g.red_al_leer = True
    i = comprobar_meta(g, CUENTA)
    assert i.problemas == ("sin red",) and not i.ok
    g2 = mundo_basico()

    class SoloLeeBien:
        def cuenta(self, a):
            return g2.cuenta(a)

        def crear(self, *a, **k):
            raise ErrorRed("conexión")
    i2 = comprobar_meta(SoloLeeBien(), CUENTA)
    assert i2.problemas == ("sin red",) and not i2.ok


def test_excepcion_inesperada_no_se_propaga_ni_filtra():
    class Roto:
        def cuenta(self, a):
            raise RuntimeError("token SECRETO-123")
    i = comprobar_meta(Roto(), CUENTA)
    assert not i.ok and "SECRETO" not in " ".join(i.problemas)


def test_informe_inmutable():
    i = comprobar_meta(mundo_basico(), CUENTA)
    assert isinstance(i, InformeMeta)
    with pytest.raises(dataclasses.FrozenInstanceError):
        i.act_id = "x"  # type: ignore[misc]


def test_ejecutor_no_importa_trovefy():
    raiz = pathlib.Path(__file__).resolve().parents[2] / "scripts/trovefy_ejecutor"
    archivos = sorted(raiz.glob("*.py"))
    assert archivos
    for f in archivos:
        assert not re.search(r"^\s*(from|import)\s+trovefy(\.|\s|$)", f.read_text(), re.MULTILINE), f.name


def test_motivo_es_el_de_validate_only_no_el_primer_problema():
    g = mundo_basico()
    g.cuentas[CUENTA]["account_status"] = 2
    g.fallar_validacion["campaigns"] = ErrorGraph(100, 1487, "mal")
    d = informe_a_dict(comprobar_meta(g, CUENTA))
    assert d["validate_only"] == {"ok": False, "motivo": "validate_only falló: Meta 100/1487"}


def test_moneda_desconocida_con_validate_ok_no_pone_motivo():
    g = mundo_basico()
    g.cuentas[CUENTA]["currency"] = "XXX"
    i = comprobar_meta(g, CUENTA)
    assert not i.ok
    assert informe_a_dict(i)["validate_only"] == {"ok": True, "motivo": None}


def test_lectura_fallida_motivo_no_se_pudo_leer():
    g = mundo_basico()
    g.token_caduca_tras = 0
    assert informe_a_dict(comprobar_meta(g, CUENTA))["validate_only"] == {
        "ok": False, "motivo": "no se pudo leer la cuenta"}
