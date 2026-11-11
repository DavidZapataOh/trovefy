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
