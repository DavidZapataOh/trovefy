import json
import os
from pathlib import Path

import pytest
import yaml
from trovefy_ejecutor.dinero import MonedaNoConfigurada
from trovefy_ejecutor.limites import (
    CLAVES_CUENTA,
    CLAVES_GLOBALES,
    LimitesInvalidos,
    cargar_limites,
)

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
C = "act_0000000000000000"


def escribir(tmp_path, d, modo=0o600):
    f = tmp_path / "limites.yaml"
    f.write_text(yaml.safe_dump(d))
    os.chmod(f, modo)
    return f


def base():
    return yaml.safe_load(PLANTILLA.read_text())


def test_plantilla_carga_y_offset_nulo_bloquea(tmp_path):
    lim = cargar_limites(escribir(tmp_path, base()))
    lc = lim.cuentas[C]
    assert lc.moneda_codigo == "COP" and lc.zona_horaria == "America/Bogota"
    assert (lc.tope_gasto_diario_total, lc.max_presupuesto_conjunto, lc.max_presupuesto_campana_cbo,
            lc.spend_cap_test, lc.spend_cap_test_prorroga) == (165000, 99000, 132000, 99000, 181500)
    assert lc.paginas_permitidas == frozenset()
    with pytest.raises(MonedaNoConfigurada):
        lc.moneda()


def test_plantilla_sin_agenda_ni_regla_meta(tmp_path):
    # Resolución 22: fuera hasta que se resuelva P-07 (el plan 11 aún no valida su contenido).
    lim = cargar_limites(escribir(tmp_path, base()))
    assert not {"agenda", "regla_meta"} & lim.acciones_permitidas
    assert "limite_ejecutor" in lim.acciones_permitidas and "presupuesto" in lim.acciones_permitidas


def test_cop_con_offset(limites_cop):
    lc = limites_cop.cuentas[C]
    assert lc.moneda().offset == 1 and lc.tope_gasto_diario_total == 165000
    assert lc.datasets_permitidos == frozenset({"8877665544"})


def test_sin_offset_fixture(limites_cop_sin_offset):
    with pytest.raises(MonedaNoConfigurada):
        limites_cop_sin_offset.cuentas[C].moneda()


def test_claves_exportadas():
    assert "paso_max_pct" in CLAVES_GLOBALES and "tope_gasto_diario_total" in CLAVES_CUENTA


def test_cuenta_permitida_sin_seccion(tmp_path):
    d = base()
    d["cuentas_permitidas"].append("act_999")
    with pytest.raises(LimitesInvalidos, match="act_999"):
        cargar_limites(escribir(tmp_path, d))


@pytest.mark.parametrize("clave,valor,motivo", [
    ("tope_gasto_diario_total_usd", 50, "D-37"), ("color", 1, "color"),
    ("paso_max_pct", 0, "paso_max_pct"), ("paso_max_pct", 101, "paso_max_pct"),
    ("paso_max_pct", True, "paso_max_pct"), ("paso_max_pct", 1.5, "paso_max_pct"),
    ("montaje_status_forzado", "ACTIVE", "PAUSED"),
    ("acciones_permitidas", ["noop", "borrar"], "borrar")])
def test_claves_malas(tmp_path, clave, valor, motivo):
    d = base()
    d[clave] = valor
    with pytest.raises(LimitesInvalidos, match=motivo):
        cargar_limites(escribir(tmp_path, d))


def test_clave_global_faltante(tmp_path):
    d = base()
    del d["paso_max_pct"]
    with pytest.raises(LimitesInvalidos, match="paso_max_pct"):
        cargar_limites(escribir(tmp_path, d))


@pytest.mark.parametrize("clave,valor,motivo", [
    ("tope_gasto_diario_total", 0, "tope_gasto_diario_total"),
    ("tope_gasto_diario_total", 1.5, "tope_gasto_diario_total"),
    ("spend_cap_test_usd", 30, "D-37"),
    ("zona_horaria", "Marte/Olimpo", "zona_horaria"),
    ("offset", 7, "offset"), ("offset", True, "offset"), ("offset", "1", "offset"),
    ("extra", 1, "extra"),
    ("paginas_permitidas", [123], "paginas_permitidas")])
def test_cuenta_mala(tmp_path, clave, valor, motivo):
    d = base()
    d["cuentas"][C][clave] = valor
    with pytest.raises(LimitesInvalidos, match=motivo):
        cargar_limites(escribir(tmp_path, d))


def test_cuenta_faltante_clave(tmp_path):
    d = base()
    del d["cuentas"][C]["spend_cap_test"]
    with pytest.raises(LimitesInvalidos, match="spend_cap_test"):
        cargar_limites(escribir(tmp_path, d))


def test_clave_de_cuenta_invalida(tmp_path):
    d = base()
    d["cuentas"]["cuenta-x"] = d["cuentas"][C]
    with pytest.raises(LimitesInvalidos, match="cuenta-x"):
        cargar_limites(escribir(tmp_path, d))


def test_yaml_ilegible_y_no_mapa(tmp_path):
    f = tmp_path / "limites.yaml"
    f.write_text("a: [")
    os.chmod(f, 0o600)
    with pytest.raises(LimitesInvalidos):
        cargar_limites(f)
    f.write_text("- 1")
    with pytest.raises(LimitesInvalidos):
        cargar_limites(f)
    with pytest.raises(LimitesInvalidos):
        cargar_limites(tmp_path / "nada.yaml")


def test_permisos_abiertos(tmp_path):
    with pytest.raises(LimitesInvalidos, match="0600"):
        cargar_limites(escribir(tmp_path, base(), 0o644))
    assert cargar_limites(escribir(tmp_path, base(), 0o644), exigir_0600=False)


@pytest.mark.parametrize("moneda,offset,ok", [("USD", 1, False), ("COP", 100, False), ("EUR", 100, False),
                                              ("COP", 1, True), ("USD", 100, True), ("COP", None, True),
                                              ("EUR", None, True)])
def test_offset_coherente_con_moneda(tmp_path, moneda, offset, ok):
    d = base()
    d["cuentas"][C]["moneda"] = moneda
    d["cuentas"][C]["offset"] = offset
    f = escribir(tmp_path, d)
    if ok:
        assert cargar_limites(f)
    else:
        with pytest.raises(LimitesInvalidos, match="offset"):
            cargar_limites(f)


def test_claves_repetidas(tmp_path):
    f = tmp_path / "limites.yaml"
    texto = PLANTILLA.read_text()
    os.chmod(tmp_path, 0o700)
    for malo, clave in [(texto.replace("    spend_cap_test: 99000", "    tope_gasto_diario_total: 1\n    spend_cap_test: 99000"),
                         "tope_gasto_diario_total"), (texto + "paso_max_pct: 10\n", "paso_max_pct")]:
        f.write_text(malo)
        os.chmod(f, 0o600)
        with pytest.raises(LimitesInvalidos, match=clave):
            cargar_limites(f)


def test_limites_a_dict_forma_de_la_resolucion_12(limites_cop):
    from trovefy_ejecutor.limites import limites_a_dict

    d = limites_a_dict(limites_cop)
    assert json.loads(json.dumps(d)) == d
    assert set(d) == {"version", "cuentas_permitidas", "acciones_permitidas", "montaje_status_forzado",
                      "paso_max_pct", "cadencia_min_presupuesto_min", "enfriamiento_puja_estructura_h",
                      "max_cambios_hora_conjunto", "cuentas"}
    assert set(d["cuentas"]) == {C}
    assert d["cuentas"][C] == {"moneda": "COP", "offset": 1, "zona_horaria": "America/Bogota",
                               "tope_gasto_diario_total": 165000, "max_presupuesto_conjunto": 99000,
                               "max_presupuesto_campana_cbo": 132000, "spend_cap_test": 99000,
                               "spend_cap_test_prorroga": 181500}
    assert d["version"] == 1 and d["paso_max_pct"] == 50 and d["montaje_status_forzado"] == "PAUSED"
    assert d["cuentas_permitidas"] == [C]
    assert d["acciones_permitidas"] == sorted(limites_cop.acciones_permitidas)


def test_limites_a_dict_offset_nulo(limites_cop_sin_offset):
    from trovefy_ejecutor.limites import limites_a_dict

    assert limites_a_dict(limites_cop_sin_offset)["cuentas"][C]["offset"] is None
