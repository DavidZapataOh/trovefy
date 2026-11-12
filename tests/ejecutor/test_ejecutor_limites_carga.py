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
    assert lc.spend_cap_test_prorroga == 181500 and lc.paginas_permitidas == frozenset()
    with pytest.raises(MonedaNoConfigurada):
        lc.moneda()


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
