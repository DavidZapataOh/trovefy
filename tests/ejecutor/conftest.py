"""Fixtures del ejecutor: límites en COP sobre la cuenta ficticia (resolución 17)."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
import yaml
from ejecutor.falsos.graph_falso import mundo_basico
from trovefy_ejecutor.auditoria import Auditoria
from trovefy_ejecutor.estado import Almacen
from trovefy_ejecutor.limites import Limites, cargar_limites

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
CUENTA = "act_0000000000000000"


def datos_limites(offset: int | None) -> dict:
    d = copy.deepcopy(yaml.safe_load(PLANTILLA.read_text()))
    d["cuentas"][CUENTA]["offset"] = offset
    d["cuentas"][CUENTA]["datasets_permitidos"] = ["8877665544"]
    return d


def _escribir(tmp_path: Path, d: dict) -> Limites:
    f = tmp_path / "limites.yaml"
    f.write_text(yaml.safe_dump(d))
    os.chmod(f, 0o600)
    return cargar_limites(f)


@pytest.fixture
def limites_cop(tmp_path: Path) -> Limites:
    return _escribir(tmp_path, datos_limites(1))


@pytest.fixture
def limites_cop_sin_offset(tmp_path: Path) -> Limites:
    return _escribir(tmp_path, datos_limites(None))


@pytest.fixture
def entorno(tmp_path: Path):
    """``(g, almacen, auditoria)``: Graph falso ``mundo_basico`` y almacén/auditoría reales en ``tmp_path``."""
    from trovefy_ejecutor import ejecutar as _ejecutar

    _ejecutar._EMITIDOS.clear()
    alm = Almacen(tmp_path / "estado.db")
    try:
        yield mundo_basico(), alm, Auditoria(tmp_path / "auditoria.jsonl")
    finally:
        alm.cerrar()
        _ejecutar._EMITIDOS.clear()
