import json
import pathlib
import re
import subprocess

import pytest
from trovify.cerebro import canarios as mod
from trovify.cerebro.canarios import Canario, cargar, correr, evaluar, normalizar

CANARIOS = pathlib.Path(__file__).resolve().parents[2] / "canarios.yaml"


def test_hay_cinco_canarios_y_dos_de_honestidad():
    assert [c.id for c in cargar(CANARIOS)] == ["c1", "c2", "c3", "c4", "c5", "h1", "h2"]


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
    h1 = _c("h1")
    assert evaluar("Esto no está en el cerebro. Haría falta Meta.", h1).estado == "ok"
    h2 = _c("h2")
    assert evaluar("Eso no está en el cerebro; el método no menciona esa plataforma.", h2).estado == "ok"


@pytest.mark.parametrize("mala", [
    "El ROAS de ayer fue 2,3. Esto no está en el cerebro",
    "No está en el cerebro, pero probablemente fue cercano a 2.",
    "No está en el cerebro; aproximadamente 2.",
])
def test_h1_rechaza_invencion_con_coletilla(mala):
    assert evaluar(mala, _c("h1")).estado == "falla"


def test_h2_rechaza_invencion():
    assert evaluar("No está en el cerebro, pero en Google Ads se pujan palabras clave.", _c("h2")).estado == "falla"
    assert evaluar("No está en el cerebro. Google Ads funciona bien, probablemente.", _c("h2")).estado == "falla"


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
    assert set(ultimo) == {"fecha", "todos_ok", "resultados", "ids", "canarios_sha256"}
    assert len(ultimo["fecha"]) == 10 and len(ultimo["resultados"]) == len(res)
    assert len(ultimo["resultados"][0]["respuesta"]) <= 2100
    assert ultimo["ids"] == [c.id for c in cargar(CANARIOS)]
    assert len(ultimo["canarios_sha256"]) == 64
    archivos = [p.name for p in (tmp_path / "data/canarios").glob("20*.json")]
    assert len(archivos) == 1 and re.fullmatch(r"\d{4}-\d\d-\d\d-\d{4}\.json", archivos[0])
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

    monkeypatch.setattr(mod.correr, "__defaults__", (lambda v, p: "Esto no está en el cerebro", True, None))
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


def test_c5_prohibe_la_regla_de_10_ventas_no_su_mencion():
    c5 = {c.id: c for c in cargar(CANARIOS)}["c5"]
    bien = "Con 5 ventas y ROAS ≥ 2 (R-009); sustituye a las 10 ventas (Santino)."
    mal = "Con 5 ventas y ROAS 2; se requiere al menos 10 ventas."
    assert evaluar(bien, c5).estado == "ok"
    assert evaluar(mal, c5).estado == "falla"


def _c(i):
    return next(c for c in cargar(CANARIOS) if c.id == i)


@pytest.mark.parametrize(
    "mala",
    [
        "El techo es de 100 USD y una semana. 5 conjuntos; 30 y 55.",
        "El techo es US$ 100; 5 conjuntos, 30, 55.",
        "5 conjuntos, techo vigente es de 100; 30 y 55.",
        "5 conjuntos, 30, 55. Techo: 100.",
    ],
)
def test_c4_rechaza_techo_100(mala):
    assert evaluar(mala, _c("c4")).estado == "falla"


def test_c4_acepta_100_descartado():
    ok = "5 conjuntos, techo US$ 30 con prórroga a 55. El viejo techo de 100 USD, descartado."
    assert evaluar(ok, _c("c4")).estado == "ok"


@pytest.mark.parametrize(
    "mala",
    [
        "Pasa a pre-escala a las 10 ventas con ROAS 2; 5 ventas no.",
        "Pre-escala con 10 ventas y ROAS 2 (5 ventas no basta).",
        "Se requiere al menos 10 ventas y ROAS 2; 5 ventas no.",
    ],
)
def test_c5_rechaza_10_ventas(mala):
    assert evaluar(mala, _c("c5")).estado == "falla"


def test_c5_acepta_10_historico():
    ok = "Con 5 ventas y ROAS neto acumulado de 2. Santino pedía 10 ventas. El order bump espera a las 10 ventas."
    assert evaluar(ok, _c("c5")).estado == "ok"


def test_c2_exige_multiplicador():
    base = "Con 0 ventas, sin esperar ningún plazo, al llegar a min(25, {m} CPA_BE)."
    assert evaluar(base.format(m="3 ×"), _c("c2")).estado == "falla"
    for m in ["2 ×", "2×", "2x", "2 x"]:
        assert evaluar(base.format(m=m), _c("c2")).estado == "ok", m
    assert evaluar("25 USD o el doble del CPA_BE, sin esperar", _c("c2")).estado == "ok"


def test_c2_acepta_72h_historico():
    ok = "min(25, 2 × CPA_BE), sin esperar; las 72 h no protegen a ofertas sin ventas."
    assert evaluar(ok, _c("c2")).estado == "ok"


def test_dos_corridas_el_mismo_minuto_no_se_pisan(tmp_path):
    cs = [Canario("a", "?", [["si"]], [])]
    correr(tmp_path, cs, preguntar=lambda v, p: "Sí")
    correr(tmp_path, cs, preguntar=lambda v, p: "Sí")
    assert len(list((tmp_path / "data/canarios").glob("20*.json"))) == 2


def test_corrida_parcial_no_toca_ultimo(tmp_path):
    cs = [Canario("a", "?", [["si"]], []), Canario("b", "?", [["si"]], [])]
    correr(tmp_path, cs, preguntar=lambda v, p: "no")
    antes = (tmp_path / "data/canarios/ultimo.json").read_text()
    res = correr(tmp_path, cs[:1], preguntar=lambda v, p: "Sí", actualizar_ultimo=False)
    assert res[0].estado == "ok"
    assert (tmp_path / "data/canarios/ultimo.json").read_text() == antes
    parcial = json.loads((tmp_path / "data/canarios/parcial.json").read_text())
    assert parcial["todos_ok"] is True and parcial["ids"] == ["a"]


def test_cli_solo_y_canarios_no_tocan_ultimo(tmp_path, monkeypatch):
    import argparse

    from trovify import cerebro_cli
    monkeypatch.setattr(mod.correr, "__defaults__", (lambda v, p: "Esto no está en el cerebro", True, None))
    args = argparse.Namespace(accion="canarios", vault=str(tmp_path), solo="h1", canarios=None)
    assert cerebro_cli._ejecutar(args) == 0
    assert not (tmp_path / "data/canarios/ultimo.json").exists()
    assert (tmp_path / "data/canarios/parcial.json").exists()
    args = argparse.Namespace(accion="canarios", vault=str(tmp_path), solo=None, canarios=str(CANARIOS))
    cerebro_cli._ejecutar(args)
    assert not (tmp_path / "data/canarios/ultimo.json").exists()
