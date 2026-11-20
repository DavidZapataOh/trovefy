"""La skill /trovefy:leer y sus entradas de rutina (plan 23, Tarea 10)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from trovefy.vault.permisos import es_lectura_meta

RAIZ = Path(__file__).resolve().parents[3]
SKILL = (RAIZ / "skills" / "leer" / "SKILL.md").read_text(encoding="utf-8")
CATALOGO = yaml.safe_load((RAIZ / "templates" / "systemd" / "rutinas.yaml").read_text(encoding="utf-8"))


def _herramientas() -> list[str]:
    return [h.strip() for h in yaml.safe_load(SKILL.split("---")[1])["allowed-tools"].split(",")]


def _impultienda() -> dict:
    datos = json.loads((RAIZ / "config" / "impultienda_tools.json").read_text(encoding="utf-8"))
    h = datos["herramientas"]
    return h if isinstance(h, dict) else {x["nombre"]: x for x in h}


def test_skill_solo_lectura():
    catalogo = _impultienda()
    for h in _herramientas():
        assert "sudo" not in h and "dangerously" not in h
        if h.startswith("mcp__meta-ads__"):
            assert es_lectura_meta(h.removeprefix("mcp__meta-ads__")), h
        if h.startswith("mcp__impultienda__"):
            assert catalogo[h.removeprefix("mcp__impultienda__")]["clase"] == "lectura", h
        if h.startswith(("Write", "Edit")):
            assert "~/.cache/trovefy/leer/" in h, h
    assert "Bash(trovefy leer *)" in _herramientas()
    assert "impultienda_ver_pago" not in SKILL  # prohibida en el catálogo (resolución 15)


def test_rutinas_subconjunto_de_la_skill_y_sin_fijar_economia():
    permitidas = set(_herramientas())
    assert set(CATALOGO) >= {"parte", "intradia", "base"}
    for nombre in ("parte", "intradia", "base"):
        r = CATALOGO[nombre]
        assert r["skill"] == "leer" and "--rutina" in r["argumentos"]
        assert set(r["herramientas"]) <= permitidas, nombre
        assert not any("fijar" in h or "recalcular" in h or "ver_plan" in h for h in r["herramientas"])
    assert CATALOGO["intradia"]["calendario"] == "*-*-* 00/2:00:00 {zona}" and CATALOGO["intradia"]["por_pais"]
    assert CATALOGO["base"]["calendario"] == "*-*-* 23:00:00 {zona}"
    assert CATALOGO["parte"]["calendario"].startswith("*-*-* 07:30:00 America/Bogota")


def test_ayuda_menciona_leer():
    assert "/trovefy:leer" in (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")


def test_pasos_clave():
    for frase in ("trovefy leer preparar", "trovefy leer importar", "trovefy leer parte", "trovefy leer intradia",
                  "trovefy leer base", "trovefy montar registrar --pendientes", "Nunca escribas en Meta",
                  "requires_user_confirmation", "desvío D1", "--seco"):
        assert frase in SKILL, frase


def test_sin_reglas_de_venta_agresiva():
    texto = SKILL.lower()
    for palabra in ("urgencia", "escasez", "prueba social", "cura"):
        assert palabra not in texto
