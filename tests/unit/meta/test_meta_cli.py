import json
from pathlib import Path

from trovefy.cli import main

FIX = Path(__file__).resolve().parents[2] / "fixtures/meta/tools_list.json"


def _vault(tmp_path):
    v = tmp_path / "v"
    assert main(["cerebro", "init", "--vault", str(v)]) == 0
    return v


def _importar(v, f, *extra):
    return main(["meta", "herramientas", "importar", str(f), "--servidor", "meta-ads", "--vault", str(v), *extra])


def test_importar_escribe_y_deniega(tmp_path, capsys):
    v = _vault(tmp_path)
    assert _importar(v, FIX) == 0
    deny = json.loads((v / ".claude/settings.json").read_text())["permissions"]["deny"]
    assert "mcp__meta-ads__ads_update_entity" in deny and "mcp__meta-ads__ads_estimate_reach" in deny
    assert "dudosa" in capsys.readouterr().out
    assert "herramientas importadas" in (v / "log.md").read_text()


def test_importar_avisa_de_nuevas_y_desaparecidas(tmp_path, capsys):
    v = _vault(tmp_path)
    _importar(v, FIX)
    capsys.readouterr()
    datos = json.loads(FIX.read_text())
    for t in datos["tools"]:
        if t["name"] == "ads_update_entity":
            t["name"] = "ads_update_entity_v2"
    f = tmp_path / "otro.json"
    f.write_text(json.dumps(datos))
    assert _importar(v, f) == 0
    out = capsys.readouterr().out
    assert "Nuevas: ads_update_entity_v2" in out and "Desaparecidas o renombradas: ads_update_entity" in out


def test_importar_rechaza_archivo_con_secreto(tmp_path, capsys):
    v = _vault(tmp_path)
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"tools": [{"name": "ads_get_a", "description": "EAAB" + "x" * 40}]}))
    assert _importar(v, f) == 2
    cap = capsys.readouterr()
    assert "EAAB" not in cap.err + cap.out and not (v / "config/meta_tools.json").exists()


def test_importar_sin_ads_library_search_avisa(tmp_path, capsys):
    v = _vault(tmp_path)
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"tools": [{"name": "ads_get_a"}]}))
    assert _importar(v, f) == 0
    assert "/cazar no podrá usar el MCP" in capsys.readouterr().out


def test_importar_codigos(tmp_path):
    v = _vault(tmp_path)
    f = tmp_path / "vacia.json"
    f.write_text('{"tools": []}')
    assert _importar(v, f) == 1
    g = tmp_path / "sin_srv.json"
    g.write_text('{"tools": [{"name": "ads_get_a"}]}')
    assert main(["meta", "herramientas", "importar", str(g), "--vault", str(v)]) == 1
    h = tmp_path / "mala.json"
    h.write_text("{no")
    assert _importar(v, h) == 2
    grande = tmp_path / "grande.json"
    grande.write_text(" " * (2 * 1024 * 1024 + 1))
    assert _importar(v, grande) == 2


def test_settings_ilegible_no_se_pisa_al_importar(tmp_path):
    v = _vault(tmp_path)
    (v / ".claude/settings.json").write_text("{roto")
    assert _importar(v, FIX) == 2
    assert (v / ".claude/settings.json").read_text() == "{roto"


def test_mostrar(tmp_path, capsys):
    v = _vault(tmp_path)
    assert main(["meta", "herramientas", "mostrar", "--vault", str(v)]) == 1
    _importar(v, FIX)
    capsys.readouterr()
    assert main(["meta", "herramientas", "mostrar", "--vault", str(v)]) == 0
    assert "lectura · ads_library_search" in capsys.readouterr().out


def test_importar_limite_de_2_mb(tmp_path, capsys):
    v = _vault(tmp_path)
    grande = tmp_path / "grande.json"
    grande.write_text('{"tools": []}' + " " * (2 * 1024 * 1024))
    assert _importar(v, grande) == 2
    assert "más de 2 MB" in capsys.readouterr().err and not (v / "config/meta_tools.json").exists()


def test_servidor_con_caracteres_raros_se_rechaza(tmp_path, capsys):
    v = _vault(tmp_path)
    for malo in ["meta ads", "a;b", "x/y", "ñ", ""]:
        assert main(["meta", "herramientas", "importar", str(FIX), "--servidor", malo, "--vault", str(v)]) == 2, malo
        assert main(["meta", "herramientas", "preparar", "--servidor", malo, "--vault", str(v)]) == 2, malo
    f = tmp_path / "srv.json"
    f.write_text(json.dumps({"tools": [{"name": "mcp__a b__ads_get_a"}]}))  # servidor deducido del volcado
    assert main(["meta", "herramientas", "importar", str(f), "--vault", str(v)]) == 2
    assert not (v / "config/meta_tools.json").exists()


def test_preparar_quita_el_deny_general(tmp_path, capsys):
    v = _vault(tmp_path)
    ruta = v / ".claude/settings.json"
    s = json.loads(ruta.read_text())
    s["permissions"]["allow"].append("Bash(mi-cosa)")
    ruta.write_text(json.dumps(s))
    assert main(["meta", "herramientas", "preparar", "--vault", str(v)]) == 0
    p = json.loads(ruta.read_text())["permissions"]
    assert "mcp__meta-ads__ads_*" not in p["deny"] and "Bash(mi-cosa)" in p["allow"]
    out = capsys.readouterr().out
    assert "meta_guard" in out and "reinicia Claude Code" in out


def test_preparar_no_pisa_settings_ilegible(tmp_path):
    v = _vault(tmp_path)
    (v / ".claude/settings.json").write_text("{roto")
    assert main(["meta", "herramientas", "preparar", "--vault", str(v)]) == 2
    assert (v / ".claude/settings.json").read_text() == "{roto"


def test_preparar_con_meta_tools_roto_no_revienta(tmp_path, monkeypatch, capsys):
    from trovefy.cli import main
    monkeypatch.setenv("TROVEFY_VAULT", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/meta_tools.json").write_text("{roto")
    assert main(["meta", "herramientas", "preparar"]) == 2
    assert "Traceback" not in capsys.readouterr().err
    assert not (tmp_path / ".claude/settings.json").exists()
