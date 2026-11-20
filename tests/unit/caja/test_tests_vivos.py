"""Tests vivos en config/caja.yaml sin perder comentarios (plan 22, Tarea 9)."""
from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy.caja.config import cargar_caja
from trovefy.caja.tests import abrir_test, actualizar_test, cerrar_test

PLANTILLA = Path(__file__).resolve().parents[3] / "templates" / "cerebro" / "config" / "caja.yaml"


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(PLANTILLA, tmp_path / "config" / "caja.yaml")
    return tmp_path


def test_abrir_test_conserva_comentarios(vault):
    antes = (vault / "config" / "caja.yaml").read_text()
    assert abrir_test(vault, "p-0099-prueba-abc123", "ZZ", "9000001", Decimal(25))
    despues = (vault / "config" / "caja.yaml").read_text()
    comentarios = [ln for ln in antes.splitlines() if "#" in ln]
    for ln in comentarios:
        if ln.startswith("tests:"):
            assert "# provisional" in despues
        else:
            assert ln in despues
    t = cargar_caja(vault).tests
    assert len(t) == 1 and t[0].campana_id == "9000001" and t[0].estado == "vivo" and t[0].presupuesto_diario == 2500


def test_abrir_es_idempotente(vault):
    assert abrir_test(vault, "p-1", "ZZ", "1", 25)
    assert not abrir_test(vault, "p-1", "ZZ", "1", 25)
    assert len(cargar_caja(vault).tests) == 1


def test_actualizar_y_cerrar(vault):
    abrir_test(vault, "p-1", "ZZ", "1", 25)
    assert actualizar_test(vault, "1", diario_usd=Decimal(35), ventas=2)
    t = cargar_caja(vault).tests[0]
    assert t.presupuesto_diario == 3500 and t.ventas == 2
    assert cerrar_test(vault, "1")
    assert cargar_caja(vault).tests[0].estado == "cerrado"
    with pytest.raises(KeyError):
        actualizar_test(vault, "999", ventas=1)
