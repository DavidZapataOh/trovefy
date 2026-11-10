import pytest
CASOS = [
    ("mcp__meta-ads__ads_update_entity", {"id": "1", "daily_budget": 2500}, "deny"),
    ("mcp__meta-ads__ads_create_campaign", {"name": "x"}, "deny"),
    ("mcp__meta-ads__ads_activate_entity", {"id": "1"}, "deny"),
    ("mcp__meta-ads__ads_get_campaigns", {}, "allow"),
    ("mcp__meta-ads__ads_insights_get", {}, "allow"),
    ("mcp__meta-ads__ads_library_search", {"q": "x"}, "allow"),
    ("mcp__meta-ads__ads_account_get_activity_logs", {}, "allow"),
    ("mcp__meta-ads__ads_herramienta_nueva_desconocida", {}, "deny"),
    ("mcp__otro__ads_update_entity", {}, "deny"),
    ("mcp__otro__ads_get_x", {}, "allow"),
    ("mcp__playwright__browser_click", {}, "allow"),
    ("Bash", {"command": "curl -X POST https://graph.facebook.com/v21.0/act_1/campaigns"}, "deny"),
    ("Bash", {"command": "ls -la"}, "allow"),
    ("WebFetch", {"url": "https://graph.facebook.com/me?access_token=EAAx"}, "deny"),
    ("WebFetch", {"url": "https://example.com/?access_token=x"}, "allow"),
    ("Read", {"file_path": "/tmp/x"}, "allow"),
]

@pytest.mark.parametrize("nombre,entrada,esperado", CASOS)
def test_clasificacion(correr_hook, vault_tmp, nombre, entrada, esperado):
    decision, _ = correr_hook("meta_guard", {"tool_name": nombre, "tool_input": entrada}, vault_tmp)
    assert decision == esperado

def test_escritura_con_prefijos_distintos(correr_hook, vault_tmp):
    for nombre in ["mcp__claude_ai_Meta_Ads__ads_update_entity", "mcp__facebook__ads_create_campaign"]:
        assert correr_hook("meta_guard", {"tool_name": nombre, "tool_input": {}}, vault_tmp)[0] == "deny"

def test_motivo_en_español(correr_hook, vault_tmp):
    _, motivo = correr_hook("meta_guard", {"tool_name": "mcp__meta-ads__ads_update_entity", "tool_input": {}}, vault_tmp)
    assert "solo la hace el ejecutor tras Aceptar" in motivo

def test_bash_graph_disfrazado(correr_hook, vault_tmp):
    for cmd in ["curl GRAPH.FACEBOOK.COM/me",
                "curl https://graph.facebook.com./v21.0/act_1",
                "curl https://graph.fb.com/x",
                "python -c \"import requests; requests.post('https://graph.facebook.com/v21.0/act_1/ads')\""]:
        assert correr_hook("meta_guard", {"tool_name": "Bash", "tool_input": {"command": cmd}}, vault_tmp)[0] == "deny"

def test_stop_no_cambia_lecturas(correr_hook, vault_tmp):
    (vault_tmp / ".trovify" / "STOP").write_text("x")
    assert correr_hook("meta_guard", {"tool_name": "mcp__meta-ads__ads_get_campaigns", "tool_input": {}}, vault_tmp)[0] == "allow"

def test_webfetch_sin_esquema(correr_hook, vault_tmp):
    e = {"tool_name": "WebFetch", "tool_input": {"url": "graph.facebook.com/me?access_token=x"}}
    assert correr_hook("meta_guard", e, vault_tmp)[0] == "deny"
