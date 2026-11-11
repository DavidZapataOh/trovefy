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
