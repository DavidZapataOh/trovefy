"""CLI `trovefy economia` (plan 16, Tarea 9)."""

from datetime import date

import pytest
from trovefy import cli, economia_cli

HOY = date(2026, 11, 13)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(economia_cli, "_hoy", lambda: HOY)
    return v


def test_iniciar(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert (vault / "config/economia.yaml").is_file()
    assert "config/economia.yaml" in capsys.readouterr().out
    antes = (vault / "config/economia.yaml").read_text(encoding="utf-8")
    assert cli.main(["economia", "iniciar"]) == 0  # ya existe: no se toca
    assert "ya existe" in capsys.readouterr().out
    assert (vault / "config/economia.yaml").read_text(encoding="utf-8") == antes


def test_economia_fijar_y_ver(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    fuente = "https://precios.whop.test/tarifas"
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "0.03",
                     "--fuente", fuente]) == 0
    capsys.readouterr()
    assert cli.main(["economia", "ver"]) == 0
    out = capsys.readouterr().out
    linea = next(x for x in out.splitlines() if "plataformas.whop.comision_pct" in x)
    assert "0,03" in linea and fuente in linea and "2026-11-13" in linea
    assert "no medido" in next(x for x in out.splitlines() if x.lstrip().startswith("ruta_activa"))


def test_fijar_null_vuelve_a_no_medido(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "0.03",
                     "--fuente", "https://a.test/"]) == 0
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "null",
                     "--fuente", "pendiente de verificar"]) == 0
    capsys.readouterr()
    assert cli.main(["economia", "ver"]) == 0
    linea = next(x for x in capsys.readouterr().out.splitlines() if "plataformas.whop.comision_pct" in x)
    assert "no medido" in linea and "pendiente de verificar" in linea


def test_fijar_clave_inexistente(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_text(encoding="utf-8")
    assert cli.main(["economia", "fijar", "--clave", "plataformas.inventada.x", "--valor", "1",
                     "--fuente", "f"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and "plataformas.inventada.x" in err
    assert (vault / "config/economia.yaml").read_text(encoding="utf-8") == antes


def test_fijar_valor_invalido(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "1.5",
                     "--fuente", "f"]) == 2
    assert capsys.readouterr().err.startswith("Error: ")


def test_ver_sin_archivo(vault, capsys):
    assert cli.main(["economia", "ver"]) == 2
    assert "trovefy economia iniciar" in capsys.readouterr().err
