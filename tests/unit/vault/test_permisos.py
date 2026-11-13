import json

from trovefy.cli import main
from trovefy.vault.permisos import generar_settings


def test_deny_fijo():
    deny = generar_settings()["permissions"]["deny"]
    # Sintaxis vigente: ruta absoluta con «//» (un solo «/» es relativo al origen de la config).
    for regla in ["Bash(curl*graph.facebook.com*)", "Bash(sudo *)", "Read(//home/trovefy-exec/**)",
                  "Edit(//var/spool/trovefy/procesadas/**)", "Bash(*graph.facebook.com*)",
                  "Bash(su *)", "Bash(* | sh)", "Bash(* | bash)"]:
        assert regla in deny


def test_deny_desde_meta_tools():
    s = generar_settings(["ads_update_entity", "ads_get_campaigns", "ads_library_search", "ads_create_campaign"])
    deny = s["permissions"]["deny"]
    assert "mcp__meta-ads__ads_update_entity" in deny
    assert "mcp__meta-ads__ads_create_campaign" in deny
    assert "mcp__meta-ads__ads_get_campaigns" not in deny
    assert "mcp__meta-ads__ads_library_search" not in deny
    allow = s["permissions"]["allow"]
    assert "mcp__meta-ads__ads_get_campaigns" in allow
    assert "mcp__meta-ads__ads_library_search" in allow
    assert "mcp__meta-ads__ads_update_entity" not in allow


def test_sin_meta_tools_deniega_todo_ads():
    s = generar_settings()
    assert "mcp__meta-ads__ads_*" in s["permissions"]["deny"]
    assert not any(a.startswith("mcp__") for a in s["permissions"]["allow"])


def test_allow_y_servidor_personalizado(tmp_path):
    s = generar_settings(["ads_x"], servidor_meta="fb", vault=tmp_path / "v")
    assert "Bash(trovefy *)" in s["permissions"]["allow"]
    assert f"Read(/{tmp_path / 'v'}/**)" in s["permissions"]["allow"]
    assert "mcp__fb__ads_x" in s["permissions"]["deny"]


def test_nunca_allow_all():
    texto = json.dumps(generar_settings(["ads_get_a"]))
    assert "dangerously" not in texto
    assert "bypassPermissions" not in texto
    assert generar_settings()["permissions"]["allow"] != ["*"]


def test_init_escribe_settings_sin_sobrescribir(tmp_path):
    v = tmp_path / "v"
    assert main(["cerebro", "init", "--vault", str(v)]) == 0
    ruta = v / ".claude/settings.json"
    s = json.loads(ruta.read_text())
    assert f"Read(/{v}/**)" in s["permissions"]["allow"]
    ruta.write_text('{"a": 1}')
    main(["cerebro", "init", "--vault", str(v)])
    assert ruta.read_text() == '{"a": 1}'


def test_permisos_regenera_con_meta_tools_json(tmp_path):
    v = tmp_path / "v"
    main(["cerebro", "init", "--vault", str(v)])
    (v / "config/meta_tools.json").write_text(json.dumps({"tools": [{"name": "ads_update_entity"}, {"name": "ads_get_x"}]}))
    assert main(["cerebro", "permisos", "--vault", str(v)]) == 0
    s = json.loads((v / ".claude/settings.json").read_text())
    assert "mcp__meta-ads__ads_update_entity" in s["permissions"]["deny"]
    assert "mcp__meta-ads__ads_get_x" in s["permissions"]["allow"]
    (v / "config/meta_tools.json").write_text(json.dumps(["ads_create_ad"]))
    main(["cerebro", "permisos", "--vault", str(v)])
    s = json.loads((v / ".claude/settings.json").read_text())
    assert "mcp__meta-ads__ads_create_ad" in s["permissions"]["deny"]


# --- Tarea 2: nombres reales, fusión y migración ---
import fnmatch
from pathlib import Path

import pytest
from trovefy.meta.herramientas import documento, escribir_meta_tools, herramientas_de
from trovefy.vault.permisos import (
    SettingsIlegible,
    es_lectura_meta,
    escribir_settings,
    fusionar_settings,
)

_FIX = Path(__file__).resolve().parents[2] / "fixtures/meta/tools_list.json"
NOMBRES_FIXTURE = [t["name"] for t in json.loads(_FIX.read_text())["tools"]]


def test_patrones_no_tapan_lecturas():
    s = generar_settings(NOMBRES_FIXTURE)
    lecturas = [n for n in NOMBRES_FIXTURE if es_lectura_meta(n)]
    assert lecturas
    for regla in s["permissions"]["deny"]:
        for n in lecturas:
            assert not fnmatch.fnmatchcase(f"mcp__meta-ads__{n}", regla), (regla, n)


def test_deny_solo_nombres_exactos_y_cada_escritura():
    s = generar_settings(NOMBRES_FIXTURE)["permissions"]
    # Sin comodines parciales en reglas MCP (soporte no confirmado): meta_guard es la barrera de lo desconocido.
    assert not [r for r in s["deny"] + s["allow"] if r.startswith("mcp__") and "*" in r]
    for n in NOMBRES_FIXTURE:
        if not es_lectura_meta(n):
            assert f"mcp__meta-ads__{n}" in s["deny"]


def test_clasifica_en_minusculas_y_conserva_el_nombre():
    s = generar_settings(["ADS_GET_X", "Ads_Library_Search", "Ads_Update_Y"])["permissions"]
    assert "mcp__meta-ads__ADS_GET_X" in s["allow"] and "mcp__meta-ads__Ads_Library_Search" in s["allow"]
    assert "mcp__meta-ads__Ads_Update_Y" in s["deny"]


def test_preparar_quita_el_deny_general_y_conserva_lo_del_usuario(tmp_path):
    main(["cerebro", "init", "--vault", str(tmp_path)])
    ruta = tmp_path / ".claude/settings.json"
    s0 = json.loads(ruta.read_text())
    assert "mcp__meta-ads__ads_*" in s0["permissions"]["deny"]
    s0["permissions"]["deny"].append("Bash(rm -rf *)")
    s0["permissions"]["allow"].append("Bash(mi-cosa)")
    ruta.write_text(json.dumps(s0))
    assert escribir_settings(tmp_path, sobrescribir=True, preparar=True) is True
    p = json.loads(ruta.read_text())["permissions"]
    assert "mcp__meta-ads__ads_*" not in p["deny"]
    assert "Bash(rm -rf *)" in p["deny"] and "Bash(mi-cosa)" in p["allow"] and "Bash(sudo *)" in p["deny"]


def test_preparar_no_pisa_settings_ilegible(tmp_path):
    ruta = tmp_path / ".claude/settings.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{roto")
    with pytest.raises(SettingsIlegible):
        escribir_settings(tmp_path, sobrescribir=True, preparar=True)
    assert ruta.read_text() == "{roto"


def test_fusion_conserva_lo_del_usuario():
    actual = {"permissions": {"allow": ["Bash(git status)"], "deny": ["Read(//secreto/**)", "mcp__meta-ads__ads_*"]},
              "hooks": {"x": 1}, "env": {"A": "1"}}
    s = fusionar_settings(actual, generar_settings(["ads_get_a", "ads_update_entity"]), {"mcp__meta-ads__ads_*"})
    assert "Bash(git status)" in s["permissions"]["allow"] and "Read(//secreto/**)" in s["permissions"]["deny"]
    assert "mcp__meta-ads__ads_*" not in s["permissions"]["deny"]
    assert s["hooks"] == {"x": 1} and s["env"] == {"A": "1"}
    assert len(s["permissions"]["deny"]) == len(set(s["permissions"]["deny"]))


def test_migra_deny_general_de_fase_0(tmp_path):
    main(["cerebro", "init", "--vault", str(tmp_path)])
    ruta = tmp_path / ".claude/settings.json"
    s0 = json.loads(ruta.read_text())
    s0["permissions"]["allow"].append("Bash(mi-cosa)")
    ruta.write_text(json.dumps(s0))
    (tmp_path / "config" / "permisos_generados.json").unlink(missing_ok=True)  # vault de la fase 0
    escribir_meta_tools(tmp_path, documento("meta-ads", herramientas_de([{"name": "ads_library_search"}]), "x", "2026-11-13"))
    escribir_settings(tmp_path, sobrescribir=True)
    p = json.loads(ruta.read_text())["permissions"]
    assert "mcp__meta-ads__ads_*" not in p["deny"]
    assert "mcp__meta-ads__ads_library_search" in p["allow"] and "Bash(mi-cosa)" in p["allow"]


def test_settings_ilegible_no_se_pisa(tmp_path):
    ruta = tmp_path / ".claude/settings.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{roto")
    with pytest.raises(SettingsIlegible):
        escribir_settings(tmp_path, sobrescribir=True)
    assert ruta.read_text() == "{roto"
    assert main(["cerebro", "permisos", "--vault", str(tmp_path)]) == 2
    assert ruta.read_text() == "{roto"


def test_servidor_sale_de_meta_tools_json(tmp_path):
    main(["cerebro", "init", "--vault", str(tmp_path)])
    escribir_meta_tools(tmp_path, documento("fb", herramientas_de([{"name": "ads_update_x"}]), "x", "2026-11-13"))
    escribir_settings(tmp_path, sobrescribir=True)
    assert "mcp__fb__ads_update_x" in json.loads((tmp_path / ".claude/settings.json").read_text())["permissions"]["deny"]
