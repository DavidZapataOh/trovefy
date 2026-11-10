import importlib
import sys

import pytest
from trovify import cli


@pytest.fixture
def registro_aislado(monkeypatch):
    monkeypatch.setattr(cli, "_REGISTRO", {})


def test_registrar_duplicado_lanza_valueerror(registro_aislado):
    cli.registrar("x", lambda p: None, lambda a: 0)
    with pytest.raises(ValueError):
        cli.registrar("x", lambda p: None, lambda a: 0)


def test_registrar_version_esta_reservado(registro_aislado):
    with pytest.raises(ValueError):
        cli.registrar("version", lambda p: None, lambda a: 0)


def test_subcomando_registrado_se_ejecuta(registro_aislado):
    cli.registrar("hola", lambda p: None, lambda a: 7)
    assert cli.main(["hola"]) == 7
    assert cli.main(["version"]) == 0


def test_descubre_modulos_cli(registro_aislado, tmp_path, monkeypatch):
    import trovify

    modulo = tmp_path / "zz_prueba_cli.py"
    modulo.write_text(
        "from trovify.cli import registrar\n"
        "registrar('zz-prueba', lambda p: None, lambda a: 9)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(trovify, "__path__", [*trovify.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "trovify.zz_prueba_cli", raising=False)
    importlib.invalidate_caches()
    assert cli.main(["zz-prueba"]) == 9
