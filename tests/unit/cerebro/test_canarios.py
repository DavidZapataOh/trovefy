import json
import pathlib
import subprocess

import pytest
from trovify.cerebro import canarios as mod
from trovify.cerebro.canarios import Canario, cargar, correr, evaluar, normalizar

CANARIOS = pathlib.Path(__file__).resolve().parents[2] / "canarios.yaml"


def test_hay_cinco_canarios_y_uno_de_honestidad():
    assert [c.id for c in cargar(CANARIOS)] == ["c1", "c2", "c3", "c4", "c5", "h1"]


def test_normalizar():
    assert normalizar("  Vía   0,60 y 1,5\nPÁGO ") == "via 0.60 y 1.5 pago"
    assert normalizar("a, b") == "a, b"


def test_evaluar_normaliza():
    c = Canario("c1", "?", [["3"], ["pago iniciado", "pagos iniciados"], ["0.60", "0.6"]], [])
    r = evaluar("Se apaga con US$ 3 gastados y 0 Pagos Iniciados, o con CPC > 0,60 (vía R-005).", c)
    assert r.estado == "ok" and r.faltan == []


def test_limite_de_palabra():
    c = Canario("c1", "?", [["3"]], [])
    assert evaluar("En 2026 gastamos 30 USD", c).estado == "falla"


def test_faltan_lista_primera_alternativa():
    c = Canario("c1", "?", [["3"], ["x", "y"]], [])
    r = evaluar("hay 3", c)
    assert r.estado == "falla" and r.faltan == ["x"]


def test_prohibido_hace_fallar():
    c = Canario("c4", "?", [["30"]], ["100 usd"])
    assert evaluar("Techo 30 USD, antes era 100 USD", c).estado == "falla"


def test_alternativa_con_simbolos_se_escapa():
    c = Canario("c4", "?", [["30"]], ["us$ 100"])
    assert evaluar("Techo 30; antes US$ 100", c).estado == "falla"
    assert evaluar("Techo 30; antes USX 100", c).estado == "ok"


def test_honestidad():
    h1 = cargar(CANARIOS)[-1]
    assert evaluar("Esto no está en el cerebro. Haría falta Meta.", h1).estado == "ok"


def test_error_de_ejecucion_no_aprueba(tmp_path):
    def revienta(vault, pregunta):
        raise TimeoutError("300 s")

    res = correr(tmp_path, cargar(CANARIOS), preguntar=revienta)
    assert all(r.estado == "error" for r in res)
    ultimo = json.loads((tmp_path / "data/canarios/ultimo.json").read_text())
    assert ultimo["todos_ok"] is False


def test_correr_guarda_contrato_y_log(tmp_path):
    res = correr(tmp_path, cargar(CANARIOS), preguntar=lambda v, p: "x" * 5000)
    ultimo = json.loads((tmp_path / "data/canarios/ultimo.json").read_text())
    assert set(ultimo) == {"fecha", "todos_ok", "resultados"}
    assert len(ultimo["fecha"]) == 10 and len(ultimo["resultados"]) == len(res)
    assert len(ultimo["resultados"][0]["respuesta"]) <= 2100
    assert (tmp_path / f"data/canarios/{ultimo['fecha']}.json").exists()
    assert "canarios" in (tmp_path / "log.md").read_text()


def test_correr_todos_ok(tmp_path):
    cs = [Canario("a", "?", [["si"]], [])]
    correr(tmp_path, cs, preguntar=lambda v, p: "Sí")
    assert json.loads((tmp_path / "data/canarios/ultimo.json").read_text())["todos_ok"] is True


def test_preguntar_a_claude_comando(tmp_path, monkeypatch):
    visto = {}

    def falso(cmd, **kw):
        visto.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="hola", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", falso)
    assert mod.preguntar_a_claude(tmp_path, "¿q?") == "hola"
    assert visto["cmd"][:3] == ["claude", "-p", "/trovify:consultar ¿q?"]
    assert "Read,Grep,Glob" in visto["cmd"]
    assert "--dangerously-skip-permissions" not in visto["cmd"]
    assert visto["cwd"] == tmp_path and visto["timeout"] == 300


def test_preguntar_a_claude_codigo_distinto_de_cero(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="mal"))
    with pytest.raises(RuntimeError):
        mod.preguntar_a_claude(tmp_path, "q")


def test_cargar_defecto_desde_el_paquete():
    assert next(c.id for c in cargar()) == "c1"


def test_cli_canarios(tmp_path, monkeypatch, capsys):
    from trovify import cerebro_cli

    monkeypatch.setattr(mod.correr, "__defaults__", (lambda v, p: "Esto no está en el cerebro",))
    import argparse
    args = argparse.Namespace(accion="canarios", vault=str(tmp_path), solo="h1", canarios=str(CANARIOS))
    assert cerebro_cli._ejecutar(args) == 0
    assert capsys.readouterr().out.startswith("h1\tok")
    args.solo = "c1"
    assert cerebro_cli._ejecutar(args) == 1
    assert "c1\tfalla\tfaltan: 3" in capsys.readouterr().out
    args.solo = "zz"
    assert cerebro_cli._ejecutar(args) == 2


def test_c2_acepta_parafrasis():
    c2 = {c.id: c for c in cargar(CANARIOS)}["c2"]
    ok = "No hay que esperar ningún plazo: se corta con 2 × CPA_BE, o 25 USD."
    assert evaluar(ok, c2).estado == "ok"


def test_c4_techo_viejo_descartado_y_techo_prohibido():
    c4 = {c.id: c for c in cargar(CANARIOS)}["c4"]
    base = "5 conjuntos, prórroga hasta 55. "
    bien = base + "El techo es 30 y el viejo documento decía 100 USD (descartado)."
    mal = base + "El techo es de 100 USD, con 30 de partida."
    assert evaluar(bien, c4).estado == "ok"
    assert evaluar(mal, c4).estado == "falla"
