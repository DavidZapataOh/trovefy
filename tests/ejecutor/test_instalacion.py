"""Funciones puras del instalador (plan 12, tarea 7)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from trovefy_ejecutor import instalacion
from trovefy_ejecutor.instalacion import (
    OffsetDistinto,
    cuenta_de_arranque,
    fijar_offset,
    limites_para_cuenta,
)
from trovefy_ejecutor.limites import cargar_limites

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
ACT = "act_0000000000000000"


def _arranque(tmp_path: Path, datos: dict | None) -> Path:
    f = tmp_path / "arranque.yaml"
    paso = {"id": "06", "estado": "hecho", "evidencia": [], "datos": datos or {}}
    f.write_text(yaml.safe_dump({"pasos": [{"id": "01", "datos": {}}, paso]}))
    return f


def _limites(tmp_path: Path) -> Path:
    f = tmp_path / "limites.yaml"
    f.write_text(limites_para_cuenta(PLANTILLA.read_text(), "act_999000111", "COP", "America/Bogota"))
    os.chmod(f, 0o600)
    return f


def test_cuenta_y_limites_desde_arranque(tmp_path):
    f = _arranque(tmp_path, {"act_id": "999000111", "moneda": "cop", "zona": "America/Bogota"})
    assert cuenta_de_arranque(f) == ("act_999000111", "COP", "America/Bogota")
    f = _arranque(tmp_path, {"act_id": "act_999000111", "moneda": "COP", "zona": "America/Bogota"})
    assert cuenta_de_arranque(f)[0] == "act_999000111"
    yaml_txt = limites_para_cuenta(PLANTILLA.read_text(), "act_999000111", "COP", "America/Bogota")
    assert ACT not in yaml_txt
    p = tmp_path / "l.yaml"
    p.write_text(yaml_txt)
    lim = cargar_limites(p, exigir_0600=False)
    assert lim.cuentas_permitidas == {"act_999000111"}
    assert lim.cuentas["act_999000111"].offset is None
    assert lim.cuentas["act_999000111"].moneda_codigo == "COP"


@pytest.mark.parametrize("datos", [None, {"act_id": "1"}, {"act_id": "x1", "moneda": "COP", "zona": "America/Bogota"},
                                   {"act_id": "1", "moneda": "COP", "zona": "Nada/Nada"}])
def test_arranque_incompleto(tmp_path, datos):
    with pytest.raises(ValueError, match="paso 06 de /arranque"):
        cuenta_de_arranque(_arranque(tmp_path, datos))
    with pytest.raises(ValueError, match="paso 06"):
        cuenta_de_arranque(tmp_path / "no_existe.yaml")


def test_limites_otra_moneda_se_niega():
    with pytest.raises(ValueError, match="COP"):
        limites_para_cuenta(PLANTILLA.read_text(), "act_1", "USD", "America/New_York")


def test_fijar_offset_solo_si_coincide_la_moneda(tmp_path):
    f = _limites(tmp_path)
    antes = f.read_bytes()
    assert fijar_offset(f, {"currency": "USD", "offset": 100}) is None
    assert fijar_offset(f, {"currency": "COP", "offset": None}) is None
    assert fijar_offset(f, {"currency": "COP", "offset": 100}) is None  # no es el oficial de COP
    assert f.read_bytes() == antes
    assert fijar_offset(f, {"currency": "COP", "offset": 1}) == 1
    assert cargar_limites(f).cuentas["act_999000111"].offset == 1
    assert (f.stat().st_mode & 0o777) == 0o600
    assert "# " in f.read_text()  # los comentarios sobreviven
    assert fijar_offset(f, {"currency": "COP", "offset": 1}) is None  # ya fijado: nada que cambiar


def test_fijar_offset_nunca_sobrescribe_otro(tmp_path, monkeypatch):
    f = _limites(tmp_path)
    monkeypatch.setitem(instalacion.OFFSETS_META, "COP", 100)  # el cargador solo admite el oficial: se simula
    f.write_text(f.read_text().replace("offset: null", "offset: 1"))
    os.chmod(f, 0o600)
    antes = f.read_bytes()
    with pytest.raises(OffsetDistinto):
        fijar_offset(f, {"currency": "COP", "offset": 100})
    assert f.read_bytes() == antes


def test_cli_instalacion(tmp_path):
    f = _arranque(tmp_path, {"act_id": "999000111", "moneda": "COP", "zona": "America/Bogota"})
    r = subprocess.run([sys.executable, "-I", "-m", "trovefy_ejecutor.instalacion", "cuenta", str(f)],
                       capture_output=True, text=True, check=True)
    assert r.stdout.split() == ["act_999000111", "COP", "America/Bogota"]
    r = subprocess.run([sys.executable, "-I", "-m", "trovefy_ejecutor.instalacion", "limites", str(PLANTILLA),
                        "act_999000111", "COP", "America/Bogota"], capture_output=True, text=True, check=True)
    assert "act_999000111" in r.stdout and ACT not in r.stdout
