from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]


def test_skill_cazar_orden_d11_y_sin_mezclas():
    t = (RAIZ / "skills/cazar/SKILL.md").read_text()
    for x in [
        "mcp__meta-ads__ads_library_search", "--desde-mcp", "Nunca mezcles fuentes en silencio",
        "--respaldo-publico", "tal cual", "--rutina` nunca usa el MCP", "Write(data/caza/mcp/**)",
        "config/meta_tools.json", "PARADA", "MCP oficial, Firecrawl o Playwright",
    ]:
        assert x in t, x
    assert "Write(config" not in t.split("---")[1]
