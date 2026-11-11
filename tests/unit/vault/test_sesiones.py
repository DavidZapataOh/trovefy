from datetime import datetime
from zoneinfo import ZoneInfo

from trovefy.vault.frontmatter import leer
from trovefy.vault.sesiones import escribir_traspaso, ultimo_traspaso

BOGOTA = ZoneInfo("America/Bogota")


def test_traspaso_y_retomar(tmp_path):
    t1 = datetime(2026, 11, 10, 9, 0, tzinfo=BOGOTA)
    t2 = datetime(2026, 11, 10, 18, 5, tzinfo=BOGOTA)
    escribir_traspaso(tmp_path, ["caza"], ["auditar"], [], [], t1)
    r = escribir_traspaso(
        tmp_path, ["auditar RO"], ["elegir país"], ["Usuario: RO primero"],
        ["productos/p-0001/AUDITORIA.md"], t2,
    )
    assert r.name == "2026-11-10-1805.md"
    assert ultimo_traspaso(tmp_path) == r


def test_contenido_y_frontmatter(tmp_path):
    t = datetime(2026, 11, 10, 18, 5, tzinfo=BOGOTA)
    r = escribir_traspaso(tmp_path, ["a"], ["b"], ["c"], ["d.md"], t)
    meta, cuerpo = leer(r)
    assert meta["tipo"] == "traspaso" and meta["fecha"] == "2026-11-10"
    for seccion in ("## Hecho", "## Pendiente", "## Decisiones del usuario", "## Archivos tocados"):
        assert seccion in cuerpo
    assert "- c" in cuerpo and "- d.md" in cuerpo


def test_sin_traspasos(tmp_path):
    assert ultimo_traspaso(tmp_path) is None
    (tmp_path / "sesiones").mkdir()
    (tmp_path / "sesiones/.gitkeep").write_text("")
    assert ultimo_traspaso(tmp_path) is None


def test_cli_traspaso_retomar_lint(tmp_path, monkeypatch, capsys):
    import argparse
    import io
    import json
    import sys

    from trovefy.cerebro_cli import _configurar, _ejecutar
    from trovefy.vault.andamio import crear_vault

    v = tmp_path / "v"
    crear_vault(v)
    def correr(*argv, stdin=""):
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        p = argparse.ArgumentParser()
        _configurar(p)
        return _ejecutar(p.parse_args([*argv, "--vault", str(v)]))
    assert correr("lint") == 0
    assert correr("retomar") == 0 and "No hay traspasos" in capsys.readouterr().out
    entrada = json.dumps({"hecho": ["x"], "pendiente": ["y"], "decisiones": [], "archivos": ["index.md"]})
    assert correr("traspaso", "--json", "-", stdin=entrada) == 0
    assert correr("retomar") == 0 and "## Pendiente" in capsys.readouterr().out
    assert correr("traspaso", "--json", "-", stdin='{"hecho": "no-lista"}') == 2
    (v / "wiki/mercados/zz.md").write_text("sin frontmatter [[nada]]\n")
    assert correr("lint") == 1


def test_mismo_minuto_no_sobrescribe(tmp_path):
    t = datetime(2026, 11, 10, 18, 5, tzinfo=BOGOTA)
    r1 = escribir_traspaso(tmp_path, ["uno"], [], [], [], t)
    r2 = escribir_traspaso(tmp_path, ["dos"], [], [], [], t)
    r3 = escribir_traspaso(tmp_path, ["tres"], [], [], [], t)
    assert [r.name for r in (r1, r2, r3)] == [
        "2026-11-10-1805.md", "2026-11-10-1805-2.md", "2026-11-10-1805-3.md"]
    assert "uno" in r1.read_text() and "dos" in r2.read_text()
    assert ultimo_traspaso(tmp_path) == r3
    t2 = datetime(2026, 11, 10, 18, 6, tzinfo=BOGOTA)
    r4 = escribir_traspaso(tmp_path, ["cuatro"], [], [], [], t2)
    assert ultimo_traspaso(tmp_path) == r4


def test_cli_traspaso_escribe_log(tmp_path, monkeypatch):
    import io
    import json

    from trovefy import cli
    from trovefy.vault.andamio import crear_vault

    v = tmp_path / "v"
    crear_vault(v)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hecho": ["x"]})))
    antes = (v / "log.md").read_text().count("\n")
    assert cli.main(["cerebro", "traspaso", "--json", "-"]) == 0
    lineas = (v / "log.md").read_text().splitlines()
    assert len(lineas) == antes + 1 and "· cerrar ·" in lineas[-1] and "sesiones/" in lineas[-1]
