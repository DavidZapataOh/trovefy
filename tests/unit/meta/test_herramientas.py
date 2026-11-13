import json
from pathlib import Path

import pytest
from trovefy.meta.herramientas import (
    ListaIlegible,
    clasificar,
    comparar,
    documento,
    escribir_meta_tools,
    herramientas_de,
    leer_documento,
    leer_tools_list,
)
from trovefy.vault.permisos import leer_meta_tools

RAIZ = Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/meta/tools_list.json"


def test_lista_blanca_y_desconocidas():
    assert clasificar("ads_get_campaigns")[0] == "lectura"
    assert clasificar("ads_library_search")[0] == "lectura"
    assert clasificar("ads_update_entity")[0] == "escritura"


def test_desconocida_con_pinta_de_escritura_es_escritura():
    for n in ["ads_update_entity_v2", "ads_campaign_duplicate", "ads_set_budget", "ads_herramienta_nueva"]:
        assert clasificar(n)[0] == "escritura", n


def test_read_only_hint_no_basta():
    clase, motivo = clasificar("ads_estimate_reach", solo_lectura_declarada=True)
    assert clase == "escritura" and "no está en la lista blanca" in motivo


def test_misma_lista_blanca_que_el_hook():
    import sys

    sys.path.insert(0, str(RAIZ / "hooks"))
    import meta_guard

    for n in ["ads_get_x", "ads_insights_y", "ads_library_search", "ads_account_get_activity_logs",
              "ads_update_entity", "ADS_GET_X", "ads_library_search_v2"]:
        hook = meta_guard.clasificar(f"mcp__meta-ads__{n}", {})[0] == "allow"
        assert (clasificar(n)[0] == "lectura") == hook, n


def test_formas_de_tools_list():
    nombres = ["mcp__meta-ads__ads_get_campaigns", "mcp__meta-ads__ads_update_entity"]
    assert leer_tools_list(nombres)[0] == "meta-ads"
    assert leer_tools_list({"result": {"tools": [{"name": "ads_get_x"}]}}) == (None, [{"name": "ads_get_x"}])
    with pytest.raises(ListaIlegible):
        leer_tools_list(["mcp__meta-ads__ads_get_a", "mcp__otro__ads_get_b"])
    with pytest.raises(ListaIlegible):
        leer_tools_list([{"name": "ads get; rm"}])


def test_comparar_detecta_renombradas():
    antes = {"tools": [{"name": "ads_update_entity", "clase": "escritura"}, {"name": "ads_get_a", "clase": "lectura"}]}
    c = comparar(antes, herramientas_de([{"name": "ads_update_entity_v2"}, {"name": "ads_get_a"}]))
    assert c.nuevas == ["ads_update_entity_v2"] and c.desaparecidas == ["ads_update_entity"]


def test_documento_compatible_con_permisos(tmp_path):
    _, crudas = leer_tools_list(json.loads(FIX.read_text()))
    ruta = escribir_meta_tools(tmp_path, documento("meta-ads", herramientas_de(crudas), "tools_list.json", "2026-11-13"))
    assert ruta == tmp_path / "config" / "meta_tools.json"
    assert "ads_update_entity" in leer_meta_tools(tmp_path)
    doc = leer_documento(tmp_path)
    assert doc["version"] == 1 and doc["servidor"] == "meta-ads"
    por = {t["name"]: t for t in doc["tools"]}
    assert por["ads_library_search"]["clase"] == "lectura"
    assert por["ads_library_search"]["argumentos"] == sorted(por["ads_library_search"]["argumentos"])
    assert por["ads_estimate_reach"]["clase"] == "escritura"
    assert por["ads_estimate_reach"]["solo_lectura_declarada"] is True
    assert por["ads_get_campaigns"]["solo_lectura_declarada"] is None


def test_comparar_cambio_de_clase_y_sin_anterior():
    c = comparar({"tools": [{"name": "ads_x", "clase": "lectura"}]}, herramientas_de([{"name": "ads_x"}]))
    assert c.cambian_de_clase == ["ads_x"]
    assert comparar(None, herramientas_de([{"name": "ads_a"}])).nuevas == ["ads_a"]


def test_leer_documento_ausente_y_corrupto(tmp_path):
    assert leer_documento(tmp_path) is None
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "meta_tools.json").write_text("{no", encoding="utf-8")
    with pytest.raises(ListaIlegible):
        leer_documento(tmp_path)
