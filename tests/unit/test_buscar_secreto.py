import pytest
from trovify import secretos
from trovify.cli import main


def _token_sk():
    return "sk" + "-" + "q" * 24


def test_buscar_secreto_publico():
    assert secretos.buscar_secreto("hola " + _token_sk()) == "clave sk-"
    assert secretos.buscar_secreto("sin nada raro") is None
    assert secretos.buscar_secreto("la URL lleva access" + "_token" + "= sin valor") is None


def test_sin_hooks_error_claro(monkeypatch, tmp_path):
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "hooks"])
    with pytest.raises(secretos.RevisionSecretosNoDisponible):
        secretos.buscar_secreto("x")


def test_cli_hecho_sin_hooks_no_lanza_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "hooks"])
    v = tmp_path / "v"
    assert main(["arranque", "hecho", "05", "--dato", "nombre=Mi tienda", "--vault", str(v)]) == 2
    err = capsys.readouterr().err
    assert "secretos" in err and "Traceback" not in err and "escribir en el vault" not in err
