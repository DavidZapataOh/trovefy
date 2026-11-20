"""La skill /trovefy:creativos (plan 21, Tarea 14)."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
CARPETA = RAIZ / "skills" / "creativos"
SKILL = (CARPETA / "SKILL.md").read_text(encoding="utf-8")


def _meta() -> dict:
    return yaml.safe_load(SKILL.split("---")[1])


def test_frontmatter_valido():
    meta = _meta()
    assert meta["name"] == "creativos"
    for disparador in ("creativos", "anuncios", "renovar"):
        assert disparador in meta["description"]


def test_skill_sin_meta():
    meta = _meta()
    for prohibido in ("mcp__meta-ads", "mcp__impultienda", "mcp__higgsfield", "WebFetch"):
        assert prohibido not in meta["allowed-tools"] and prohibido not in SKILL


def test_allowed_tools_solo_trovefy_creativos():
    herramientas = [h.strip() for h in _meta()["allowed-tools"].split(", ")]
    assert herramientas == ["Read", "Glob", "Agent", "Write(productos/*/creativos/*/*/brief.yaml)",
                            "Write(productos/*/creativos/*/*/escenas.yaml)",
                            "Write(productos/*/creativos/*/*/guiones/*.yaml)", "Bash(trovefy creativos *)",
                            "Bash(trovefy montar renovacion *)"]


def test_pasos_y_reglas():
    for frase in ("aprobar-coste", "espera su «sí»", "trovefy creativos coste", "--solo-gancho", "--agente revisor",
                  "--agente nativo", "trovefy creativos cerrar", "trovefy creativos renovar", "trovefy creativos rehacer",
                  "STOP lo quita solo el usuario", "Nada ajeno entra", "US$ 6", "US$ 2", "en palabras",
                  "«no medido» se dice tal cual", "Nada se escribe en Meta"):
        assert frase in SKILL, frase
    assert (CARPETA / "references" / "brief.md").is_file() and (CARPETA / "references" / "formatos.md").is_file()


def test_ayuda_menciona_creativos():
    assert "/trovefy:creativos" in (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")
