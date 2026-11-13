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
    ("WebFetch", {"url": "https://x@graph.facebook.com/v21.0/me?access_token=EAA"}, "deny"),
    ("WebFetch", {"url": "https://GRAPH.FACEBOOK.COM:443/me?access_token=EAA"}, "deny"),
    ("WebFetch", {"url": "https://graph.facebook.com/me?access%5Ftoken=EAA"}, "deny"),
    ("WebFetch", {"url": "https://graph.facebook.com/me?%61ccess_token=EAA"}, "deny"),
    ("WebFetch", {"url": "https://graph.facebook.com/me?method=post"}, "deny"),
    ("WebFetch", {"url": "https://example.com/doc"}, "allow"),
    ("mcp__playwright__browser_navigate", {"url": "https://graph.facebook.com/v21.0/me"}, "deny"),
    ("mcp__playwright__browser_navigate", {"url": "https://graph%2Efacebook.com/x"}, "deny"),
    ("mcp__playwright__browser_navigate", {"url": "https://example.com"}, "allow"),
    ("mcp__firecrawl__firecrawl_scrape", {"url": "https://graph.fb.com/x"}, "deny"),
    ("Write", {"file_path": "/tmp/n.md", "content": "usa graph.facebook.com solo en docs"}, "allow"),
    ("ADS_UPDATE_ENTITY", {}, "allow"),
    ("mcp__ads_update", {}, "deny"),
    ("mcp__meta", {}, "deny"),
    ("mcp__facebook", {}, "deny"),
    ("mcp__meta__ads__update_entity", {}, "deny"),
    ("MCP__META__ADS_UPDATE", {}, "deny"),
    ("MCP__META__ADS_GET_CAMPAIGNS", {}, "allow"),
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
    (vault_tmp / ".trovefy" / "STOP").write_text("x")
    assert correr_hook("meta_guard", {"tool_name": "mcp__meta-ads__ads_get_campaigns", "tool_input": {}}, vault_tmp)[0] == "allow"

def test_webfetch_sin_esquema(correr_hook, vault_tmp):
    e = {"tool_name": "WebFetch", "tool_input": {"url": "graph.facebook.com/me?access_token=x"}}
    assert correr_hook("meta_guard", e, vault_tmp)[0] == "deny"


def test_graph_video_y_subdominios_graph(correr_hook, vault_tmp):
    cmd = "curl -X POST -F source=@v.mp4 https://graph-video.facebook.com/v21.0/act_1/advideos"
    assert correr_hook("meta_guard", {"tool_name": "Bash", "tool_input": {"command": cmd}}, vault_tmp)[0] == "deny"
    e = {"tool_name": "WebFetch", "tool_input": {"url": "https://graph-video.facebook.com/v21.0/act_1/advideos"}}
    assert correr_hook("meta_guard", e, vault_tmp)[0] == "deny"
    e = {"tool_name": "mcp__playwright__browser_navigate", "tool_input": {"url": "https://graph-video.facebook.com/x"}}
    assert correr_hook("meta_guard", e, vault_tmp)[0] == "deny"
    e = {"tool_name": "WebFetch", "tool_input": {"url": "https://www.facebook.com/help"}}
    assert correr_hook("meta_guard", e, vault_tmp)[0] == "allow"


def test_servidor_meta_por_token_no_por_subcadena(correr_hook, vault_tmp):
    for nombre in ("mcp__metabase__run_query", "mcp__obsidian-metadata__get"):
        assert correr_hook("meta_guard", {"tool_name": nombre, "tool_input": {}}, vault_tmp)[0] == "allow", nombre
    for nombre in ("mcp__meta-ads__ads_update_entity", "mcp__claude_ai_Meta_Ads__ads_update_entity",
                   "mcp__facebook__x", "mcp__fb__x", "mcp__metaads__x"):
        assert correr_hook("meta_guard", {"tool_name": nombre, "tool_input": {}}, vault_tmp)[0] == "deny", nombre


def test_stop_deniega_depositar_en_meta_guard(correr_hook, vault_tmp):
    cmd = {"tool_name": "Bash", "tool_input": {"command": "trovefy buzon depositar p.json"}}
    assert correr_hook("meta_guard", cmd, vault_tmp)[0] == "allow"
    (vault_tmp / ".trovefy" / "STOP").write_text("x")
    d, m = correr_hook("meta_guard", cmd, vault_tmp)
    assert d == "deny" and "STOP activo: no se deposita nada" in m
    cmd2 = {"tool_name": "Bash", "tool_input": {"command": "cp x /var/spool/trovefy/entrada/P-1.json"}}
    assert correr_hook("meta_guard", cmd2, vault_tmp)[0] == "deny"
    assert correr_hook("meta_guard", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, vault_tmp)[0] == "allow"
