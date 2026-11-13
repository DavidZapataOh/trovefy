import shutil
import sys
from pathlib import Path

import pytest
from trovefy import cli
from trovefy.aprobaciones import fuentes

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "aprobaciones"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    shutil.copytree(FIX, v)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "sin-spool"))
    return v


def test_listar_agrupa_en_salida(entorno, capsys):
    assert cli.main(["aprobaciones", "listar"]) == 0
    out = capsys.readouterr().out
    assert "pendientes" in out and "P-20261112-901" in out and "tú, por Telegram" in out
    assert "--todas" in out and "P-20261112-001" not in out


def test_listar_todas(entorno, capsys):
    assert cli.main(["aprobaciones", "listar", "--todas"]) == 0
    out = capsys.readouterr().out
    assert "P-20261112-002" in out and "caducadas (1)" in out and "P-20261112-001" in out


def test_estado_sin_ejecutor_sale_0(entorno, capsys):
    assert cli.main(["aprobaciones", "estado"]) == 0
    assert "El ejecutor aún no está instalado: se instala con el plan 12 y /arranque." in capsys.readouterr().out


def test_explicar_id_invalido_sale_2(entorno, capsys):
    assert cli.main(["aprobaciones", "explicar", "../config"]) == 2
    assert "id" in capsys.readouterr().err


def test_explicar_ok(entorno, capsys):
    assert cli.main(["aprobaciones", "explicar", "P-20261112-003"]) == 0
    assert "campo no permitido: x" in capsys.readouterr().out


def test_probar_deposita_noop(entorno, monkeypatch, capsys):
    visto = {}

    def falso(vault, datos, ahora=None):
        visto["datos"] = datos
        return "P-20261113-001"

    monkeypatch.setattr(fuentes, "depositar", falso)
    assert cli.main(["aprobaciones", "probar"]) == 0
    assert "P-20261113-001" in capsys.readouterr().out
    from trovefy_ejecutor.esquema import cargar_propuesta
    d = dict(visto["datos"], id="P-20261113-001", creada="2026-11-13T10:00:00-05:00")
    assert cargar_propuesta(d).tipo == "noop"


def test_probar_sin_buzon(entorno, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "trovefy.buzon", None)
    assert cli.main(["aprobaciones", "probar"]) == 1
    assert "plan 12" in capsys.readouterr().err
