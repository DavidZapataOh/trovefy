import json
import pathlib

import yaml

RAIZ = pathlib.Path(__file__).resolve().parents[2]

def test_manifiesto_del_plugin():
    m = json.loads((RAIZ / ".claude-plugin/plugin.json").read_text())
    assert m["name"] == "trovefy"
    assert m["version"] == "0.1.0"

def test_cada_skill_tiene_frontmatter_valido():
    for skill in (RAIZ / "skills").glob("*/SKILL.md"):
        cabecera = skill.read_text().split("---")[1]
        meta = yaml.safe_load(cabecera)
        assert meta["name"] == skill.parent.name
        assert meta["description"].strip()
        assert "allowed-tools" in meta

def test_cada_agente_tiene_frontmatter_valido():
    agentes = sorted((RAIZ / "agents").glob("*.md"))
    assert {a.stem for a in agentes} >= {"revisor", "nativo"}
    for agente in agentes:
        texto = agente.read_text()
        _, cabecera, cuerpo = texto.split("---", 2)
        meta = yaml.safe_load(cabecera)
        assert meta["name"] == agente.stem
        assert meta["description"].strip()
        herramientas = {t.strip() for t in meta["tools"].split(",")}
        assert herramientas <= {"Read", "Glob", "Grep"}
        assert "VEREDICTO: ok" in cuerpo
        assert "VEREDICTO: corregir" in cuerpo
