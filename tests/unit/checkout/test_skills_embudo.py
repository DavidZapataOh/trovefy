"""Las skills `/tracking` y `/checkout` (plan 19, Tarea 16): sus reglas, sus herramientas y la ayuda."""

import re
from pathlib import Path

import yaml
from trovefy.tienda.mcp import PREFIJO_MCP, cargar_catalogo, nombre_mcp, permitidas

RAIZ = Path(__file__).resolve().parents[3]
SKILLS = ("tracking", "checkout")
LECTURAS_META = {f"mcp__meta-ads__{n}" for n in ("ads_get_datasets", "ads_get_dataset_details",
                                                  "ads_get_dataset_stats", "ads_get_dataset_quality")}


def _skill(nombre: str) -> tuple[dict, str, str]:
    texto = (RAIZ / "skills" / nombre / "SKILL.md").read_text(encoding="utf-8")
    _, cabecera, cuerpo = texto.split("---", 2)
    return yaml.safe_load(cabecera), cuerpo, texto


def _herramientas(meta: dict) -> set[str]:
    return {t.strip() for t in meta["allowed-tools"].split(",")}


def test_skills_embudo():
    for nombre in SKILLS:
        meta, _, texto = _skill(nombre)
        assert meta["name"] == nombre and meta["description"].strip()
        for frase in ("resumen en seco", "lo pega el usuario", "terminal aparte", "trovefy checkout aprobar",
                      "¿Estás en el cerebro?", "no medido: <motivo>", "pendiente de Aprobar en el panel",
                      "Nunca escribas en Meta", "Mira cada captura con Read",
                      "Nunca uses una herramienta que no esté en la skill", "Nunca abras ni inicies sesión en ningún panel"):
            assert frase in texto, (nombre, frase)
        assert "ads_pixel_event_read" not in texto, nombre
        assert "trovefy navegador abrir" not in texto, nombre
        assert "sudo -u trovefy-exec" in texto, nombre
    ayuda = (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")
    assert "/trovefy:tracking" in ayuda and "/trovefy:checkout" in ayuda


def test_skill_tracking_herramientas():
    meta, _, _ = _skill("tracking")
    h = _herramientas(meta)
    assert {"Read", "Write(~/.cache/trovefy/tracking/**)", "Bash(trovefy tracking *)",
            "Bash(trovefy checkout evidencia *)"} | LECTURAS_META == h
    assert not any(t.startswith(PREFIJO_MCP) for t in h)


def test_skill_checkout_herramientas():
    meta, cuerpo, _ = _skill("checkout")
    h = _herramientas(meta)
    assert {"Read", "Write(~/.cache/trovefy/checkout/**)", "Bash(trovefy checkout *)",
            "Bash(trovefy tracking eventos *)"} <= h
    assert not any(t.startswith("mcp__meta-ads__") for t in h)
    assert "trovefy checkout cerrar" in cuerpo and "trovefy checkout excepcion" in cuerpo
    assert "no admiten excepción" in cuerpo


def test_skill_solo_herramientas_clasificadas():
    """Cada `mcp__impultienda__*` de las skills es `lectura` o `escritura` en el catálogo; ninguna `prohibida`."""
    catalogo = cargar_catalogo()
    lectura, escritura = set(permitidas(catalogo, "lectura")), set(permitidas(catalogo, "escritura"))
    prohibidas = {n for n, x in catalogo.items() if x.clase == "prohibida"}
    for nombre in SKILLS:
        meta, cuerpo, _ = _skill(nombre)
        mcp = {t for t in _herramientas(meta) if t.startswith(PREFIJO_MCP)}
        for t in mcp:
            corto = t.removeprefix(PREFIJO_MCP)
            assert corto in lectura | escritura, (nombre, t)
            assert corto not in prohibidas, (nombre, t)
        for corto in re.findall(r"impultienda_[a-z_]+", cuerpo):
            assert corto not in prohibidas, (nombre, corto)
    meta, _, _ = _skill("checkout")
    assert {nombre_mcp(n) for n in lectura | escritura} == {t for t in _herramientas(meta)
                                                            if t.startswith(PREFIJO_MCP)}
