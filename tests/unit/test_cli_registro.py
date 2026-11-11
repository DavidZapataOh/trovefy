import importlib
import sys

import pytest
from trovefy import cli


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
    import trovefy

    modulo = tmp_path / "zz_prueba_cli.py"
    modulo.write_text(
        "from trovefy.cli import registrar\n"
        "registrar('zz-prueba', lambda p: None, lambda a: 9)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(trovefy, "__path__", [*trovefy.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "trovefy.zz_prueba_cli", raising=False)
    importlib.invalidate_caches()
    assert cli.main(["zz-prueba"]) == 9


def test_modulo_roto_no_impide_el_resto(registro_aislado, tmp_path, monkeypatch, capsys):
    import trovefy

    (tmp_path / "zz_roto_cli.py").write_text("import modulo_que_no_existe_zz\n", encoding="utf-8")
    monkeypatch.setattr(trovefy, "__path__", [*trovefy.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "trovefy.zz_roto_cli", raising=False)
    importlib.invalidate_caches()
    assert cli.main(["version"]) == 0
    err = capsys.readouterr().err
    assert "aviso: no se pudo cargar trovefy.zz_roto_cli: ModuleNotFoundError" in err


def test_registrar_sin_ayuda_sigue_funcionando(registro_aislado):
    cli.registrar("sin-ayuda", lambda p: None, lambda a: 3)
    assert cli.main(["sin-ayuda"]) == 3


def test_ayuda_del_subcomando_sale_en_help(registro_aislado, capsys):
    cli.registrar("zz-ayuda", lambda p: None, lambda a: 0, ayuda="hace algo útil")
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "zz-ayuda" in out
    assert "hace algo útil" in out


def test_todos_los_subcomandos_reales_tienen_ayuda(registro_aislado, monkeypatch, capsys):
    # Se reimportan los *_cli reales para que se registren en el registro aislado.
    for nombre in [m for m in sys.modules if m.startswith("trovefy.") and m.endswith("_cli")]:
        monkeypatch.delitem(sys.modules, nombre)
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for nombre in ("arranque", "auditar", "caza", "cerebro", "navegador", "rutinas"):
        assert nombre in out
    assert "==SUPPRESS==" not in out
    for nombre, (configurar, _ejecutar, ayuda) in cli._REGISTRO.items():
        assert ayuda.strip(), f"el subcomando «{nombre}» no tiene ayuda"
