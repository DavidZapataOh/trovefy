import json
from pathlib import Path

import pytest
from trovefy.arranque.estado import marcar_hecho
from trovefy.arranque.verificadores import REGISTRO
from trovefy.arranque.verificadores.mcp import verificar_mcp
from trovefy.cli import main
from trovefy.meta.herramientas import clasificar
from trovefy.vault.andamio import crear_vault

FIX = Path(__file__).resolve().parents[2] / "fixtures/meta/tools_list.json"
NOMBRES = [t["name"] for t in json.loads(FIX.read_text())["tools"]]
ESCRITURAS = [n for n in NOMBRES if clasificar(n)[0] == "escritura"]


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    return v


@pytest.fixture
def importado(vault):
    assert main(["meta", "herramientas", "importar", str(FIX), "--servidor", "meta-ads", "--vault", str(vault)]) == 0
    return vault


def _settings(v):
    return v / ".claude/settings.json"


def _editar_deny(v, f):
    s = json.loads(_settings(v).read_text())
    s["permissions"]["deny"] = f(s["permissions"]["deny"])
    _settings(v).write_text(json.dumps(s))


def test_registrado():
    assert REGISTRO["14"] is verificar_mcp


def test_14_ok_con_fixture(importado):
    r = verificar_mcp(importado)
    assert r.ok is True, r.motivo
    assert r.datos["escritura"] == str(len(ESCRITURAS)) and r.datos["servidor"] == "meta-ads"
    assert r.datos["lectura"] == str(len(NOMBRES) - len(ESCRITURAS))
    assert r.datos["ads_library_search"] == "si"
    assert "config/meta_tools.json" in r.evidencia
    assert any(e.startswith("config/evidencia/14-mcp-") for e in r.evidencia)
    assert all((importado / e).is_file() for e in r.evidencia)


def test_14_sin_meta_tools_falla(vault):
    r = verificar_mcp(vault)
    assert r.ok is False and "trovefy meta herramientas importar" in " ".join(r.arreglos)


def test_14_deny_desactualizado_falla(importado):
    _editar_deny(importado, lambda d: [x for x in d if x != "mcp__meta-ads__ads_update_entity"])
    r = verificar_mcp(importado)
    assert r.ok is False and "permissions.deny no está al día" in r.motivo
    assert "ads_update_entity" in r.motivo


def test_14_lectura_denegada_falla(importado):
    _editar_deny(importado, lambda d: [*d, "mcp__meta-ads__ads_library_search"])
    r = verificar_mcp(importado)
    assert r.ok is False and "ads_library_search" in r.motivo


def test_14_deny_general_falla(importado):
    _editar_deny(importado, lambda d: [*d, "mcp__meta-ads__ads_*"])
    r = verificar_mcp(importado)
    assert r.ok is False and "ads_get_campaigns" in r.motivo


def test_14_patron_que_tapa_una_lectura_falla(importado):
    _editar_deny(importado, lambda d: [*d, "mcp__meta-ads__ads_get_*"])
    assert verificar_mcp(importado).ok is False


def test_14_settings_ilegible_o_ausente_falla(importado):
    _settings(importado).write_text("{roto")
    r = verificar_mcp(importado)
    assert r.ok is False and r.arreglos
    assert _settings(importado).read_text() == "{roto"
    _settings(importado).unlink()
    assert verificar_mcp(importado).ok is False


def test_14_meta_tools_corrupto_falla(importado):
    (importado / "config/meta_tools.json").write_text("{roto")
    r = verificar_mcp(importado)
    assert r.ok is False and "Traceback" not in r.motivo


def test_14_lista_vacia_falla(importado):
    (importado / "config/meta_tools.json").write_text(json.dumps({"servidor": "meta-ads", "tools": []}))
    assert verificar_mcp(importado).ok is False


def test_14_informa_p02(importado):
    assert "OAuth: no medido (P-02)" in verificar_mcp(importado).motivo
    marcar_hecho(importado, "14", datos={"oauth": "lectura"})
    r = verificar_mcp(importado)
    assert r.datos["oauth"] == "lectura" and "OAuth: lectura" in r.motivo


def test_14_sin_ads_library_search_verifica_con_aviso(vault):
    f = vault / "a.json"
    f.write_text(json.dumps({"tools": [{"name": "ads_get_a"}, {"name": "ads_update_b"}]}))
    assert main(["meta", "herramientas", "importar", str(f), "--servidor", "meta-ads", "--vault", str(vault)]) == 0
    r = verificar_mcp(vault)
    assert r.ok is True and "/cazar no podrá usar el MCP" in r.motivo and r.datos["ads_library_search"] == "no"


def test_14_sin_meta_tools_pide_preparar_antes(vault):
    r = verificar_mcp(vault)
    assert r.arreglos[0].startswith("trovefy meta herramientas preparar")
    assert "trovefy meta herramientas importar" in r.arreglos[1]


def test_14_un_comodin_parcial_no_cuenta_como_deny(importado):
    # Solo nombres exactos: un patrón como mcp__meta-ads__ads_update_* no sustituye al nombre exacto.
    _editar_deny(importado, lambda d: [x for x in d if x != "mcp__meta-ads__ads_update_entity"]
                 + ["mcp__meta-ads__ads_update_*"])
    r = verificar_mcp(importado)
    assert r.ok is False and "ads_update_entity" in r.motivo


def test_14_importado_sin_comodines_parciales(importado):
    deny = json.loads(_settings(importado).read_text())["permissions"]["deny"]
    assert not [x for x in deny if x.startswith("mcp__") and "*" in x]


def test_14_servidor_raro_en_meta_tools_falla(importado):
    doc = json.loads((importado / "config/meta_tools.json").read_text())
    doc["servidor"] = "a b"
    (importado / "config/meta_tools.json").write_text(json.dumps(doc))
    r = verificar_mcp(importado)
    assert r.ok is False and "servidor" in r.motivo
