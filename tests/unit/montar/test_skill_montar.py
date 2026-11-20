"""La skill /trovefy:montar (plan 22, Tarea 10)."""
from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
SKILL = (RAIZ / "skills" / "montar" / "SKILL.md").read_text(encoding="utf-8")


def _meta() -> dict:
    return yaml.safe_load(SKILL.split("---")[1])


def test_skill_montar_existe():
    meta = _meta()
    assert meta["name"] == "montar"
    for d in ("montar", "Activar", "PAUSED"):
        assert d in meta["description"]


def test_skill_sin_escrituras_de_meta():
    herramientas = [h.strip() for h in _meta()["allowed-tools"].split(",")]
    for h in herramientas:
        if h.startswith("mcp__meta-ads__"):
            assert h.removeprefix("mcp__meta-ads__").startswith("ads_get_")  # lectura para hooks/meta_guard.py
        assert "sudo" not in h
    assert {h for h in herramientas if h.startswith("mcp__")} == {
        "mcp__meta-ads__ads_get_ad_accounts", "mcp__meta-ads__ads_get_ad_entities"}
    assert "Bash(trovefy montar *)" in herramientas


def test_ayuda_menciona_montar():
    assert "/trovefy:montar" in (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")


def test_pasos_clave():
    for frase in ("trovefy montar preparar", "trovefy montar validar", "trovefy montar depositar",
                  "trovefy montar registrar --pendientes", "trovefy montar renovacion", "VETO-", "Nunca escribas en Meta"):
        assert frase in SKILL
